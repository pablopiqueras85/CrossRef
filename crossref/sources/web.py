"""Conector para catalogos que solo existen como web.

Se configura en YAML, sin escribir codigo por cada catalogo: se indican las
paginas donde estan los productos y los selectores CSS de cada dato. Si la
ficha publica datos estructurados (JSON-LD `Product`), se usan ademas como
respaldo, que es lo mas estable.

Buenas practicas incorporadas: se respeta robots.txt, se limita el ritmo de
peticiones y se cachea el HTML para no repetir descargas.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.robotparser
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree

import httpx
from selectolax.parser import HTMLParser

from .base import RawProduct, SourceError

__all__ = ["WebCatalogSource"]

DEFAULT_USER_AGENT = "CrossRefBot/0.1 (catalogo interno; contacto: it@empresa.local)"


class WebCatalogSource:
    """Recorre un catalogo web y extrae las fichas segun la configuracion."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self.id = str(config.get("id", "web"))
        self.config = config
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        if not self.base_url:
            raise SourceError("la fuente web necesita 'base_url'")

        request = config.get("request") or {}
        self.user_agent = str(request.get("user_agent", DEFAULT_USER_AGENT))
        self.timeout = float(request.get("timeout", 20))
        self.rate_limit = float(request.get("rate_limit_per_sec", 1.0))
        self.max_pages = int(request.get("max_pages", 5000))
        self.respect_robots = bool(request.get("respect_robots", True))
        self.headers = {"User-Agent": self.user_agent, **(request.get("headers") or {})}
        self.cache_dir = Path(request["cache_dir"]) if request.get("cache_dir") else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client = client or httpx.Client(
            headers=self.headers, timeout=self.timeout, follow_redirects=True
        )
        self._owns_client = client is None
        self._last_request = 0.0
        self._robots: urllib.robotparser.RobotFileParser | None = None
        self._seen: set[str] = set()

    # ------------------------------------------------------------------ publico

    def fetch(self, limit: int | None = None) -> Iterator[RawProduct]:
        count = 0
        for url in self._discover_product_urls():
            if limit is not None and count >= limit:
                return
            html = self._get(url)
            if html is None:
                continue
            product = self.parse_product(html, url)
            if product is None or not product.reference:
                continue
            count += 1
            yield product

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "WebCatalogSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --------------------------------------------------------------- descubrir

    def _discover_product_urls(self) -> Iterator[str]:
        """URLs de ficha: por sitemap, recorriendo listados o las indicadas a mano."""
        emitted = 0
        for url in self._candidate_urls():
            url, _ = urldefrag(url)
            if url in self._seen or not self._is_product_url(url):
                continue
            self._seen.add(url)
            emitted += 1
            if emitted > self.max_pages:
                return
            yield url

    def _candidate_urls(self) -> Iterator[str]:
        if self.config.get("sitemap"):
            yield from self._sitemap_urls(str(self.config["sitemap"]))
        listing = self.config.get("listing") or {}
        for start_url in self.config.get("start_urls", []):
            if listing:
                yield from self._crawl_listing(str(start_url), listing)
            else:
                yield str(start_url)

    def _sitemap_urls(self, sitemap_url: str, depth: int = 0) -> Iterator[str]:
        if depth > 3:
            return
        body = self._get(sitemap_url)
        if not body:
            return
        try:
            tree = ElementTree.fromstring(body.encode("utf-8", "ignore"))
        except ElementTree.ParseError as exc:  # pragma: no cover - sitemap roto
            raise SourceError(f"sitemap ilegible ({sitemap_url}): {exc}") from exc
        tag = lambda node: node.tag.split("}")[-1]  # noqa: E731 - lambda local corta
        for node in tree.iter():
            if tag(node) != "loc" or not (node.text or "").strip():
                continue
            location = node.text.strip()
            parent_is_index = tag(tree) == "sitemapindex"
            if parent_is_index or location.endswith((".xml", ".xml.gz")):
                yield from self._sitemap_urls(location, depth + 1)
            else:
                yield location

    def _crawl_listing(self, url: str, listing: dict[str, Any]) -> Iterator[str]:
        item_selector = listing.get("item_link_selector")
        next_selector = listing.get("next_page_selector")
        page_param = listing.get("page_param")
        max_listing_pages = int(listing.get("max_pages", 200))
        visited: set[str] = set()
        page = 1
        current = url

        while current and current not in visited and page <= max_listing_pages:
            visited.add(current)
            html = self._get(current)
            if html is None:
                return
            tree = HTMLParser(html)
            found = 0
            if item_selector:
                for node in tree.css(item_selector):
                    href = node.attributes.get("href")
                    if href:
                        found += 1
                        yield urljoin(current, href)
            if found == 0 and page > 1:
                return  # pagina vacia: se ha llegado al final del listado
            nxt = None
            if next_selector:
                node = tree.css_first(next_selector)
                if node is not None and node.attributes.get("href"):
                    nxt = urljoin(current, node.attributes["href"])
            elif page_param:
                separator = "&" if "?" in url else "?"
                nxt = f"{url}{separator}{page_param}={page + 1}"
            current = nxt
            page += 1

    def _is_product_url(self, url: str) -> bool:
        product = self.config.get("product") or {}
        pattern = product.get("match_url")
        if pattern and not re.search(str(pattern), url):
            return False
        exclude = product.get("exclude_url")
        if exclude and re.search(str(exclude), url):
            return False
        if urlparse(url).netloc and urlparse(self.base_url).netloc:
            return urlparse(url).netloc == urlparse(self.base_url).netloc
        return True

    # ------------------------------------------------------------------ parseo

    def parse_product(self, html: str, url: str) -> RawProduct | None:
        """Extrae una ficha del HTML. Publico para poder probarlo sin red."""
        product = self.config.get("product") or {}
        tree = HTMLParser(html)
        structured = _json_ld_product(tree)

        reference = (
            _field(tree, product.get("reference"), url)
            or structured.get("sku")
            or structured.get("mpn")
            or structured.get("productID")
        )
        if not reference:
            return None

        specs = self._extract_specs(tree, product.get("specs") or {})
        for key, value in (structured.get("_specs") or {}).items():
            specs.setdefault(key, value)

        categories = _field_list(tree, product.get("category_path"), url)
        if not categories and structured.get("category"):
            categories = [c.strip() for c in str(structured["category"]).split(">") if c.strip()]

        return RawProduct(
            reference=str(reference).strip(),
            url=url,
            manufacturer=_field(tree, product.get("manufacturer"), url) or structured.get("brand"),
            description=_field(tree, product.get("description"), url) or structured.get("name"),
            family_hint=_field(tree, product.get("family"), url),
            category_path=categories,
            specs=specs,
            datasheet_url=_absolute(url, _field(tree, product.get("datasheet"), url)),
            extra={
                k: _field(tree, v, url)
                for k, v in (product.get("extra") or {}).items()
                if _field(tree, v, url)
            },
        )

    def _extract_specs(self, tree: HTMLParser, config: dict[str, Any]) -> dict[str, str]:
        specs: dict[str, str] = {}

        rows_selector = config.get("table_rows")
        if rows_selector:
            key_selector = config.get("key_selector", "th")
            value_selector = config.get("value_selector", "td")
            for row in tree.css(rows_selector):
                key_node = row.css_first(key_selector)
                value_nodes = row.css(value_selector)
                if key_node is None or not value_nodes:
                    continue
                # En tablas sin <th>, la primera celda es la clave.
                if key_selector == value_selector and len(value_nodes) >= 2:
                    key, value = value_nodes[0].text(strip=True), value_nodes[1].text(strip=True)
                else:
                    key, value = key_node.text(strip=True), value_nodes[-1].text(strip=True)
                if key and value:
                    specs[_clean_key(key)] = value

        dl_selector = config.get("definition_list")
        if dl_selector:
            for definition in tree.css(dl_selector):
                terms = definition.css("dt")
                values = definition.css("dd")
                for term, value in zip(terms, values):
                    key, text = term.text(strip=True), value.text(strip=True)
                    if key and text:
                        specs[_clean_key(key)] = text

        pair_selector = config.get("pair_selector")
        if pair_selector:
            key_selector = config.get("pair_key_selector")
            value_selector = config.get("pair_value_selector")
            for node in tree.css(pair_selector):
                key_node = node.css_first(key_selector) if key_selector else None
                value_node = node.css_first(value_selector) if value_selector else None
                if key_node is not None and value_node is not None:
                    key, text = key_node.text(strip=True), value_node.text(strip=True)
                    if key and text:
                        specs[_clean_key(key)] = text
                    continue
                text = node.text(strip=True)
                if ":" in text:
                    key, _, value = text.partition(":")
                    if key.strip() and value.strip():
                        specs[_clean_key(key)] = value.strip()
        return specs

    # ------------------------------------------------------------------- red

    def _get(self, url: str) -> str | None:
        if self.respect_robots and not self._robots_allows(url):
            raise SourceError(
                f"robots.txt no permite descargar {url}. Pide una API o una exportacion "
                "del catalogo, o autorizacion expresa para rastrearlo."
            )
        cached = self._read_cache(url)
        if cached is not None:
            return cached

        wait = (1.0 / self.rate_limit) - (time.monotonic() - self._last_request) if self.rate_limit else 0
        if wait > 0:
            time.sleep(wait)
        try:
            response = self._client.get(url)
            self._last_request = time.monotonic()
            if response.status_code >= 400:
                return None
            text = response.text
        except httpx.HTTPError as exc:
            raise SourceError(f"error descargando {url}: {exc}") from exc
        self._write_cache(url, text)
        return text

    def _robots_allows(self, url: str) -> bool:
        if self._robots is None:
            parser = urllib.robotparser.RobotFileParser()
            robots_url = urljoin(self.base_url + "/", "/robots.txt")
            try:
                response = self._client.get(robots_url)
                parser.parse(response.text.splitlines() if response.status_code < 400 else [])
            except httpx.HTTPError:
                parser.parse([])
            self._robots = parser
        return self._robots.can_fetch(self.user_agent, url)

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{digest}.html"

    def _read_cache(self, url: str) -> str | None:
        path = self._cache_path(url)
        if path and path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
        return None

    def _write_cache(self, url: str, text: str) -> None:
        path = self._cache_path(url)
        if path:
            path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# Utilidades de extraccion
# --------------------------------------------------------------------------


def _clean_key(key: str) -> str:
    return re.sub(r"\s*[:：]\s*$", "", key.strip())


def _field(tree: HTMLParser, spec: Any, base_url: str) -> str | None:
    """Extrae un campo segun {selector, attr, regex, default}."""
    if spec is None:
        return None
    if isinstance(spec, str):
        spec = {"selector": spec}
    selector = spec.get("selector")
    if not selector:
        return spec.get("default")
    node = tree.css_first(selector)
    if node is None:
        return spec.get("default")
    attr = spec.get("attr", "text")
    value = node.text(strip=True) if attr == "text" else (node.attributes.get(attr) or "")
    if spec.get("regex"):
        match = re.search(str(spec["regex"]), value)
        value = (match.group(1) if match and match.groups() else match.group(0)) if match else ""
    value = value.strip()
    return value or spec.get("default")


def _field_list(tree: HTMLParser, spec: Any, base_url: str) -> list[str]:
    if spec is None:
        return []
    if isinstance(spec, str):
        spec = {"selector": spec}
    selector = spec.get("selector")
    if not selector:
        return []
    attr = spec.get("attr", "text")
    skip = int(spec.get("skip", 0))
    values = []
    for node in tree.css(selector):
        text = node.text(strip=True) if attr == "text" else (node.attributes.get(attr) or "")
        if text.strip():
            values.append(text.strip())
    return values[skip:]


def _absolute(base_url: str, value: str | None) -> str | None:
    return urljoin(base_url, value) if value else None


def _json_ld_product(tree: HTMLParser) -> dict[str, Any]:
    """Lee el bloque JSON-LD `Product` si la ficha lo publica."""
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text()
        if not raw or "Product" not in raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for candidate in _iter_json_objects(data):
            types = candidate.get("@type")
            types = [types] if isinstance(types, str) else (types or [])
            if "Product" not in types:
                continue
            brand = candidate.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            specs = {}
            for prop in candidate.get("additionalProperty", []) or []:
                if isinstance(prop, dict) and prop.get("name"):
                    specs[_clean_key(str(prop["name"]))] = str(prop.get("value", "")).strip()
            return {
                "sku": candidate.get("sku"),
                "mpn": candidate.get("mpn"),
                "productID": candidate.get("productID"),
                "name": candidate.get("name"),
                "brand": brand,
                "category": candidate.get("category"),
                "_specs": {k: v for k, v in specs.items() if v},
            }
    return {}


def _iter_json_objects(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _iter_json_objects(value)
    elif isinstance(data, list):
        for value in data:
            yield from _iter_json_objects(value)
