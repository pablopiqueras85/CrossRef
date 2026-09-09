"""Interpretacion de peticiones escritas por personas."""

from __future__ import annotations

import pytest

from crossref.extract import build_query, coerce_value, extract_from_text, map_fields


def test_detecta_familia_y_valores_de_texto_libre(registry):
    query = extract_from_text(
        registry,
        "Necesito un atenuador coaxial de 3 dB, 50 ohm, DC-18 GHz, 2 W, SMA macho / SMA hembra",
    )
    assert query.family == "rf_attenuator"
    assert query.attributes["attenuation"].number == pytest.approx(3.0)
    assert query.attributes["impedance"].number == pytest.approx(50.0)
    assert query.attributes["power"].number == pytest.approx(2.0)
    assert query.attributes["frequency_range"].interval == (0.0, 18e9)
    assert query.attributes["connector_a"].text == "sma macho"
    assert query.attributes["connector_b"].text == "sma hembra"


def test_abreviatura_de_conectores(registry):
    query = extract_from_text(registry, "Atenuador 10dB SMA-M/SMA-F 6GHz 5W")
    assert query.attributes["connector_a"].text == "sma macho"
    assert query.attributes["connector_b"].text == "sma hembra"


def test_genero_implicito_del_segundo_conector(registry):
    query = extract_from_text(registry, "atenuador 3 dB SMA macho/hembra DC-18GHz 2W")
    assert query.attributes["connector_a"].text == "sma macho"
    assert query.attributes["connector_b"].text == "sma hembra"


def test_no_confunde_un_rango_con_una_referencia(registry):
    query = extract_from_text(registry, "atenuador 3 dB DC-18 GHz 2W SMA hembra")
    assert query.part_number is None
    assert query.attributes["frequency_range"].interval == (0.0, 18e9)


def test_reconoce_la_referencia_del_fabricante(registry):
    query = extract_from_text(registry, "Atenuador 10dB SMA-M/SMA-F 6GHz 5W ref BW-S10W2+")
    assert query.part_number == "BW-S10W2+"


def test_notacion_rkm_y_coma_decimal(registry):
    query = extract_from_text(registry, "resistencia 4K7 1% 0805 0,25W")
    assert query.family == "resistor"
    assert query.attributes["resistance"].number == pytest.approx(4700.0)
    assert query.attributes["power_rating"].number == pytest.approx(0.25)
    assert query.attributes["package"].text == "0805"


def test_campos_del_formulario_ganan_al_texto(registry):
    query = build_query(
        registry,
        text="atenuador 3 dB DC-18GHz 2W SMA macho/hembra",
        family_id="rf_attenuator",
        fields={"attenuation": "10 dB"},
    )
    assert query.attributes["attenuation"].number == pytest.approx(10.0)


def test_valor_asumido_por_la_familia_se_avisa(registry):
    query = build_query(registry, text="atenuador 3 dB SMA macho/hembra DC-18GHz 2W")
    assert query.attributes["impedance"].number == pytest.approx(50.0)
    assert "asume" in query.attributes["impedance"].note
    assert any("Impedancia" in w for w in query.warnings)


def test_dos_columnas_min_y_max_forman_un_rango(registry):
    family = registry["rf_attenuator"]
    mapped, unmapped = map_fields(
        family, {"Frecuencia mínima": "700 MHz", "Frecuencia máxima": "2,7 GHz"}
    )
    assert mapped["frequency_range"].interval == (700e6, 2.7e9)
    assert not unmapped


def test_campos_desconocidos_se_reportan_no_se_inventan(registry):
    family = registry["rf_attenuator"]
    mapped, unmapped = map_fields(family, {"Color de la carcasa": "azul"})
    assert not mapped
    assert unmapped == {"Color de la carcasa": "azul"}


def test_valor_ilegible_no_se_silencia(registry):
    spec = registry["rf_attenuator"].attributes["attenuation"]
    value = coerce_value(spec, "no indicado")
    assert value.is_empty()
    assert value.note


def test_el_parentesis_del_conector_no_se_pierde(registry):
    spec = registry["rf_attenuator"].attributes["connector_a"]
    assert coerce_value(spec, "N (F)").text == "n hembra"


def test_familia_desconocida_cae_en_generic(registry):
    query = extract_from_text(registry, "un cacharro raro de 3 unidades")
    assert query.family in (None, "generic")


def test_un_valor_de_lista_desconocido_no_se_compara():
    """Guardarlo como si fuera válido provoca descartes falsos.

    La columna "Application" de los borneros mezcla el tipo de conexión con la
    forma del conector: "Screwless Push In" sí lo es, "PCB Header" no. Tomar el
    segundo por un tipo de conexión hacía que pedir push-in descartara la ficha,
    cuando lo honesto es no saberlo.
    """
    from crossref.extract import coerce_value
    from crossref.schema import load_registry
    from tests.conftest import CATALOG_FAMILIES_DIR

    spec = load_registry(CATALOG_FAMILIES_DIR)["terminal_block"].attributes["connection_type"]

    bueno = coerce_value(spec, "Screwless Push In")
    assert bueno.text == "push-in"
    assert not bueno.is_empty()

    desconocido = coerce_value(spec, "PCB Header")
    assert desconocido.is_empty()            # no comparable
    assert desconocido.raw == "PCB Header"   # pero no se pierde
    assert "fuera de la lista" in (desconocido.note or "")
