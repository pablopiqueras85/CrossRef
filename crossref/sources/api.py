"""Conector para catalogos que exponen una API JSON.

Es la fuente preferida cuando existe: mas estable y mas barata que rastrear
la web. Se configura indicando la URL, como paginar y de que campo sale cada
dato (con rutas tipo `data.attributes.sku`).
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

from .base import RawProduct, SourceError

__all__ = ["ApiCatalogSource"]


class ApiCatalogSource:
    """Descarga fichas de una API JSON paginada."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self.id = str(config.get("id", "api"))
        self.config = config
        self.url = str(config.get("url", ""))
        if not self.url:
            raise SourceError("la fuente api necesita 'url'")

        request = config.get("request") or {}
        self.headers = dict(request.get("headers") or {})
        self.timeout = float(request.get("timeout", 30))
        self.rate_limit = float(request.get("rate_limit_per_sec", 5.0))
        self.method = str(request.get("method", "GET")).upper()
        self.params = dict(config.get("params") or {})

        pagination = config.get("pagination") or {}
        self.page_param = pagination.get("page_param")
        self.size_param = pagination.get("size_param")
        self.page_size = int(pagination.get("page_size", 100))
        self.start_page = int(pagination.get("start_page", 1))
        self.max_pages = int(pagination.get("max_pages", 1000))
        self.next_field = pagination.get("next_field")

        self.records_path = config.get("records_path")
        self.fields: dict[str, str] = {k: str(v) for k, v in (config.get("fields") or {}).items()}
        self.specs_path = config.get("specs_path")
        self.specs_key = config.get("specs_key_field", "name")
        self.specs_value = config.get("specs_value_field", "value")

        self._client = client or httpx.Client(headers=self.headers, timeout=self.timeout)
        self._owns_client = client is None
        self._last_request = 0.0

    def fetch(self, limit: int | None = None) -> Iterator[RawProduct]:
        count = 0
        url: str | None = self.url
        page = self.start_page
        pages = 0

        while url and pages < self.max_pages:
            params = dict(self.params)
            if self.page_param:
                params[self.page_param] = page
            if self.size_param:
                params[self.size_param] = self.page_size
            payload = self._request(url, params)
            records = _dig(payload, self.records_path) if self.records_path else payload
            if isinstance(records, dict):
                records = list(records.values())
            if not records:
                return
            for record in records:
                if limit is not None and count >= limit:
                    return
                product = self._to_product(record)
                if product is not None:
                    count += 1
                    yield product
            pages += 1
            page += 1
            url = _dig(payload, self.next_field) if self.next_field else (url if self.page_param else None)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, url: str, params: dict[str, Any]) -> Any:
        wait = (1.0 / self.rate_limit) - (time.monotonic() - self._last_request) if self.rate_limit else 0
        if wait > 0:
            time.sleep(wait)
        try:
            response = self._client.request(self.method, url, params=params)
            self._last_request = time.monotonic()
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"error consultando {url}: {exc}") from exc

    def _to_product(self, record: Any) -> RawProduct | None:
        if not isinstance(record, dict):
            return None
        reference = _dig(record, self.fields.get("reference", "sku"))
        if not reference:
            return None

        specs: dict[str, str] = {}
        raw_specs = _dig(record, self.specs_path) if self.specs_path else None
        if isinstance(raw_specs, dict):
            specs = {str(k): str(v) for k, v in raw_specs.items() if str(v or "").strip()}
        elif isinstance(raw_specs, list):
            for entry in raw_specs:
                if isinstance(entry, dict):
                    key = entry.get(self.specs_key)
                    value = entry.get(self.specs_value)
                    if key and str(value or "").strip():
                        specs[str(key)] = str(value).strip()

        categories = _dig(record, self.fields.get("category_path", ""))
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(">") if c.strip()]
        elif not isinstance(categories, list):
            categories = []

        return RawProduct(
            reference=str(reference).strip(),
            url=_as_str(_dig(record, self.fields.get("url", "url"))),
            manufacturer=_as_str(_dig(record, self.fields.get("manufacturer", "brand"))),
            description=_as_str(_dig(record, self.fields.get("description", "name"))),
            family_hint=_as_str(_dig(record, self.fields.get("family", ""))),
            category_path=[str(c) for c in categories],
            specs=specs,
            datasheet_url=_as_str(_dig(record, self.fields.get("datasheet_url", ""))),
        )


def _dig(data: Any, path: str | None) -> Any:
    """Navega 'data.attributes.sku' sobre diccionarios y listas."""
    if not path:
        return None
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
