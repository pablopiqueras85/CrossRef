"""Reglas de equivalencia: que cuenta como 1:1 y que como alternativa."""

from __future__ import annotations

import pytest

from crossref.models import AttributeValue, FieldStatus
from crossref.rules import compare_attribute
from crossref.units import parse_interval, parse_quantity


def num(attribute, text, dimension):
    return AttributeValue.from_quantity(attribute, parse_quantity(text, dimension))


def rng(attribute, text, dimension):
    return AttributeValue.from_interval(attribute, parse_interval(text, dimension))


@pytest.fixture
def attenuator(registry):
    return registry["rf_attenuator"]


@pytest.mark.parametrize(
    "pedido,catalogo,esperado",
    [
        ("3 dB", "3 dB", FieldStatus.MATCH),
        ("3 dB", "3,0 dB", FieldStatus.MATCH),
        ("3 dB", "3,3 dB", FieldStatus.CLOSE),
        ("3 dB", "6 dB", FieldStatus.MISMATCH),
    ],
)
def test_atenuacion_exacta_con_banda_de_alternativa(attenuator, pedido, catalogo, esperado):
    result = compare_attribute(
        attenuator.attributes["attenuation"],
        num("attenuation", pedido, "decibel"),
        num("attenuation", catalogo, "decibel"),
    )
    assert result.status is esperado


@pytest.mark.parametrize(
    "pedido,catalogo,esperado",
    [
        ("2 W", "5 W", FieldStatus.MATCH),      # de sobra
        ("2 W", "2 W", FieldStatus.MATCH),
        ("2 W", "1,95 W", FieldStatus.CLOSE),   # dentro del 10% admitido
        ("2 W", "1 W", FieldStatus.MISMATCH),
    ],
)
def test_potencia_es_un_minimo_no_una_igualdad(attenuator, pedido, catalogo, esperado):
    result = compare_attribute(
        attenuator.attributes["power"], num("power", pedido, "power"), num("power", catalogo, "power")
    )
    assert result.status is esperado


@pytest.mark.parametrize(
    "pedido,catalogo,esperado",
    [
        ("DC-18GHz", "DC-26,5GHz", FieldStatus.MATCH),
        ("DC-18GHz", "DC-18GHz", FieldStatus.MATCH),
        ("DC-18GHz", "DC-12GHz", FieldStatus.MISMATCH),
        ("1-2GHz", "0,8-2,05GHz", FieldStatus.MATCH),
        ("1-2GHz", "1,02-2GHz", FieldStatus.CLOSE),   # 5% del rango sin cubrir
    ],
)
def test_el_rango_del_catalogo_debe_cubrir_el_pedido(attenuator, pedido, catalogo, esperado):
    result = compare_attribute(
        attenuator.attributes["frequency_range"],
        rng("frequency_range", pedido, "frequency"),
        rng("frequency_range", catalogo, "frequency"),
    )
    assert result.status is esperado


def test_unidades_distintas_no_impiden_la_coincidencia(attenuator):
    result = compare_attribute(
        attenuator.attributes["frequency_range"],
        rng("frequency_range", "700-2700 MHz", "frequency"),
        rng("frequency_range", "0,7 - 2,7 GHz", "frequency"),
    )
    assert result.status is FieldStatus.MATCH


def test_falta_el_dato_en_la_peticion(attenuator):
    result = compare_attribute(
        attenuator.attributes["attenuation"], None, num("attenuation", "3 dB", "decibel")
    )
    assert result.status is FieldStatus.MISSING_QUERY
    assert "peticion" in result.reason


def test_falta_el_dato_en_el_catalogo(attenuator):
    result = compare_attribute(
        attenuator.attributes["attenuation"], num("attenuation", "3 dB", "decibel"), None
    )
    assert result.status is FieldStatus.MISSING_CATALOG


def test_campo_informativo_nunca_decide(attenuator):
    spec = attenuator.attributes["rohs"]
    result = compare_attribute(
        spec,
        AttributeValue("rohs", "si", kind="bool", boolean=True),
        AttributeValue("rohs", "no", kind="bool", boolean=False),
    )
    assert result.status is FieldStatus.NOT_APPLICABLE
    assert not result.blocking


def test_enum_de_conector_normaliza_sinonimos(attenuator):
    from crossref.extract import coerce_value

    spec = attenuator.attributes["connector_a"]
    result = compare_attribute(spec, coerce_value(spec, "SMA-F"), coerce_value(spec, "SMA Hembra"))
    assert result.status is FieldStatus.MATCH


def test_cada_comparacion_explica_la_regla(attenuator):
    result = compare_attribute(
        attenuator.attributes["power"], num("power", "2 W", "power"), num("power", "1 W", "power")
    )
    assert result.rule and result.reason
    assert result.deviation is not None
