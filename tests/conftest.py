"""Fixtures compartidas: registro de familias y catalogo en memoria."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crossref.ingest import ingest_products  # noqa: E402
from crossref.schema import load_registry  # noqa: E402
from crossref.service import CrossRefService  # noqa: E402
from crossref.sources.files import FileCatalogSource  # noqa: E402
from crossref.store import CatalogStore  # noqa: E402

FAMILIES_DIR = ROOT / "config" / "families"
SAMPLE_CSV = ROOT / "data" / "catalogo_ejemplo.csv"


@pytest.fixture(scope="session")
def registry():
    return load_registry(FAMILIES_DIR)


@pytest.fixture
def store(tmp_path):
    return CatalogStore(tmp_path / "catalog.db")


@pytest.fixture
def sample_source():
    return FileCatalogSource(
        {
            "id": "test_csv",
            "type": "file",
            "path": str(SAMPLE_CSV),
            "columns": {
                "reference": "Referencia",
                "manufacturer": "Fabricante",
                "description": "Descripcion",
                "url": "URL",
                "category_path": "Categoria",
            },
        }
    )


@pytest.fixture
def service(tmp_path, sample_source, registry):
    svc = CrossRefService(FAMILIES_DIR, tmp_path / "catalog.db")
    ingest_products(svc.registry, svc.store, sample_source.fetch(), source_id="test_csv")
    return svc
