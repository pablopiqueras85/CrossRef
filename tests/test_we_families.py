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
