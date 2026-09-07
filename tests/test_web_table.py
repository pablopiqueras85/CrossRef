"""Conector de tablas de artículos: una fila del catálogo = una referencia.

El fixture reproduce el marcado real del catálogo, incluidas las trampas que
aparecieron al conectarlo: dos columnas distintas con la misma etiqueta oculta,
el estado con el texto del tooltip pegado, y enlaces de las migas de pan que
parecen series pero no lo son.
"""

from __future__ import annotations

import pytest

from crossref.sources.base import SourceError, load_source
from crossref.sources.web_table import WebTableCatalogSource

CATEGORIA_HTML = """
<html><body>
  <div class="weBreadcrumbs"><a href="/en/components/products/pbs">Passive Components</a></div>
  <div class="wec-grid">
    <div class="wec-grid__item"><a href="/en/components/products/WE-CBF">WE-CBF</a></div>
    <div class="wec-grid__item"><a href="/en/components/products/WE-RFI_FERRITE_BEAD">WE-RFI</a></div>
  </div>
</body></html>
"""

SERIE_HTML = """
<html><body>
  <h1>WE-CBF SMT EMI Suppression Ferrite Bead</h1>
  <div class="parametricSearch" data-total-article-count="2"></div>
  <table class="wecProductTable">
    <tr>
      <th data-column="Order Code">Order Code</th>
      <th data-column="Status">Status</th>
      <th data-column="Z @ 100 MHz">Z @ 100 MHz</th>
      <th data-column="Z<sub>max</sub>">Zmax</th>
      <th data-column="Test Condition Z<sub>max</sub>">Test Condition</th>
      <th data-column="I<sub>R</sub> 2">IR 2</th>
      <th data-column="Data&shy;sheet">Datasheet</th>
    </tr>
    <tr>
      <td class="ordercode" data-column="Order Code">
        <a class="orderCode" href="/en/components/products/WE-CBF#74279204">74279204</a></td>
      <td data-column="Status">
        <span class="wecProductTableBody__data--mobile">Status</span>
        <div class="wecLifecycle__status-wrapper"><span>Active</span>
          <span class="wecLifecycle__status-info">Production is active. &gt;10 years.</span></div></td>
      <td data-unit="&#937;" data-column="Z @ 100 MHz">
        <span class="wecProductTableBody__data--mobile">Impedance @ 100 MHz</span>
        <span data-sort-value="600">600&nbsp;&#937;</span></td>
      <td data-unit="&#937;" data-column="Z<sub>max</sub>">
        <span class="wecProductTableBody__data--mobile">Maximum Impedance</span>
        <span data-sort-value="700">700&nbsp;&#937;</span></td>
      <td data-unit="MHz" data-column="Test Condition Z<sub>max</sub>">
        <span class="wecProductTableBody__data--mobile">Maximum Impedance</span>
        <span data-sort-value="150">150&nbsp;MHz</span></td>
      <td data-unit="mA" data-column="I<sub>R</sub> 2">
        <span class="wecProductTableBody__data--mobile">Rated Current</span>
        <span data-sort-value="1500">1500&nbsp;mA</span></td>
      <td data-column="Data&shy;sheet">
        <a href="/components/products/datasheet/74279204.pdf">SPEC 600 &#937;</a></td>
    </tr>
    <tr>
      <td class="ordercode" data-column="Order Code">
        <a class="orderCode" href="/en/components/products/WE-CBF#74279205">74279205</a></td>
      <td data-column="Status">
        <span class="wecProductTableBody__data--mobile">Status</span>
        <div class="wecLifecycle__status-wrapper"><span>Obsolete</span></div></td>
      <td data-unit="&#937;" data-column="Z @ 100 MHz">
        <span class="wecProductTableBody__data--mobile">Impedance @ 100 MHz</span>
        <span data-sort-value="1000">1000&nbsp;&#937;</span></td>
      <td data-unit="&#937;" data-column="Z<sub>max</sub>">–</td>
      <td data-unit="MHz" data-column="Test Condition Z<sub>max</sub>">–</td>
      <td data-unit="mA" data-column="I<sub>R</sub> 2">
        <span data-sort-value="900">900&nbsp;mA</span></td>
      <td data-column="Data&shy;sheet">–</td>
    </tr>
  </table>
</body></html>
"""


def config(**extra):
    base = {
        "id": "prueba",
        "type": "web_table",
        "base_url": "https://catalogo.example",
        "manufacturer": "Fabricante",
        "series": {
            "link_selector": ".wec-grid__item a[href]",
            "url_pattern": r"^/en/components/products/[A-Za-z0-9][A-Za-z0-9_\-]*$",
            "title_selector": "h1",
        },
        "table": {
            "selector": "table.wecProductTable",
            "row_selector": "tr",
            "cell_selector": "td[data-column]",
            "label_attr": "data-column",
            "label_selector": "span.wecProductTableBody__data--mobile",
            "unit_attr": "data-unit",
            "value_attr": "data-sort-value",
            "reference_columns": ["Order Code"],
            "datasheet_selector": 'a[href$=".pdf"]',
            "status_column": "Status",
            "value_selectors": {"Status": ".wecLifecycle__status-wrapper > span"},
            "ignore_columns": ["Datasheet"],
        },
        "categories": [{"url": "/cat", "family": "ferrite_bead",
                        "category_path": ["EMC Components", "Ferrites for PCB Assembly"]}],
    }
    for key, value in extra.items():
        base[key] = value
    return base


@pytest.fixture
def source():
    src = WebTableCatalogSource(config())
    yield src
    src.close()


def productos(source, **kw):
    return list(source.parse_table(SERIE_HTML, "https://catalogo.example/en/components/products/WE-CBF",
                                   {**config()["categories"][0], **kw}))


def test_una_fila_es_una_referencia(source):
    items = productos(source)
    assert [p.reference for p in items] == ["74279204", "74279205"]


def test_el_valor_sale_limpio_del_atributo_y_la_unidad(source):
    specs = productos(source)[0].specs
    assert specs["Z @ 100 MHz"] == "600 Ω"
    assert specs["IR 2"] == "1500 mA"


def test_dos_columnas_con_la_misma_etiqueta_oculta_no_se_pisan(source):
    """'Zmax' y 'Test Condition Zmax' se anuncian las dos como 'Maximum Impedance'."""
    specs = productos(source)[0].specs
    assert specs["Zmax"] == "700 Ω"
    assert specs["Test Condition Zmax"] == "150 MHz"


def test_el_estado_no_arrastra_el_tooltip(source):
    assert productos(source)[0].specs["Status"] == "Active"


def test_las_celdas_vacias_no_generan_specs(source):
    assert "Zmax" not in productos(source)[1].specs


def test_columnas_ignoradas_y_datasheet(source):
    item = productos(source)[0]
    assert "Datasheet" not in item.specs
    assert item.datasheet_url.endswith("/74279204.pdf")


def test_serie_categoria_y_enlace(source):
    item = productos(source)[0]
    assert item.specs["Series"].startswith("WE-CBF")
    assert item.category_path == ["EMC Components", "Ferrites for PCB Assembly"]
    assert item.family_hint == "ferrite_bead"
    assert item.url.endswith("#74279204")
    assert item.manufacturer == "Fabricante"


def test_constantes_de_categoria_no_pisan_una_columna_real(source):
    items = productos(source, constant_specs={"Test frequency": "100 MHz",
                                              "Z @ 100 MHz": "1 Ω"})
    assert items[0].specs["Test frequency"] == "100 MHz"
    assert items[0].specs["Z @ 100 MHz"] == "600 Ω"


def test_solo_activos(source):
    activo = WebTableCatalogSource({**config(), "table": {**config()["table"], "only_active": True}})
    items = list(activo.parse_table(SERIE_HTML, "https://catalogo.example/x", config()["categories"][0]))
    activo.close()
    assert [p.reference for p in items] == ["74279204"]


def test_los_enlaces_de_serie_se_buscan_solo_en_la_rejilla():
    """Las migas de pan enlazan la categoría padre: no es una serie."""
    import httpx

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cat":
            return httpx.Response(200, text=CATEGORIA_HTML)
        return httpx.Response(200, text=SERIE_HTML)

    client = httpx.Client(transport=httpx.MockTransport(responder))
    src = WebTableCatalogSource({**config(), "request": {"respect_robots": False, "rate_limit_per_sec": 0}}, client)
    urls = src._series_urls(config()["categories"][0])  # noqa: SLF001
    src.close()
    assert [u.rsplit("/", 1)[-1] for u in urls] == ["WE-CBF", "WE-RFI_FERRITE_BEAD"]
    assert not any(u.endswith("/pbs") for u in urls)


def test_recorrido_completo_categoria_series_tabla():
    import httpx

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CATEGORIA_HTML if request.url.path == "/cat" else SERIE_HTML)

    client = httpx.Client(transport=httpx.MockTransport(responder))
    src = WebTableCatalogSource({**config(), "request": {"respect_robots": False, "rate_limit_per_sec": 0}}, client)
    items = list(src.fetch())
    src.close()
    assert len(items) == 4  # 2 series x 2 filas


def test_una_cabecera_no_ascii_falla_con_un_mensaje_util():
    with pytest.raises(SourceError, match="ASCII"):
        WebTableCatalogSource({**config(), "request": {"user_agent": "Bot/1.0 (catálogo)"}})


def test_el_tipo_de_fuente_esta_registrado(tmp_path):
    import json

    path = tmp_path / "fuente.yaml"
    path.write_text(json.dumps(config()), encoding="utf-8")
    assert isinstance(load_source(path), WebTableCatalogSource)
