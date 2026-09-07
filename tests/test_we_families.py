"""Familias del catalogo propio: deteccion e interpretacion de peticiones reales.

Estos tests usan SOLO config/families (sin las familias de ejemplo), que es lo
que se despliega en produccion.
"""

from __future__ import annotations

import pytest

from crossref.extract import build_query, extract_from_text
from crossref.schema import load_registry
from tests.conftest import CATALOG_FAMILIES_DIR


@pytest.fixture(scope="module")
def catalog_registry():
    return load_registry(CATALOG_FAMILIES_DIR)


@pytest.mark.parametrize(
    "texto,familia",
    [
        ("inductancia de potencia 10 uH 3 A DCR 30 mOhm apantallada", "power_inductor"),
        ("power inductor 4.7uH 5A shielded 4x4mm", "power_inductor"),
        ("choque de modo comun 90 ohm a 100 MHz 2 lineas 0805", "common_mode_choke"),
        ("common mode choke 51 ohm 100MHz 4 lines", "common_mode_choke"),
        ("ferrita 600 ohm a 100 MHz 0603 2 A", "ferrite_bead"),
        ("condensador ceramico 100 nF 50 V X7R 0805", "mlcc"),
        ("condensador electrolitico 470 uF 35 V 10x12 mm", "aluminum_capacitor"),
        ("supercondensador 1 F 5,5 V", "supercapacitor"),
        ("tira de pines paso 2,54 mm 20 contactos 2 filas acodado", "pin_header"),
        ("bornero paso 5,08 mm 3 contactos tornillo 16 A 300 V", "terminal_block"),
        ("conector USB-C hembra SMD", "io_connector"),
        ("diodo TVS 5 V 1 linea SOT-23", "esd_tvs"),
        ("varistor 275 V 2500 A 100 J", "varistor"),
        ("LED blanco 1200 mcd 0805", "led"),
        ("cristal de cuarzo 16 MHz 10 ppm 12 pF", "crystal_oscillator"),
        ("antena chip 2400-2500 MHz ganancia 2 dB", "antenna"),
        ("almohadilla termica 3 W/mK 1 mm de espesor", "thermal_interface"),
        ("modulo de alimentacion entrada 6-36 V salida 5 V 1 A", "power_module"),
        ("bobina de carga inalambrica 24 uH Qi 2 A", "wireless_power_coil"),
        ("transformador relacion 1:1 aislamiento 4 kV", "transformer"),
    ],
)
def test_deteccion_de_familia(catalog_registry, texto, familia):
    query = extract_from_text(catalog_registry, texto)
    assert query.family == familia, f"{texto!r} -> {query.family_candidates}"


def test_inductancia_de_potencia(catalog_registry):
    query = extract_from_text(
        catalog_registry, "inductancia de potencia 10 uH 3 A DCR 30 mOhm apantallada"
    )
    assert query.attributes["inductance"].number == pytest.approx(1e-5)
    assert query.attributes["rated_current"].number == pytest.approx(3.0)
    assert query.attributes["dcr"].number == pytest.approx(0.03)
    assert query.attributes["shielding"].text == "apantallado"


def test_ferrita_impedancia_y_frecuencia_de_medida(catalog_registry):
    query = build_query(
        catalog_registry,
        family_id="ferrite_bead",
        fields={"Impedancia": "600 Ohm", "Frecuencia de medida": "100 MHz",
                "Corriente nominal": "2 A", "DCR": "50 mOhm", "Encapsulado": "0603"},
    )
    assert query.attributes["impedance_at_frequency"].number == pytest.approx(600.0)
    assert query.attributes["test_frequency"].number == pytest.approx(1e8)
    assert query.attributes["dcr"].number == pytest.approx(0.05)


def test_mlcc_dielectrico_y_encapsulado(catalog_registry):
    query = extract_from_text(catalog_registry, "condensador ceramico 100 nF 50 V X7R 0805 10%")
    assert query.attributes["capacitance"].number == pytest.approx(1e-7)
    assert query.attributes["dielectric"].text == "x7r"
    assert query.attributes["package"].text == "0805"
    assert query.attributes["tolerance"].number == pytest.approx(10.0)


def test_conector_paso_y_contactos(catalog_registry):
    query = build_query(
        catalog_registry,
        family_id="pin_header",
        fields={"Paso": "2,54 mm", "Numero de contactos": "20", "Filas": "2",
                "Genero": "macho", "Orientacion": "acodado", "Montaje": "THT"},
    )
    assert query.attributes["pitch"].number == pytest.approx(0.00254)
    assert query.attributes["positions"].number == pytest.approx(20)
    assert query.attributes["orientation"].text == "acodado"
    assert query.attributes["mounting"].text == "through hole"


def test_paso_de_conector_no_admite_tolerancia(catalog_registry):
    """2,50 mm y 2,54 mm no son intercambiables aunque se parezcan."""
    from crossref.extract import coerce_value
    from crossref.models import FieldStatus
    from crossref.rules import compare_attribute

    spec = catalog_registry["pin_header"].attributes["pitch"]
    result = compare_attribute(spec, coerce_value(spec, "2,54 mm"), coerce_value(spec, "2,50 mm"))
    assert result.status is FieldStatus.MISMATCH


def test_led_intensidad_luminosa(catalog_registry):
    query = extract_from_text(catalog_registry, "LED blanco 1200 mcd 20 mA 0805")
    assert query.attributes["color"].text == "blanco"
    assert query.attributes["luminous_intensity"].number == pytest.approx(1200.0)
    assert query.attributes["forward_current"].number == pytest.approx(0.02)


def test_interfaz_termica_conductividad(catalog_registry):
    query = extract_from_text(catalog_registry, "almohadilla termica 3 W/mK 1 mm de espesor")
    assert query.attributes["thermal_conductivity"].number == pytest.approx(3.0)
    assert query.attributes["thickness"].number == pytest.approx(0.001)


def test_modulo_de_alimentacion_rango_de_entrada(catalog_registry):
    query = build_query(
        catalog_registry,
        family_id="power_module",
        fields={"Tension de entrada": "6 - 36 V", "Tension de salida": "5 V",
                "Corriente de salida": "1 A", "Encapsulado": "SIP-8"},
    )
    assert query.attributes["input_voltage_range"].interval == (6.0, 36.0)
    assert query.attributes["output_voltage"].number == pytest.approx(5.0)


def test_cristal_tolerancia_en_ppm(catalog_registry):
    query = extract_from_text(catalog_registry, "cristal 16 MHz 10 ppm 12 pF")
    assert query.attributes["frequency"].number == pytest.approx(16e6)
    assert query.attributes["frequency_tolerance"].number == pytest.approx(10 * 1e-4)


def test_todas_las_familias_pueden_confirmar_un_1_a_1(catalog_registry):
    """Una familia sin campos obligatorios nunca podria confirmar una equivalencia."""
    sin_obligatorios = [
        family.id
        for family in catalog_registry.families.values()
        if family.id != "generic" and not family.required_attributes
    ]
    assert not sin_obligatorios


def test_peticion_irreconocible_no_elige_familia_al_azar(catalog_registry):
    query = extract_from_text(catalog_registry, "un cacharro raro de 3 unidades")
    assert query.family == "generic"
    assert any("no se reconoce" in w for w in query.warnings)


# --------------------------------------------------------------------------
# El catalogo publica rangos de serie donde el esquema espera un valor
# --------------------------------------------------------------------------


@pytest.fixture
def series_service(tmp_path):
    """Servicio cargado con el indice de SERIES (rangos), no de referencias."""
    from crossref.ingest import ingest_products
    from crossref.service import CrossRefService
    from crossref.sources.files import FileCatalogSource
    from tests.conftest import ROOT

    service = CrossRefService(CATALOG_FAMILIES_DIR, tmp_path / "series.db")
    source = FileCatalogSource(
        {
            "id": "series",
            "type": "file",
            "path": str(ROOT / "data" / "series_ferritas_pcb.csv"),
            "columns": {"reference": "Referencia", "description": "Descripcion",
                        "category_path": "Categoria"},
            "family_by_category": {"Ferrites for PCB Assembly": "ferrite_bead"},
        }
    )
    ingest_products(service.registry, service.store, source.fetch(), source_id="series")
    return service


def test_un_rango_del_catalogo_se_guarda_como_rango(series_service):
    item = series_service.store.by_reference("WE-CBF")[0]
    valor = item.attributes["impedance_at_frequency"]
    assert valor.kind == "range"
    assert valor.interval == (10.0, 2700.0)
    assert "rango" in valor.note


def test_caer_en_el_rango_de_una_serie_nunca_es_un_1_a_1(series_service):
    """Que el valor pedido este dentro del rango no prueba que exista la pieza."""
    from crossref.models import Verdict

    response = series_service.crossref(
        text="ferrita 600 ohm a 100 MHz 2 A", limit=5
    )
    assert response["results"]
    assert all(r["verdict"] != Verdict.EQUIVALENT.value for r in response["results"])
    mejor = response["results"][0]
    assert any("confirmar la referencia concreta" in r for r in mejor["reasons"])


def test_fuera_del_rango_de_la_serie_se_descarta(series_service):
    response = series_service.crossref(
        text="ferrita 5000 ohm a 100 MHz", limit=5, include_rejected=True
    )
    descartadas = {r["reference"] for r in response["rejected"]}
    assert "WE-CBF" in descartadas  # su rango llega hasta 2700 ohm
    motivos = " ".join(r["reasons"][0] for r in response["rejected"] if r["reasons"])
    assert "fuera del rango" in motivos


def test_la_serie_mas_ajustada_puntua_mas_alto(series_service):
    """Pedir 500 ohm y 8,7 A deberia acercar a WE-SUKW (416-580 ohm, 8,5-9 A)."""
    response = series_service.crossref(text="ferrita 500 ohm a 100 MHz 8,7 A", limit=3)
    assert response["results"][0]["reference"] == "WE-SUKW"


def test_la_categoria_mas_especifica_manda(catalog_registry):
    """'EMC Components' la comparten muchas familias; 'Ferrites for PCB Assembly' no."""
    assert catalog_registry.detect_from_category(
        ["EMC Components", "Ferrites for PCB Assembly"]
    ) == "ferrite_bead"
    assert catalog_registry.detect_from_category(
        ["EMC Components", "Ferrites for Cable Assembly"]
    ) == "cable_ferrite"
    assert catalog_registry.detect_from_category(
        ["EMC Components", "Surge Protection"]
    ) == "varistor"
    assert catalog_registry.detect_from_category(
        ["Passive Components", "Power Magnetics", "Shielded Power Inductors"]
    ) == "power_inductor"


def test_una_ficha_guardada_en_disco_se_puede_inspeccionar(tmp_path, catalog_registry):
    """La opcion B de tools/README.md: ajustar selectores sin salir a la red."""
    from crossref.ingest import resolve_family
    from crossref.sources.web import WebCatalogSource

    ficha = tmp_path / "ficha.html"
    ficha.write_text(
        """<html><body>
        <nav class="breadcrumb"><a>Home</a><a>EMC Components</a><a>Ferrites for PCB Assembly</a></nav>
        <h1 class="product-title">WE-CBF SMT EMI Suppression Ferrite Bead</h1>
        <div class="order-code"><span class="value">742792022</span></div>
        <table class="properties-table">
          <tr><th>Impedance @ 100 MHz</th><td>600 &#937;</td></tr>
          <tr><th>Rated Current IR</th><td>500 mA</td></tr>
          <tr><th>DC Resistance RDC max</th><td>0.35 &#937;</td></tr>
          <tr><th>Size</th><td>0603</td></tr>
        </table></body></html>""",
        encoding="utf-8",
    )
    source = WebCatalogSource(
        {
            "id": "local", "type": "web", "base_url": "https://ejemplo.local",
            "product": {
                "reference": {"selector": "div.order-code span.value"},
                "description": {"selector": "h1.product-title"},
                "category_path": {"selector": "nav.breadcrumb a", "skip": 1},
                "specs": {"table_rows": "table.properties-table tr",
                          "key_selector": "th", "value_selector": "td"},
            },
        }
    )
    html = source.get(f"file://{ficha}")
    product = source.parse_product(html, f"file://{ficha}")
    source.close()

    assert product.reference == "742792022"
    assert resolve_family(catalog_registry, product) == "ferrite_bead"

    from crossref.extract import map_fields

    mapped, unmapped = map_fields(catalog_registry["ferrite_bead"], product.specs)
    assert not unmapped
    assert mapped["impedance_at_frequency"].number == pytest.approx(600.0)
    assert mapped["dcr"].number == pytest.approx(0.35)
    assert mapped["package"].text == "0603"


def test_falta_en_el_catalogo_lo_que_se_pide_impide_confirmar(service):
    """Si la petición pide un dato que la ficha no publica, no hay 1:1 posible.

    Aunque el campo no sea obligatorio para la familia: dar por buena una
    equivalencia sobre un dato que no se conoce sería afirmar lo que no se sabe.
    """
    from crossref.models import Verdict

    response = service.crossref(
        text="atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra",
        fields={"vswr": "1.05"},   # el catálogo de ejemplo publica 1.25
        family="rf_attenuator",
    )
    # 1.05 pedido contra 1.25 publicado incumple: se descarta, no se confirma
    assert all(r["verdict"] != Verdict.EQUIVALENT.value for r in response["results"])

    sin_dato = service.crossref(
        text="atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra",
        fields={"accuracy": "0.1 dB"},
        family="rf_attenuator",
    )
    mejor = sin_dato["results"][0] if sin_dato["results"] else None
    if mejor:
        assert mejor["verdict"] != Verdict.EQUIVALENT.value


# --------------------------------------------------------------------------
# Atributos universales del catálogo
# --------------------------------------------------------------------------


def test_toda_familia_tiene_los_atributos_universales(catalog_registry):
    """Estado, serie, montaje y dimensiones los publica cualquier ficha."""
    universales = {"series", "lifecycle", "mounting", "aec_q", "length", "width",
                   "height_max", "temperature_range", "rohs"}
    for family in catalog_registry.families.values():
        faltan = universales - set(family.attributes)
        assert not faltan, f"{family.id} no tiene {faltan}"


def test_el_atributo_propio_gana_el_alias_compartido(catalog_registry):
    """La columna 'L' es la inductancia en una bobina y la longitud en una resistencia.

    Los universales se añaden al final de cada familia justamente para que un
    atributo propio se quede con el alias cuando lo comparten.
    """
    assert catalog_registry["power_inductor"].attribute_for("L").id == "inductance"
    assert catalog_registry["thick_film_resistor"].attribute_for("L").id == "length"
    assert catalog_registry["thermal_interface"].attribute_for("L").id == "length"


@pytest.mark.parametrize(
    "familia,columna,atributo",
    [
        ("power_inductor", "fres", "srf"),
        ("power_inductor", "IRP,40K", "rated_current"),
        ("power_inductor", "ISAT,30%", "saturation_current"),
        ("power_inductor", "RDC typ.", "dcr"),
        ("power_inductor", "Tol. L", "tolerance"),
        ("power_inductor", "Status", "lifecycle"),
        ("power_inductor", "Mount", "mounting"),
        ("power_inductor", "AEC-Q Product", "aec_q"),
        ("thick_film_resistor", "PRated", "power_rating"),
        ("thick_film_resistor", "Tol. R", "tolerance"),
        ("mlcc", "Ceramic Type", "dielectric"),
        ("mlcc", "VR", "voltage"),
        ("crystal_oscillator", "Cload", "load_capacitance"),
        ("crystal_oscillator", "Tol. f", "frequency_tolerance"),
        ("esd_tvs", "VClamp max.", "clamping_voltage"),
        ("esd_tvs", "IPeak", "peak_pulse_current"),
        ("esd_tvs", "Pins", "lines"),
        ("varistor", "VRMS", "max_ac_voltage"),
        ("common_mode_choke", "VT", "isolation_voltage"),
        ("transformer", "n", "turns_ratio"),
        ("thermal_interface", "κ", "thermal_conductivity"),
        ("ferrite_bead", "Z @ 100 MHz", "impedance_at_frequency"),
        ("ferrite_bead", "R_DC max", "dcr"),
    ],
)
def test_la_notacion_del_catalogo_se_reconoce(catalog_registry, familia, columna, atributo):
    encontrado = catalog_registry[familia].attribute_for(columna)
    assert encontrado is not None, f"'{columna}' sin mapear en {familia}"
    assert encontrado.id == atributo


def test_las_series_de_conexion_tienen_familia(catalog_registry):
    """Cables planos, ZIF/LIF, circulares y terminales de potencia."""
    casos = {
        "WR-FFC Flat Flexible Cable - 0.50 mm": "flat_cable",
        "WR-CAB Ribbon Flat Cable": "flat_cable",
        "WR-FPC Zero Insertion Force Connectors - 0.50mm": "ffc_fpc_connector",
        "WR-FPC Low Insertion Force Connectors": "ffc_fpc_connector",
        "WR-CIRCM12 Cable Assembly": "circular_connector",
        "WP-THRSH REDCUBE THR with external thread": "press_fit_terminal",
        "WR-MM MiniModule": "pin_header",
    }
    for serie, familia in casos.items():
        detectada = catalog_registry.detect(serie, top=1)
        assert detectada and detectada[0][0] == familia, f"{serie} -> {detectada}"
