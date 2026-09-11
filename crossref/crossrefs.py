"""Tabla de equivalencias ya declaradas (competencia -> referencia propia).

Un fabricante suele tener listas historicas de "esta referencia de la
competencia se sustituye por esta nuestra". Esas equivalencias valen mas que
cualquier comparacion de parametros: son decisiones ya tomadas y validadas.

Se cargan aqui y quedan asociadas a la ficha del catalogo, con su procedencia,
para que el resultado pueda citarla y se pueda auditar.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .normalize import normalize_pn, slug
from .store import CatalogStore

__all__ = ["CrossReference", "load_cross_reference_file", "apply_cross_references", "CrossRefReport"]

#: nombres de columna admitidos para cada campo
_COLUMNS = {
    "competitor_reference": [
        "referencia competencia", "referencia de competencia", "competidor", "competitor",
        "competitor part number", "competitor pn", "referencia externa", "referencia cliente",
        "cross reference", "cross ref", "mpn", "part number", "referencia ajena",
    ],
    "competitor_manufacturer": [
        "fabricante competencia", "fabricante", "manufacturer", "marca", "brand",
        "competitor manufacturer",
    ],
    "our_reference": [
        "referencia propia", "nuestra referencia", "referencia", "our reference",
        "we reference", "reference", "codigo propio", "sku", "articulo",
    ],
    "note": ["nota", "note", "observaciones", "comentario", "comment", "remarks"],
}


@dataclass
class CrossReference:
    """Una equivalencia declarada entre una referencia ajena y una propia."""

    competitor_reference: str
    our_reference: str
    competitor_manufacturer: str | None = None
    note: str | None = None
    source: str = "tabla de equivalencias"


@dataclass
class CrossRefReport:
    """Resultado de cargar una tabla de equivalencias."""

    source: str
    applied: int = 0
    items_updated: int = 0
    unknown_references: list[str] = None  # referencias propias que no estan en el catalogo

    def __post_init__(self) -> None:
        if self.unknown_references is None:
            self.unknown_references = []

    def summary_lines(self) -> list[str]:
        lines = [
            f"Tabla '{self.source}': {self.applied} equivalencias aplicadas "
            f"sobre {self.items_updated} referencias del catalogo."
        ]
        if self.unknown_references:
            lines.append(
                f"  ! {len(self.unknown_references)} referencias propias no estan en el "
                f"catalogo (ejemplos: {', '.join(self.unknown_references[:5])}). "
                "Sincroniza el catalogo primero o revisa esos codigos."
            )
        return lines

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "applied": self.applied,
            "items_updated": self.items_updated,
            "unknown_references": self.unknown_references[:50],
            "unknown_total": len(self.unknown_references),
        }


def load_cross_reference_file(path: str | Path, source: str | None = None) -> Iterator[CrossReference]:
    """Lee un CSV de equivalencias, tolerando distintos nombres de columna."""
    file_path = Path(path)
    origin = source or file_path.name
    with file_path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            return
        lookup = {slug(name): name for name in reader.fieldnames if name}

        def column(field: str) -> str | None:
            for candidate in _COLUMNS[field]:
                if slug(candidate) in lookup:
                    return lookup[slug(candidate)]
            return None

        competitor_col = column("competitor_reference")
        our_col = column("our_reference")
        if not competitor_col or not our_col:
            raise ValueError(
                "el fichero necesita una columna de referencia de la competencia y otra "
                f"de referencia propia. Columnas encontradas: {reader.fieldnames}"
            )
        manufacturer_col = column("competitor_manufacturer")
        note_col = column("note")

        for row in reader:
            competitor = str(row.get(competitor_col, "")).strip()
            ours = str(row.get(our_col, "")).strip()
            if not competitor or not ours:
                continue
            yield CrossReference(
                competitor_reference=competitor,
                our_reference=ours,
                competitor_manufacturer=(str(row[manufacturer_col]).strip()
                                         if manufacturer_col and row.get(manufacturer_col) else None),
                note=(str(row[note_col]).strip() if note_col and row.get(note_col) else None),
                source=origin,
            )


def apply_cross_references(
    store: CatalogStore,
    entries: Iterable[CrossReference],
    source: str = "tabla de equivalencias",
) -> CrossRefReport:
    """Asocia cada equivalencia a su ficha del catalogo, sin duplicar."""
    report = CrossRefReport(source=source)
    by_reference: dict[str, list[CrossReference]] = {}
    for entry in entries:
        by_reference.setdefault(normalize_pn(entry.our_reference), []).append(entry)

    for normalized, group in by_reference.items():
        items = store.by_reference(normalized)
        if not items:
            report.unknown_references.append(group[0].our_reference)
            continue
        for item in items:
            declared = list(item.extra.get("cross_references") or [])
            known = {
                normalize_pn(d["reference"] if isinstance(d, dict) else d)
                for d in declared
                if (d.get("reference") if isinstance(d, dict) else d)
            }
            added = 0
            for entry in group:
                if normalize_pn(entry.competitor_reference) in known:
                    continue
                declared.append(
                    {
                        "reference": entry.competitor_reference,
                        "manufacturer": entry.competitor_manufacturer,
                        "note": entry.note,
                        "source": entry.source,
                    }
                )
                known.add(normalize_pn(entry.competitor_reference))
                added += 1
            if added:
                item.extra["cross_references"] = declared
                store.upsert([item])
                report.applied += added
                report.items_updated += 1
    return report
