"""Unidades: el mismo valor escrito de mil formas debe dar el mismo numero."""

from __future__ import annotations

import math

import pytest

from crossref.units import (
    UnitError,
    dimension_of_unit,
    format_quantity,
    parse_interval,
    parse_number,
    parse_quantity,
)


@pytest.mark.parametrize(
    "text,expected",
    [("1.5", 1.5), ("1,5", 1.5), ("1.234", 1234.0), ("1,234,567.5", 1234567.5),
     ("1.234.567,5", 1234567.5), ("2e3", 2000.0), ("-3,5", -3.5)],
)
def test_parse_number_admite_formatos_es_y_en(text, expected):
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text,dimension,expected",
    [
        ("1,5 GHz", "frequency", 1.5e9),
        ("1500MHz", "frequency", 1.5e9),
        ("1500000 kHz", "frequency", 1.5e9),
        ("50 Ohm", "resistance", 50.0),
        ("50Ω", "resistance", 50.0),
        ("4K7", "resistance", 4700.0),
        ("1R5", "resistance", 1.5),
        ("4n7", "capacitance", 4.7e-9),
        ("100 nF", "capacitance", 1e-7),
        ("10uH", "inductance", 1e-5),
        ("-3 dB", "decibel", -3.0),
        ("2 W", "power", 2.0),
        ("30 dBm", "power", 1.0),
        ("0,25W", "power", 0.25),
        ("4", "ratio", 4.0),
    ],
)
def test_parse_quantity_convierte_a_unidad_base(text, dimension, expected):
    assert parse_quantity(text, dimension).value == pytest.approx(expected)


def test_misma_magnitud_distinto_formato_mismo_valor():
    formas = ["1,5 GHz", "1500 MHz", "1500000 kHz", "1.5GHz", "1500000000 Hz"]
    valores = {parse_quantity(f, "frequency").value for f in formas}
    assert len(valores) == 1


def test_mili_y_mega_no_se_confunden():
    assert parse_quantity("5 mW", "power").value == pytest.approx(0.005)
    assert parse_quantity("5 MW", "power").value == pytest.approx(5e6)


@pytest.mark.parametrize(
    "text,dimension,low,high",
    [
        ("DC-18GHz", "frequency", 0.0, 18e9),
        ("DC - 3000 MHz", "frequency", 0.0, 3e9),
        ("0,5 a 6 GHz", "frequency", 0.5e9, 6e9),
        ("700 MHz - 2,7 GHz", "frequency", 0.7e9, 2.7e9),
        ("-55 a 125 °C", "temperature", -55.0, 125.0),
        ("-40 ... +85 C", "temperature", -40.0, 85.0),
        ("2 GHz", "frequency", 2e9, 2e9),
    ],
)
def test_parse_interval(text, dimension, low, high):
    interval = parse_interval(text, dimension)
    assert interval.low == pytest.approx(low)
    assert interval.high == pytest.approx(high)


def test_interval_desde_deja_limite_superior_infinito():
    assert parse_interval("desde 1 GHz", "frequency").high == math.inf


def test_covers():
    pedido = parse_interval("DC-18GHz", "frequency")
    amplio = parse_interval("DC-26,5GHz", "frequency")
    corto = parse_interval("DC-12GHz", "frequency")
    assert amplio.covers(pedido)
    assert not corto.covers(pedido)


@pytest.mark.parametrize("unit,dimension", [("GHz", "frequency"), ("ghz", "frequency"),
                                            ("mW", "power"), ("Ohm", "resistance"),
                                            ("dB", "decibel"), ("nF", "capacitance")])
def test_dimension_of_unit(unit, dimension):
    assert dimension_of_unit(unit) == dimension


def test_format_quantity_usa_prefijo_legible():
    assert format_quantity(parse_quantity("1500 MHz", "frequency")) == "1.5 GHz"
    assert format_quantity(parse_quantity("0,25 W", "power")) == "250 mW"


def test_valor_no_interpretable_lanza():
    with pytest.raises(UnitError):
        parse_quantity("azul", "frequency")
