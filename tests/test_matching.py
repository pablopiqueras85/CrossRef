"""Veredictos: cuando se confirma un 1:1 y cuando no."""

from __future__ import annotations

import pytest

from crossref.models import Verdict


def buscar(service, texto, **kw):
    return service.crossref(text=texto, **kw)


def test_equivalencia_1_a_1(service):
    response = buscar(service, "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra")
    assert response["results"][0]["reference"] == "AT-3SM-2W-18"
    assert response["results"][0]["verdict"] == Verdict.EQUIVALENT.value


def test_el_formato_de_entrada_no_cambia_el_resultado(service):
    formas = [
        "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra",
        "Atenuador; atenuacion: 3dB; impedancia: 50 Ohm; frecuencia: DC-18000 MHz; potencia: 2W; conector 1: SMA-M; conector 2: SMA-F",
        "ATENUADOR 3,0 DB 50OHM DC-18GHZ 2,0W SMA MACHO / SMA HEMBRA",
    ]
    referencias = {buscar(service, f)["results"][0]["reference"] for f in formas}
    assert referencias == {"AT-3SM-2W-18"}


def test_una_discrepancia_obligatoria_descarta(service):
    response = buscar(service, "atenuador 3 dB 50 ohm DC-18 GHz 100 W SMA macho/SMA hembra",
                      include_rejected=True)
    assert not response["results"]
    motivos = " ".join(r["reasons"][0] for r in response["rejected"] if r["reasons"])
    assert "Potencia" in motivos


def test_tolerancia_produce_alternativa_no_equivalencia(service):
    response = buscar(service, "atenuador 3,2 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra")
    mejor = response["results"][0]
    assert mejor["verdict"] == Verdict.ALTERNATIVE.value
    assert any("tolerancia" in r for r in mejor["reasons"])


def test_lo_que_no_se_pregunta_se_saca_a_confirmar_pero_no_bloquea(service):
    """La petición calla sobre el conector, que es obligatorio en atenuadores.

    Exigir que el usuario nombre TODOS los campos obligatorios para poder
    confirmar un 1:1 obligaba a escribir la ficha entera, y era la causa de
    que casi nada saliera como equivalente. Lo que sí impide confirmar es no
    poder comprobar un dato, no que nadie haya preguntado por él: el valor
    que trae el catálogo se saca aparte, para verificarlo a ojo.
    """
    mejor = buscar(service, "atenuador 3 dB 50 ohm DC-18 GHz 2 W")["results"][0]
    assert mejor["verdict"] == Verdict.EQUIVALENT.value
    assert any("Confirma que te vale" in r for r in mejor["reasons"])


def test_lo_que_se_pide_y_no_publica_el_catalogo_si_bloquea(service):
    """El límite que no se mueve: no se afirma lo que no se puede ver."""
    from crossref.models import CatalogItem, utcnow

    service.store.upsert([CatalogItem(
        id="prueba:sin-conector", reference="SIN-CONECTOR", family="attenuator",
        description="Atenuador sin datos de conector",
        specs={"Atenuacion": "3 dB", "Impedancia": "50 ohm"},
        attributes={}, source="prueba", fetched_at=utcnow(),
    )])
    respuesta = buscar(service, "atenuador 3 dB 50 ohm SMA macho/SMA hembra")
    fichas = {r["reference"]: r for r in respuesta["results"]}
    if "SIN-CONECTOR" in fichas:
        assert fichas["SIN-CONECTOR"]["verdict"] != Verdict.EQUIVALENT.value


def test_el_catalogo_puede_superar_lo_pedido(service):
    # Se pide DC-6 GHz y el catalogo llega a 18 GHz: sigue siendo valido.
    response = buscar(service, "atenuador 3 dB 50 ohm DC-6 GHz 2 W SMA macho/SMA hembra")
    assert response["results"][0]["verdict"] == Verdict.EQUIVALENT.value


def test_cada_resultado_explica_campo_a_campo(service):
    mejor = buscar(service, "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra")["results"][0]
    campos = {c["attribute"]: c for c in mejor["comparisons"]}
    assert campos["attenuation"]["query_value"] == "3 dB"
    assert campos["attenuation"]["catalog_value"] == "3 dB"
    assert campos["attenuation"]["rule"]
    assert campos["attenuation"]["reason"]


def test_el_resultado_enlaza_con_la_ficha_y_dice_su_procedencia(service):
    mejor = buscar(service, "carga 50 ohm N hembra DC-4GHz 25W")["results"][0]
    assert mejor["url"].startswith("https://")
    assert mejor["source"] == "test_csv"
    assert mejor["fetched_at"]


def test_referencia_exacta_manda(service):
    response = service.crossref(text="algo", part_number="AT-10SM-2W-18", family="rf_attenuator")
    assert response["results"][0]["reference"] == "AT-10SM-2W-18"
    assert response["results"][0]["exact_reference"] is True


def test_modo_estricto_solo_devuelve_1_a_1(service):
    response = buscar(service, "atenuador 3,2 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra",
                      strict=True)
    assert response["results"] == []


def test_divisor_por_numero_de_vias(service):
    response = buscar(service, "divisor de potencia 4 vias 698-2700 MHz 50 ohm N hembra 200W")
    assert response["results"][0]["reference"] == "PD-4W-698-2700-N"
    assert response["results"][0]["verdict"] == Verdict.EQUIVALENT.value


def test_lote(service):
    filas = [
        {"text": "atenuador 3 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra"},
        {"text": "carga 50 ohm N hembra DC-4GHz 25W"},
        {"text": "atenuador 7 dB 50 ohm DC-18 GHz 2 W SMA macho/SMA hembra"},
    ]
    resultados = service.batch(filas)
    assert [r["status"] for r in resultados[:2]] == ["equivalente", "equivalente"]
    assert resultados[2]["catalog_reference"] is None
