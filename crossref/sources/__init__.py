"""Conectores de catalogo: de donde salen las fichas de producto."""

from .base import CatalogSource, RawProduct, SourceError, load_source
from .files import FileCatalogSource
from .web import WebCatalogSource
from .web_table import WebTableCatalogSource
from .api import ApiCatalogSource

__all__ = [
    "CatalogSource",
    "RawProduct",
    "SourceError",
    "load_source",
    "FileCatalogSource",
    "WebCatalogSource",
    "WebTableCatalogSource",
    "ApiCatalogSource",
]
