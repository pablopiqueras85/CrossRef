"""Motor de equivalencias: compara la peticion con las fichas del catalogo.

Reglas de decision (deliberadamente conservadoras):

* `equivalente`  -> todos los campos obligatorios cumplen la regla estricta.
* `alternativa`  -> cumple, pero algun campo se ha aceptado por tolerancia.
* `requiere revision` -> falta un dato obligatorio en la peticion o en la ficha.
* `descartado`   -> algun campo obligatorio incumple la regla.

Nunca se confirma una equivalencia con datos incompletos.
"""

from __future__ import annotations

from .models import (
    CatalogItem,
    ComponentQuery,
    FieldComparison,
    FieldStatus,
    MatchResult,
    Verdict,
)
from .normalize import normalize_pn, normalize_text, similarity
from .rules import compare_attribute
from .schema import FamilySpec, Registry

__all__ = ["evaluate", "rank", "VERDICT_ORDER"]

VERDICT_ORDER = {
    Verdict.EQUIVALENT: 0,
    Verdict.ALTERNATIVE: 1,
    Verdict.REVIEW: 2,
    Verdict.REJECTED: 3,
}

#: Peso de cada estado al calcular la puntuacion de ordenacion.
_STATUS_SCORE = {
    FieldStatus.MATCH: 1.0,
    FieldStatus.CLOSE: 0.6,
    FieldStatus.MISSING_QUERY: 0.5,
    FieldStatus.MISSING_CATALOG: 0.25,
    FieldStatus.MISMATCH: 0.0,
}


def evaluate(family: FamilySpec, query: ComponentQuery, item: CatalogItem) -> MatchResult:
    """Compara una ficha del catalogo con la peticion y explica el resultado."""
    comparisons: list[FieldComparison] = [
        compare_attribute(spec, query.attributes.get(attr_id), item.attributes.get(attr_id))
        for attr_id, spec in family.attributes.items()
    ]

    blocking = [c for c in comparisons if c.required and c.status is FieldStatus.MISMATCH]
    optional_mismatch = [c for c in comparisons if not c.required and c.status is FieldStatus.MISMATCH]
    close = [c for c in comparisons if c.status is FieldStatus.CLOSE]
    missing_required = [
        c
        for c in comparisons
        if c.required and c.status in (FieldStatus.MISSING_QUERY, FieldStatus.MISSING_CATALOG)
    ]
    matched = [c for c in comparisons if c.status is FieldStatus.MATCH]

    pn_exact, pn_explanation = _same_reference(query, item)

    if blocking:
        verdict = Verdict.REJECTED
    elif missing_required:
        verdict = Verdict.REVIEW
    elif close or optional_mismatch:
        verdict = Verdict.ALTERNATIVE
    elif matched:
        verdict = Verdict.EQUIVALENT
    else:
        # Nada que comparar: no se confirma nada.
        verdict = Verdict.REVIEW

    reasons = _build_reasons(
        verdict, blocking, missing_required, close, optional_mismatch, matched, pn_explanation
    )

    return MatchResult(
        item=item,
        verdict=verdict,
        score=_score(comparisons, query, item, pn_exact),
        comparisons=comparisons,
        reasons=reasons,
        matched_fields=[c.attribute for c in matched],
        differing_fields=[c.attribute for c in comparisons if c.status in (FieldStatus.MISMATCH, FieldStatus.CLOSE)],
        missing_fields=[
            c.attribute
            for c in comparisons
            if c.status in (FieldStatus.MISSING_QUERY, FieldStatus.MISSING_CATALOG)
        ],
        pn_exact=pn_exact,
    )


def _build_reasons(
    verdict: Verdict,
    blocking: list[FieldComparison],
    missing_required: list[FieldComparison],
    close: list[FieldComparison],
    optional_mismatch: list[FieldComparison],
    matched: list[FieldComparison],
    pn_explanation: str | None,
) -> list[str]:
    reasons: list[str] = []
    if pn_explanation:
        reasons.append(pn_explanation)
    if verdict is Verdict.EQUIVALENT:
        reasons.append(
            "Equivalencia 1:1: " + ", ".join(c.label for c in matched) + " cumplen la regla estricta."
        )
    for c in blocking:
        reasons.append(f"Descartado por {c.label}: {c.reason}.")
    for c in missing_required:
        which = "la peticion" if c.status is FieldStatus.MISSING_QUERY else "la ficha del catalogo"
        reasons.append(f"No se puede confirmar {c.label}: falta el dato en {which}.")
    for c in close:
        reasons.append(f"{c.label} aceptado por tolerancia: {c.reason}.")
    for c in optional_mismatch:
        reasons.append(f"{c.label} difiere (campo no obligatorio): {c.reason}.")
    return reasons


def _same_reference(query: ComponentQuery, item: CatalogItem) -> tuple[bool, str | None]:
    """La referencia pedida es la del catalogo, o una equivalencia ya declarada.

    Devuelve (coincide, explicacion). La explicacion cita la lista de la que
    procede la equivalencia, para que se pueda auditar.
    """
    wanted = normalize_pn(query.part_number or "")
    if not wanted:
        return False, None
    if wanted == normalize_pn(item.reference):
        return True, "La referencia pedida es exactamente esta referencia del catalogo."

    for entry in _declared_cross_references(item):
        if wanted != normalize_pn(entry.get("reference", "")):
            continue
        manufacturer = entry.get("manufacturer")
        origin = entry.get("source")
        detail = f"'{entry.get('reference')}'"
        if manufacturer:
            detail += f" de {manufacturer}"
        text = f"Equivalencia ya declarada para {detail}"
        if origin:
            text += f" (segun {origin})"
        note = entry.get("note")
        return True, text + (f": {note}." if note else ".")
    return False, None


def _declared_cross_references(item: CatalogItem) -> list[dict]:
    """Normaliza `extra.cross_references`, que admite texto o fichas completas."""
    declared = item.extra.get("cross_references") or []
    if isinstance(declared, str):
        declared = [declared]
    entries = []
    for entry in declared:
        if isinstance(entry, str):
            entries.append({"reference": entry})
        elif isinstance(entry, dict) and entry.get("reference"):
            entries.append(entry)
    return entries


def _score(
    comparisons: list[FieldComparison],
    query: ComponentQuery,
    item: CatalogItem,
    pn_exact: bool,
) -> float:
    """Puntuacion 0..1 solo para ordenar. El veredicto no depende de ella."""
    total = weighted = 0.0
    for c in comparisons:
        if c.status is FieldStatus.NOT_APPLICABLE:
            continue
        total += c.weight
        if c.specificity is not None:
            # Encaje contra un rango publicado: cuanto mas ajustado, mejor senal.
            weighted += c.weight * (0.45 + 0.35 * c.specificity)
        else:
            weighted += c.weight * _STATUS_SCORE.get(c.status, 0.0)
    base = weighted / total if total else 0.0

    # Desempate por parecido textual de la descripcion.
    text_hint = similarity(
        " ".join(filter(None, [query.description or query.raw_text or "", query.manufacturer or ""])),
        " ".join(filter(None, [item.description or "", item.manufacturer or "", item.reference])),
    )
    score = 0.9 * base + 0.1 * text_hint
    if pn_exact:
        score = min(1.0, score + 0.25)
    return round(score, 4)


def rank(
    registry: Registry,
    query: ComponentQuery,
    items: list[CatalogItem],
    *,
    limit: int = 20,
    include_rejected: bool = False,
    min_score: float = 0.0,
) -> list[MatchResult]:
    """Evalua todo el catalogo candidato y ordena por utilidad para el usuario."""
    family = registry.get(query.family) or registry["generic"]
    results: list[MatchResult] = []
    for item in items:
        item_family = registry.get(item.family) or family
        # Si la ficha pertenece a otra familia, se compara con el esquema comun
        # de la peticion: solo coincidiran los atributos que ambas compartan.
        results.append(evaluate(family if item_family.id != family.id else item_family, query, item))

    if not include_rejected:
        results = [r for r in results if r.verdict is not Verdict.REJECTED]
    if min_score:
        results = [r for r in results if r.score >= min_score or r.pn_exact]

    results.sort(key=lambda r: (not r.pn_exact, VERDICT_ORDER[r.verdict], -r.score, r.item.reference))
    return results[:limit]


def summarize(results: list[MatchResult]) -> dict[str, int]:
    """Recuento por veredicto, para la cabecera de la respuesta."""
    counts = {v.value: 0 for v in Verdict}
    for result in results:
        counts[result.verdict.value] += 1
    return counts
