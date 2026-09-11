"""Fuente de catalogo a partir de ficheros: CSV, TSV, JSON o XLSX.

Sirve para arrancar sin integracion (una exportacion del catalogo) y para
cargar los ficheros que el equipo ya maneja hoy.
"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from typing import Any, Iterator

from ..normalize import slug
from .base import RawProduct, SourceError

__all__ = ["FileCatalogSource"]

#: nombres de columna habituales para los campos fijos de la ficha
_DEFAULT_COLUMNS = {
    "reference": ["referencia", "reference", "ref", "codigo", "sku", "part number", "pn", "mpn"],
    "manufacturer": ["fabricante", "manufacturer", "marca", "brand"],
    "description": ["descripcion", "description", "nombre", "name", "titulo", "title"],
    "family": ["familia", "family", "tipo", "type"],
    "url": ["url", "enlace", "link", "ficha"],
    "datasheet_url": ["datasheet", "hoja de datos", "ficha tecnica", "pdf"],
    "category_path": ["categoria", "category", "categorias", "familia web", "seccion"],
}


class FileCatalogSource:
    """Lee un fichero tabular donde cada fila es una referencia del catalogo.

    Las columnas que no sean campos fijos se guardan como especificaciones,
    con su nombre original, para que el mapeo al esquema sea revisable.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.id = str(config.get("id", "fichero"))
        self.config = config
        self.path = Path(config["path"])
        self.columns: dict[str, str] = {k: str(v) for k, v in (config.get("columns") or {}).items()}
        self.spec_columns: list[str] | None = config.get("spec_columns")
        self.ignore_columns = {slug(c) for c in config.get("ignore_columns", [])}
        self.delimiter = config.get("delimiter")
        self.encoding = config.get("encoding", "utf-8-sig")
        self.family_by_category: dict[str, str] = {
            str(k): str(v) for k, v in (config.get("family_by_category") or {}).items()
        }
        if not self.path.exists():
            raise SourceError(f"fichero de catalogo inexistente: {self.path}")

    def fetch(self, limit: int | None = None) -> Iterator[RawProduct]:
        rows = self._rows()
        for index, row in enumerate(rows):
            if limit is not None and index >= limit:
                return
            product = self._to_product(row)
            if product is not None:
                yield product

    # ------------------------------------------------------------------ lectura

    def _rows(self) -> Iterator[dict[str, Any]]:
        suffix = self.path.suffix.lower()
        if suffix in (".csv", ".tsv", ".txt"):
            yield from self._csv_rows()
        elif suffix == ".json":
            yield from self._json_rows()
        elif suffix in (".xlsx", ".xlsm"):
            yield from self._xlsx_rows()
        else:
            raise SourceError(f"extension no soportada: {suffix}")

    def _csv_rows(self) -> Iterator[dict[str, Any]]:
        with self.path.open("r", encoding=self.encoding, newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            delimiter = self.delimiter
            if not delimiter:
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                except csv.Error:
                    delimiter = "\t" if self.path.suffix.lower() == ".tsv" else ","
            for row in csv.DictReader(handle, delimiter=delimiter):
                yield {k: v for k, v in row.items() if k}

    def _json_rows(self) -> Iterator[dict[str, Any]]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        records = data
        pointer = self.config.get("records_path")
        if pointer:
            for part in str(pointer).split("."):
                records = records[part]
        if isinstance(records, dict):
            records = list(records.values())
        for row in records:
            if isinstance(row, dict):
                yield row

    def _xlsx_rows(self) -> Iterator[dict[str, Any]]:
        """Lector minimo de XLSX (sin dependencias externas)."""
        import re
        from xml.etree import ElementTree

        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(self.path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                tree = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")) for si in tree]
            sheet_name = self.config.get("sheet", "xl/worksheets/sheet1.xml")
            if sheet_name not in archive.namelist():
                raise SourceError(f"hoja no encontrada en {self.path}: {sheet_name}")
            tree = ElementTree.fromstring(archive.read(sheet_name))
            header: list[str] = []
            for row in tree.iter(f"{{{ns['m']}}}row"):
                values: dict[int, str] = {}
                for cell in row.iter(f"{{{ns['m']}}}c"):
                    ref = cell.get("r", "")
                    column = _column_index(re.sub(r"\d", "", ref))
                    raw = cell.find(f"{{{ns['m']}}}v")
                    text = ""
                    if cell.get("t") == "s" and raw is not None:
                        text = shared[int(raw.text or 0)]
                    elif cell.get("t") == "inlineStr":
                        node = cell.find(f"{{{ns['m']}}}is/{{{ns['m']}}}t")
                        text = node.text or "" if node is not None else ""
                    elif raw is not None:
                        text = raw.text or ""
                    values[column] = text
                cells = [values.get(i, "") for i in range(max(values) + 1)] if values else []
                if not header:
                    header = [c.strip() for c in cells]
                    continue
                if any(c.strip() for c in cells):
                    yield {header[i]: cells[i] for i in range(min(len(header), len(cells)))}

    # ------------------------------------------------------------------- mapeo

    def _to_product(self, row: dict[str, Any]) -> RawProduct | None:
        lookup = {slug(k): (k, v) for k, v in row.items() if k}
        used: set[str] = set()

        def take(field: str) -> str | None:
            explicit = self.columns.get(field)
            names = [explicit] if explicit else _DEFAULT_COLUMNS.get(field, [])
            for name in names:
                entry = lookup.get(slug(name))
                if entry and str(entry[1]).strip():
                    used.add(slug(entry[0]))
                    return str(entry[1]).strip()
            return None

        # Se resuelven todos los campos fijos antes de construir las specs,
        # para que sus columnas queden marcadas como usadas.
        reference = take("reference")
        if not reference:
            return None
        manufacturer = take("manufacturer")
        description = take("description")
        url = take("url")
        datasheet_url = take("datasheet_url")
        family = take("family")
        categories_raw = take("category_path") or ""
        categories = [c.strip() for c in categories_raw.replace("|", ">").split(">") if c.strip()]

        if self.spec_columns is not None:
            specs = {c: str(row.get(c, "")).strip() for c in self.spec_columns if str(row.get(c, "")).strip()}
        else:
            specs = {
                key: str(value).strip()
                for key, value in row.items()
                if key
                and slug(key) not in used
                and slug(key) not in self.ignore_columns
                and str(value or "").strip()
            }

        if not family and categories:
            for category in categories:
                if category in self.family_by_category:
                    family = self.family_by_category[category]
                    break

        return RawProduct(
            reference=reference,
            url=url,
            manufacturer=manufacturer,
            description=description,
            family_hint=family,
            category_path=categories,
            specs=specs,
            datasheet_url=datasheet_url,
        )


def _column_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - 64)
    return max(0, index - 1)
