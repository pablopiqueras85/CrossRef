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

        # Una categoria puede colgar de si misma otras mas concretas
        # ("led/leds" -> "led/leds/color_led" -> ".../chip_led") y las series
        # solo se enlazan en la hoja. Sin bajar por ellas se pierde la rama
        # entera: asi se quedaron fuera los LED de color y los borneros.
        sub = config.get("subcategories") or {}
        self.sub_enabled = bool(sub.get("enabled", True))
        sub_pattern = sub.get("url_pattern")
        self.sub_pattern = re.compile(str(sub_pattern)) if sub_pattern else None
        sub_exclude = sub.get("exclude_pattern")
        self.sub_exclude = re.compile(str(sub_exclude)) if sub_exclude else None
        self.sub_max_depth = int(sub.get("max_depth", 3))
        self.sub_link_selector = str(sub.get("link_selector", self.series_link_selector))

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
        # Hay datos que la tabla de articulos no publica como columna porque
        # los hereda de otra tabla de la misma pagina: el encapsulado vive en
        # la lista de variantes de arriba, emparejado por el mismo id de
        # subcategoria que llevan las filas. Sin esto, un LED 0805 no se puede
        # distinguir de su gemelo en 0603.
        group = table.get("row_group") or {}
        self.group_key_attr = group.get("key_attr")
        self.group_lookup_selector = group.get("lookup_selector")
        self.group_column = _clean_label(group.get("column", "")) or None

        #: de donde sale el numero de articulos que la pagina dice tener, para
        #: poder contrastarlo con las filas que sirve de verdad
        self.total_selector = table.get("total_selector")
        self.total_attr = table.get("total_attr")
        #: (url, declarados, extraidos) de cada pagina de serie recorrida
        self.coverage: list[tuple[str, int, int]] = []

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
        """URLs de las series: las indicadas a mano o las enlazadas en la categoria.

        La rejilla de una categoria mezcla dos cosas: enlaces a series
        (".../WL-SMCW") y enlaces a categorias mas concretas
        (".../led/leds/color_led"). Se recorren tambien las segundas, porque
        hay ramas enteras cuyas series solo se enlazan ahi abajo.
        """
        explicit = category.get("series_urls") or []
        if explicit:
            return [urljoin(self.base_url + "/", str(u)) for u in explicit]

        category_url = category.get("url")
        if not category_url:
            raise SourceError(f"categoria sin 'url' ni 'series_urls': {category}")

        raiz = urljoin(self.base_url + "/", str(category_url))
        pendientes: list[tuple[str, int]] = [(raiz, 0)]
        visitadas: set[str] = set()
        found: list[str] = []

        while pendientes:
            url, depth = pendientes.pop(0)
            if url in visitadas:
                continue
            visitadas.add(url)

            html = self.fetcher.get(url)
            if html is None:
                if url == raiz:
                    raise SourceError(f"no se ha podido descargar la categoria {category_url}")
                continue

            tree = HTMLParser(html)
            for node in tree.css(self.series_link_selector):
                href = urldefrag(node.attributes.get("href", ""))[0]
                if not href or (self.series_exclude and self.series_exclude.search(href)):
                    continue
                if self.series_pattern.search(href):
                    absolute = urljoin(self.base_url + "/", href)
                    if absolute not in found:
                        found.append(absolute)

            if depth < self.sub_max_depth:
                for sub in self._subcategory_urls(tree, raiz):
                    if sub not in visitadas:
                        pendientes.append((sub, depth + 1))

        return found

    def _subcategory_urls(self, tree: HTMLParser, raiz: str) -> list[str]:
        """Enlaces de la pagina que llevan a una categoria por debajo de `raiz`.

        Colgar de la raiz es la condicion importante: evita salirse de la rama
        por el menu de navegacion, que enlaza el catalogo entero.
        """
        if not self.sub_enabled:
            return []
        salida: list[str] = []
        for node in tree.css(self.sub_link_selector):
            href = urldefrag(node.attributes.get("href", ""))[0]
            if not href:
                continue
            if self.sub_pattern and not self.sub_pattern.search(href):
                continue
            if self.sub_exclude and self.sub_exclude.search(href):
                continue
            absolute = urljoin(self.base_url + "/", href)
            if absolute.startswith(raiz.rstrip("/") + "/") and absolute not in salida:
                salida.append(absolute)
        return salida

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
        grupos = self._row_groups(tree)
        derivados = self._derived_specs(category, url, series_name)
        extraidos = 0

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
            extraidos += 1
            if self.only_active and self.status_column:
                status = (specs.get(self.status_column) or "").strip().lower()
                if status and not any(a in status for a in self.active_values):
                    continue
            if grupos and self.group_column:
                etiqueta = grupos.get(row.attributes.get(self.group_key_attr) or "")
                if etiqueta:
                    specs.setdefault(self.group_column, etiqueta)
            if series_name:
                specs.setdefault("Series", series_name)
            # Datos que la categoria da por sabidos y no publica como columna
            # (p. ej. la frecuencia de medida, que va dentro del nombre de la
            # columna "Z @ 100 MHz"). No pisan nunca a una columna real.
            for key, value in (category.get("constant_specs") or {}).items():
                if str(value).strip():
                    specs.setdefault(str(key), str(value))
            # Datos que solo estan en el nombre o la URL de la serie
            # ("WR-TBL Series 2545 - 5.08 mm Horizontal"). Van los ultimos:
            # cualquier columna real de la tabla manda sobre ellos.
            for key, value in derivados.items():
                specs.setdefault(key, value)

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

        # Se compara contra las filas que hay en el marcado, no contra el
        # numero que la pagina dice tener: ese no es fiable. La misma pagina
        # WE-TI_2 declaraba 328 en una descarga y 1448 en la siguiente,
        # sirviendo las mismas 140 filas que WE-TI, que si declara 140. Con
        # aquel numero salian 1.920 "articulos que faltan" inexistentes.
        #
        # Lo que si se puede comprobar, y es lo unico accionable, es si el
        # conector deja filas sin leer de la tabla que tiene delante.
        en_el_marcado = len(
            [row for row in table.css(self.row_selector) if row.css(self.cell_selector)]
        )
        if en_el_marcado:
            self.coverage.append((url, en_el_marcado, extraidos))

    def _derived_specs(
        self, category: dict[str, Any], url: str, series_name: str | None
    ) -> dict[str, str]:
        """Datos que la tabla no publica pero el nombre o la URL de la serie si.

        El paso de un bornero es el ejemplo claro: no hay columna "Pitch", pero
        la serie se llama "WR-TBL Series 2545 - 5.08 mm Horizontal" y su URL es
        TBL_5_08_2545. Sin esto, pedir un bornero de paso 5,08 no confirma
        nada en 2.273 de las 2.297 fichas.
        """
        reglas = category.get("derived_specs") or []
        salida: dict[str, str] = {}
        for regla in reglas:
            columna = str(regla.get("column") or "").strip()
            if not columna or columna in salida:
                continue
            origen = str(regla.get("from", "title")).lower()
            texto = (series_name or "") if origen == "title" else urldefrag(url)[0]
            patron = regla.get("pattern")
            if not (texto and patron):
                continue
            match = re.search(str(patron), texto)
            if match is None:
                continue
            plantilla = str(regla.get("value", "{1}"))
            try:
                valor = plantilla.format("", *match.groups(), **match.groupdict())
            except (IndexError, KeyError) as exc:
                raise SourceError(
                    f"derived_specs de '{columna}': la plantilla {plantilla!r} no "
                    f"encaja con los grupos de {patron!r} ({exc})"
                ) from exc
            if valor.strip():
                salida[columna] = valor.strip()
        return salida

    def _row_groups(self, tree: HTMLParser) -> dict[str, str]:
        """Empareja el id de subcategoria de una fila con su etiqueta.

        La pagina lista arriba las variantes de la serie ("0603", "0805",
        "1206") y cada fila de articulo lleva el id de la suya. Es la unica
        forma de saber el encapsulado cuando no hay columna que lo diga.
        """
        if not (self.group_key_attr and self.group_lookup_selector and self.group_column):
            return {}
        salida: dict[str, str] = {}
        for node in tree.css(self.group_lookup_selector):
            fila = node.parent
            while fila is not None and not fila.attributes.get(self.group_key_attr):
                fila = fila.parent
            if fila is None:
                continue
            clave = fila.attributes.get(self.group_key_attr) or ""
            etiqueta = " ".join(node.text().split())
            if clave and etiqueta and clave not in salida:
                salida[clave] = etiqueta
        return salida

    def _declared_total(self, tree: HTMLParser) -> int | None:
        """Cuantos articulos dice la pagina que tiene, si lo publica.

        Ojo: no es fiable en todas las paginas (ver parse_table). Se conserva
        porque el comando 'probe' lo muestra como dato informativo.
        """
        if not self.total_selector or not self.total_attr:
            return None
        node = tree.css_first(self.total_selector)
        if node is None:
            return None
        raw = node.attributes.get(self.total_attr)
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

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
