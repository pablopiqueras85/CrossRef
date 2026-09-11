"""Contrato comun de los conectores de catalogo.

Un conector solo sabe traer fichas en bruto. La normalizacion y el mapeo al
esquema de familias ocurren despues, en `crossref.ingest`, de modo que la
fuente sea una dependencia intercambiable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

import yaml

__all__ = ["RawProduct", "CatalogSource", "SourceError", "load_source", "load_source_config"]


class SourceError(RuntimeError):
    """Fallo al obtener datos de la fuente."""


@dataclass
class RawProduct:
    """Ficha tal y como viene de la fuente, sin interpretar."""

    reference: str
    url: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    family_hint: str | None = None
    category_path: list[str] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)
    datasheet_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def stable_id(self, source_id: str) -> str:
        """Id estable: fuente + referencia normalizada (o URL si no hay referencia)."""
        from ..normalize import normalize_pn

        key = normalize_pn(self.reference) or re.sub(r"[^A-Za-z0-9]+", "", self.url or "")
        return f"{source_id}:{key}"


class CatalogSource(Protocol):
    """Lo unico que el sistema espera de una fuente de catalogo."""

    id: str

    def fetch(self, limit: int | None = None) -> Iterator[RawProduct]:
        """Devuelve las fichas disponibles."""
        ...


def load_source_config(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SourceError(f"configuracion de fuente invalida: {path}")
    data.setdefault("id", Path(path).stem)
    return data


def load_source(path: str | Path) -> CatalogSource:
    """Instancia el conector que indique el campo `type` del YAML."""
    config = load_source_config(path)
    kind = str(config.get("type", "")).lower()
    if kind == "web":
        from .web import WebCatalogSource

        return WebCatalogSource(config)
    if kind in ("web_table", "table"):
        from .web_table import WebTableCatalogSource

        return WebTableCatalogSource(config)
    if kind in ("file", "csv", "json", "xlsx"):
        from .files import FileCatalogSource

        return FileCatalogSource(config)
    if kind == "api":
        from .api import ApiCatalogSource

        return ApiCatalogSource(config)
    raise SourceError(
        f"tipo de fuente no soportado: {kind!r} (usa web, web_table, file o api)"
    )
