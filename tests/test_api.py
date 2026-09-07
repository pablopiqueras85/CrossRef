"""API HTTP: contrato de la respuesta."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from crossref.api import create_app
from crossref.ingest import ingest_products
from tests.conftest import FAMILIES_DIR


@pytest.fixture
def client(tmp_path, sample_source):
    app = create_app(FAMILIES_DIR, tmp_path / "catalog.db")
    service = app.state.service
    ingest_products(service.registry, service.store, sample_source.fetch(), source_id="test_csv")
    return TestClient(app)


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok" and body["items"] == 51


def test_crossref_devuelve_resultado_explicado(client):
    response = client.post(
        "/api/v1/crossref",
        json={"text": "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra"},
    )
    assert response.status_code == 200
    body = response.json()
    mejor = body["results"][0]
    assert mejor["reference"] == "AT-3SM-2W-18"
    assert mejor["verdict"] == "equivalente"
    assert mejor["url"].startswith("https://")
    assert mejor["comparisons"] and mejor["reasons"]
    assert body["family"]["id"] == "rf_attenuator"


def test_crossref_sin_datos_da_422(client):
    assert client.post("/api/v1/crossref", json={}).status_code == 422


def test_parse_muestra_lo_entendido(client):
    body = client.post("/api/v1/parse", json={"text": "carga 50 ohm N hembra DC-4GHz 25W"}).json()
    assert body["family"] == "rf_load"
    etiquetas = {u["attribute"] for u in body["understood"]}
    assert {"impedance", "power", "connector_a", "frequency_range"} <= etiquetas


def test_familias(client):
    body = client.get("/api/v1/families").json()
    assert any(f["id"] == "rf_attenuator" for f in body["families"])
    detalle = client.get("/api/v1/families/rf_attenuator").json()
    assert any(a["id"] == "attenuation" and a["required"] for a in detalle["attributes"])


def test_familia_inexistente_da_404(client):
    assert client.get("/api/v1/families/no_existe").status_code == 404


def test_stats_y_cobertura(client):
    stats = client.get("/api/v1/catalog/stats").json()
    assert stats["items"] == 51
    cobertura = client.get("/api/v1/catalog/coverage/rf_attenuator").json()
    assert cobertura["attenuation"]["coverage"] == 1.0


def test_lote_json(client):
    body = client.post(
        "/api/v1/crossref/batch",
        json={"rows": [{"text": "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra"},
                       {"text": "carga 50 ohm N hembra DC-4GHz 25W"}]},
    ).json()
    assert body["rows"] == 2
    assert body["results"][0]["catalog_reference"] == "AT-3SM-2W-18"


def test_lote_csv(client):
    csv_data = "peticion\natenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra\n"
    response = client.post(
        "/api/v1/crossref/batch/csv?column=peticion",
        files={"file": ("peticiones.csv", io.BytesIO(csv_data.encode()), "text/csv")},
    )
    assert response.status_code == 200
    assert "AT-3SM-2W-18" in response.text


def test_lote_csv_sin_la_columna_da_422(client):
    response = client.post(
        "/api/v1/crossref/batch/csv?column=peticion",
        files={"file": ("x.csv", io.BytesIO(b"otra\nvalor\n"), "text/csv")},
    )
    assert response.status_code == 422


def test_interfaz_web_se_sirve(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
