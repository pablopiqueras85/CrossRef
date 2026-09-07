"""Conector para catalogos que publican una TABLA de articulos por serie.

Muchos catalogos de fabricante no tienen una pagina por referencia: tienen una
pagina por linea de producto con una tabla donde cada fila es una referencia y
cada columna un parametro. Leer esa tabla es mucho mas barato y mas fiable que
visitar miles de fichas, y suele traer el dato ya etiquetado.

El recorrido tiene dos niveles:

    categoria  ->  enlaces a las series  ->  tabla de articulos de cada serie

Todo se configura en YAML: selectores de la tabla, de que atributo sale el
valor y que columnas ignorar.
"""

from __future__ import annotations

import re
from typing import Any, Iterator
from urllib.parse import urldefrag, urljoin

import httpx
from selectolax.parser import HTMLParser

from .base import RawProduct, SourceError
from .fetcher import WebFetcher

__all__ = ["WebTableCatalogSource"]

#: guion suave y espacios raros que los catalogos meten en las cabeceras
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍﻿"), None)


class WebTableCatalogSource:
    """Extrae una referencia por fila de las tablas de articulos del catalogo."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self.id = str(config.get("id", "web_table"))
        self.config = config
        self.fetcher = WebFetcher(config, client)
        self.base_url = self.fetcher.base_url

        self.categories: list[dict[str, Any]] = list(config.get("categories") or [])
        if not self.categories and not config.get("series_urls"):
            raise SourceError("la fuente web_table necesita 'categories' o 'series_urls'")

        series = config.get("series") or {}
        self.series_pattern = re.compile(str(series.get("url_pattern", r".")))
        exclude = series.get("exclude_pattern")
        #: kits de diseño, bolsas de filtros y manuales viven en las mismas
        #: rejillas que las series de producto, pero no son componentes
        self.series_exclude = re.compile(str(exclude)) if exclude else None
        #: acota donde buscar los enlaces: si no, las migas de pan y el menu
        #: cuelan paginas que no son series
        self.series_link_selector = str(series.get("link_selector", "a[href]"))
        self.series_title_selector = str(series.get("title_selector", "h1"))
        self.series_from_url = re.compile(str(series.get("name_from_url", r"([^/]+)$")))

        table = config.get("table") or {}
        self.table_selector = str(table.get("selector", "table"))
        self.row_selector = str(table.get("row_selector", "tr"))
        self.cell_selector = str(table.get("cell_selector", "td[data-column]"))
        self.label_attr = str(table.get("label_attr", "data-column"))
        self.label_selector = table.get("label_selector")
        self.unit_attr = table.get("unit_attr")
        self.value_attr = table.get("value_attr")
        #: selector especifico del valor para columnas concretas
        self.value_selectors = {
            _clean_label(k): str(v) for k, v in (table.get("value_selectors") or {}).items()
        }
        self.reference_columns = [
            _clean_label(c) for c in table.get("reference_columns", ["Order Code"])
        ]
        self.datasheet_selector = table.get("datasheet_selector")
        self.status_column = _clean_label(table.get("status_column", "")) or None
        self.active_values = {
            str(v).strip().lower() for v in table.get("active_values", ["active"])
        }
        self.only_active = bool(table.get("only_active", False))
        self.ignore_columns = {_clean_label(c) for c in table.get("ignore_columns", [])}

    # ------------------------------------------------------------------ publico

    def fetch(self, limit: int | None = None) -> Iterator[RawProduct]:
        count = 0
        for category in self._categories():
            for series_url in self._series_urls(category):
                html = self.fetcher.get(series_url)
                if html is None:
                    continue
                for product in self.parse_table(html, series_url, category):
                    if limit is not None and count >= limit:
                        return
                    count += 1
                    yield product

    def close(self) -> None:
        self.fetcher.close()

    def __enter__(self) -> "WebTableCatalogSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- recorrido

    def _categories(self) -> list[dict[str, Any]]:
        if self.categories:
            return self.categories
        return [{"series_urls": self.config.get("series_urls", [])}]

    def _series_urls(self, category: dict[str, Any]) -> list[str]:
        """URLs de las series: las indicadas a mano o las enlazadas en la categoria."""
        explicit = category.get("series_urls") or []
        if explicit:
            return [urljoin(self.base_url + "/", str(u)) for u in explicit]

        category_url = category.get("url")
        if not category_url:
            raise SourceError(f"categoria sin 'url' ni 'series_urls': {category}")
        html = self.fetcher.get(urljoin(self.base_url + "/", str(category_url)))
        if html is None:
            raise SourceError(f"no se ha podido descargar la categoria {category_url}")

        tree = HTMLParser(html)
        found: list[str] = []
        for node in tree.css(self.series_link_selector):
            href = urldefrag(node.attributes.get("href", ""))[0]
            if not href or not self.series_pattern.search(href):
                continue
            if self.series_exclude and self.series_exclude.search(href):
                continue
            if True:
                absolute = urljoin(self.base_url + "/", href)
                if absolute not in found:
                    found.append(absolute)
        return found

    # --------------------------------------------------------------- parseo

    def parse_table(
        self, html: str, url: str, category: dict[str, Any] | None = None
    ) -> Iterator[RawProduct]:
        """Convierte cada fila de la tabla en una ficha. Publico para poder probarlo."""
        category = category or {}
        tree = HTMLParser(html)
        table = tree.css_first(self.table_selector)
        if table is None:
            return

        series_name = self._series_name(tree, url)
        category_path = [str(c) for c in category.get("category_path", []) if c]

        for row in table.css(self.row_selector):
            cells = row.css(self.cell_selector)
            if not cells:
                continue
            specs: dict[str, str] = {}
            reference = None
            datasheet = None
            for cell in cells:
                label, value = self._read_cell(cell)
                if not label or label in self.ignore_columns:
                    continue
                if label in self.reference_columns:
                    reference = value or None
                    continue
                if value:
                    specs[label] = value
            if self.datasheet_selector:
                link = row.css_first(self.datasheet_selector)
                if link is not None and link.attributes.get("href"):
                    datasheet = urljoin(url, link.attributes["href"])
            if not reference:
                continue
            if self.only_active and self.status_column:
                status = (specs.get(self.status_column) or "").strip().lower()
                if status and not any(a in status for a in self.active_values):
                    continue
            if series_name:
                specs.setdefault("Series", series_name)
            # Datos que la categoria da por sabidos y no publica como columna
            # (p. ej. la frecuencia de medida, que va dentro del nombre de la
            # columna "Z @ 100 MHz"). No pisan nunca a una columna real.
            for key, value in (category.get("constant_specs") or {}).items():
                if str(value).strip():
                    specs.setdefault(str(key), str(value))

            yield RawProduct(
                reference=reference,
                url=f"{url}#{reference}",
                manufacturer=self.config.get("manufacturer"),
                description=" ".join(filter(None, [series_name, reference])),
                # Una categoria como "EMC Components" mezcla ferritas, chokes,
                # varistores y apantallamiento: el nombre de la serie es mucho
                # mejor pista que la categoria para clasificar la ficha.
                family_hint=category.get("family") or series_name,
                category_path=category_path,
                specs=specs,
                datasheet_url=datasheet,
                extra={"series_url": url},
            )

    def _series_name(self, tree: HTMLParser, url: str) -> str | None:
        node = tree.css_first(self.series_title_selector)
        if node is not None and node.text(strip=True):
            return _clean_label(node.text(strip=True))
        match = self.series_from_url.search(urldefrag(url)[0])
        return match.group(1) if match else None

    def _read_cell(self, cell) -> tuple[str, str]:
        """Etiqueta y valor de una celda.

        La etiqueta sale del atributo de columna, que es unico dentro de la
        fila. La etiqueta que algunos catalogos esconden en la celda para la
        vista movil NO sirve como clave: dos columnas distintas pueden
        compartirla (en este catalogo, "Zmax" y "Test Condition Zmax" se
        anuncian las dos como "Maximum Impedance") y una pisaria a la otra.
        Se usa solo cuando no hay atributo de columna, y siempre se descarta
        del texto para que no contamine el valor.
        """
        label = _clean_label(cell.attributes.get(self.label_attr, ""))
        if self.label_selector:
            hidden = cell.css_first(self.label_selector)
            if hidden is not None:
                if not label:
                    label = _clean_label(hidden.text(strip=True))
                hidden.decompose()

        specific = self.value_selectors.get(label)
        if specific:
            node = cell.css_first(specific)
            return label, _clean_value(node.text(separator=" ", strip=True) if node else "")

        value_node = cell.css_first(f"[{self.value_attr}]") if self.value_attr else None
        if value_node is not None:
            raw = value_node.attributes.get(self.value_attr) or value_node.text(strip=True)
            unit = cell.attributes.get(self.unit_attr) if self.unit_attr else None
            value = f"{raw} {unit}".strip() if unit else str(raw)
        else:
            value = cell.text(separator=" ", strip=True)
        return label, _clean_value(value)


def _clean_label(label: str) -> str:
    """'Z<sub>max</sub>' o 'Data­sheet' -> texto plano comparable."""
    text = re.sub(r"<[^>]+>", "", str(label or ""))
    text = text.translate(_INVISIBLE).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean_value(value: str) -> str:
    text = str(value or "").translate(_INVISIBLE).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text in ("-", "–", "—", "n/a", "N/A") else text
