"""Tabla de equivalencias ya declaradas: manda sobre la comparacion de parametros."""

from __future__ import annotations

import pytest

from crossref.crossrefs import apply_cross_references, load_cross_reference_file


@pytest.fixture
def tabla(tmp_path):
    path = tmp_path / "equivalencias.csv"
    path.write_text(
        "Referencia competencia;Fabricante;Referencia propia;Nota\n"
        "XYZ-3DB-SMA;OtroFabricante;AT-3SM-2W-18;validado en 2024\n"
        "NOEXISTE-1;OtroFabricante;NO-ESTA-EN-CATALOGO;\n",
        encoding="utf-8",
    )
    return path


def test_lectura_tolera_nombres_de_columna(tabla):
    entradas = list(load_cross_reference_file(tabla))
    assert len(entradas) == 2
    assert entradas[0].competitor_reference == "XYZ-3DB-SMA"
    assert entradas[0].our_reference == "AT-3SM-2W-18"
    assert entradas[0].competitor_manufacturer == "OtroFabricante"
    assert entradas[0].note == "validado en 2024"


def test_fichero_sin_las_columnas_necesarias_falla_claro(tmp_path):
    path = tmp_path / "mala.csv"
    path.write_text("una,otra\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="referencia"):
        list(load_cross_reference_file(path))


def test_se_asocia_a_la_ficha_y_avisa_de_lo_que_no_existe(service, tabla):
    report = apply_cross_references(
        service.store, load_cross_reference_file(tabla), "equivalencias.csv"
    )
    assert report.applied == 1
    assert report.unknown_references == ["NO-ESTA-EN-CATALOGO"]

    item = service.store.by_reference("AT-3SM-2W-18")[0]
    assert item.extra["cross_references"][0]["reference"] == "XYZ-3DB-SMA"


def test_la_equivalencia_declarada_sale_la_primera_y_se_cita(service, tabla):
    apply_cross_references(service.store, load_cross_reference_file(tabla), "equivalencias.csv")
    response = service.crossref(part_number="XYZ-3DB-SMA", family="rf_attenuator", limit=3)
    mejor = response["results"][0]
    assert mejor["reference"] == "AT-3SM-2W-18"
    assert mejor["exact_reference"] is True
    assert "XYZ-3DB-SMA" in mejor["reasons"][0]
    assert "equivalencias.csv" in mejor["reasons"][0]
    assert "validado en 2024" in mejor["reasons"][0]


def test_no_se_duplica_al_cargar_dos_veces(service, tabla):
    for _ in range(2):
        apply_cross_references(service.store, load_cross_reference_file(tabla), "equivalencias.csv")
    item = service.store.by_reference("AT-3SM-2W-18")[0]
    assert len(item.extra["cross_references"]) == 1


def test_la_referencia_propia_tambien_se_reconoce(service):
    response = service.crossref(part_number="AT-10SM-2W-18", family="rf_attenuator")
    assert response["results"][0]["reference"] == "AT-10SM-2W-18"
    assert "exactamente" in response["results"][0]["reasons"][0]
