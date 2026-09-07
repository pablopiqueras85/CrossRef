"""Catalogo: ingesta, indice y conectores."""

from __future__ import annotations

import json

import pytest

from crossref.ingest import ingest_products, resolve_family
from crossref.models import CatalogItem
from crossref.sources.base import RawProduct, SourceError, load_source
from crossref.sources.web import WebCatalogSource

FICHA_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","sku":"AT-3SM-2W-18",
 "name":"Atenuador coaxial 3 dB","brand":{"@type":"Brand","name":"RFComp"},
 "category":"Componentes RF > Atenuadores",
 "additionalProperty":[{"@type":"PropertyValue","name":"RoHS","value":"Sí"}]}
</script></head>
<body>
  <nav class="breadcrumb"><a>Inicio</a><a>Componentes RF</a><a>Atenuadores</a></nav>
  <h1 class="title">Atenuador coaxial fijo 3 dB SMA</h1>
  <span class="sku">Ref. AT-3SM-2W-18</span>
  <span class="brand">RFComp</span>
  <table class="specs">
    <tr><th>Impedancia</th><td>50 Ohm</td></tr>
    <tr><th>Atenuación</th><td>3 dB</td></tr>
    <tr><th>Rango de frecuencia</th><td>DC - 18 GHz</td></tr>
    <tr><th>Potencia</th><td>2 W</td></tr>
    <tr><th>Conector 1</th><td>SMA macho</td></tr>
    <tr><th>Conector 2</th><td>SMA hembra</td></tr>
  </table>
  <a class="datasheet" href="/pdf/at-3sm.pdf">Hoja de datos</a>
</body></html>
"""

CONFIG_WEB = {
    "id": "web_test",
    "type": "web",
    "base_url": "https://catalogo.example",
    "product": {
        "match_url": "/producto/",
        "reference": {"selector": "span.sku", "regex": r"Ref\.\s*(.+)"},
        "manufacturer": "span.brand",
        "description": "h1.title",
        "category_path": {"selector": "nav.breadcrumb a", "skip": 1},
        "datasheet": {"selector": "a.datasheet", "attr": "href"},
        "specs": {"table_rows": "table.specs tr", "key_selector": "th", "value_selector": "td"},
    },
}


def test_web_source_extrae_la_ficha():
    source = WebCatalogSource(CONFIG_WEB)
    product = source.parse_product(FICHA_HTML, "https://catalogo.example/producto/at-3sm-2w-18")
    assert product.reference == "AT-3SM-2W-18"
    assert product.manufacturer == "RFComp"
    assert product.category_path == ["Componentes RF", "Atenuadores"]
    assert product.specs["Impedancia"] == "50 Ohm"
    assert product.specs["Atenuación"] == "3 dB"
    assert product.specs["RoHS"] == "Sí"          # viene del JSON-LD
    assert product.datasheet_url.endswith("/pdf/at-3sm.pdf")
    source.close()


def test_web_source_sin_datos_estructurados_ni_selectores_no_inventa():
    source = WebCatalogSource({**CONFIG_WEB, "product": {"match_url": "/producto/"}})
    assert source.parse_product("<html><body>nada</body></html>", "https://x/producto/1") is None
    source.close()


def test_ingesta_normaliza_y_clasifica(registry, store, sample_source):
    report = ingest_products(registry, store, sample_source.fetch(), source_id="test_csv")
    assert report.items == 51
    assert report.by_family["rf_attenuator"] == 18
    assert not report.unclassified

    item = store.by_reference("AT-3SM-2W-18")[0]
    assert item.family == "rf_attenuator"
    assert item.attributes["attenuation"].number == pytest.approx(3.0)
    assert item.attributes["frequency_range"].interval == (0.0, 18e9)
    assert item.specs["Impedancia"] == "50 Ohm"      # se conserva el original
    assert item.source == "test_csv"


def test_la_ficha_conserva_procedencia_y_fecha(registry, store, sample_source):
    ingest_products(registry, store, sample_source.fetch(), source_id="test_csv")
    item = store.by_reference("LD-N-25W-4")[0]
    assert item.url and item.fetched_at


def test_informe_avisa_de_campos_sin_mapear(registry, store):
    productos = [
        RawProduct(reference="X-1", description="Atenuador 3 dB",
                   category_path=["Atenuadores"],
                   specs={"Impedancia": "50 Ohm", "Color de la carcasa": "azul"})
    ]
    report = ingest_products(registry, store, productos, source_id="s")
    assert "Color de la carcasa" in report.unmapped_fields
    assert report.unmapped_fields["Color de la carcasa"][0] == 1


def test_informe_avisa_de_fichas_incompletas(registry, store):
    productos = [RawProduct(reference="X-2", description="Atenuador",
                            category_path=["Atenuadores"], specs={"Impedancia": "50 Ohm"})]
    report = ingest_products(registry, store, productos, source_id="s")
    assert report.incomplete and "Atenuacion" in report.incomplete[0][1]


def test_resolve_family_por_categoria(registry):
    product = RawProduct(reference="X", category_path=["Componentes RF", "Cargas"])
    assert resolve_family(registry, product) == "rf_load"


def test_store_reindexa_sin_duplicar(registry, store, sample_source):
    ingest_products(registry, store, sample_source.fetch(), source_id="test_csv")
    ingest_products(registry, store, sample_source.fetch(), source_id="test_csv")
    assert store.stats()["items"] == 51


def test_store_da_de_baja_lo_que_desaparece(registry, store, sample_source):
    ingest_products(registry, store, sample_source.fetch(), source_id="test_csv")
    superviviente = store.by_reference("AT-3SM-2W-18")[0]
    store.deactivate_missing("test_csv", [superviviente.id])
    assert store.stats()["items"] == 1


def test_busqueda_por_texto(registry, store, sample_source):
    ingest_products(registry, store, sample_source.fetch(), source_id="test_csv")
    encontrados = [i.reference for i in store.search_text("divisor 4 vias")]
    assert any(r.startswith("PD-4W") for r in encontrados)


def test_atributos_sobreviven_al_viaje_por_sqlite(store):
    from crossref.models import AttributeValue

    item = CatalogItem(
        id="x", reference="R-1",
        attributes={"frequency_range": AttributeValue("frequency_range", "DC-18GHz",
                                                      kind="range", interval=(0.0, 18e9),
                                                      dimension="frequency")},
    )
    store.upsert([item])
    recuperado = store.get("x")
    assert recuperado.attributes["frequency_range"].interval == (0.0, 18e9)
    assert recuperado.attributes["frequency_range"].display() == "0 Hz - 18 GHz"


def test_tipo_de_fuente_desconocido_falla_claro(tmp_path):
    path = tmp_path / "mala.yaml"
    path.write_text("type: paloma_mensajera\n", encoding="utf-8")
    with pytest.raises(SourceError, match="no soportado"):
        load_source(path)


def test_fuente_csv_desde_yaml(tmp_path):
    csv_path = tmp_path / "cat.csv"
    csv_path.write_text("Referencia,Impedancia\nR-1,50 Ohm\n", encoding="utf-8")
    yaml_path = tmp_path / "fuente.yaml"
    yaml_path.write_text(
        json.dumps({"type": "file", "path": str(csv_path),
                    "columns": {"reference": "Referencia"}}),
        encoding="utf-8",
    )
    source = load_source(yaml_path)
    productos = list(source.fetch())
    assert productos[0].reference == "R-1"
    assert productos[0].specs == {"Impedancia": "50 Ohm"}
