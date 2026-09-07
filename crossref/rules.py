"""Motor de reglas: compara un atributo de la peticion con el del catalogo.

Cada comparacion devuelve un `FieldComparison` con el estado, la regla
aplicada y el motivo en lenguaje llano. Nunca se resume en una puntuacion
opaca: la puntuacion solo sirve para ordenar, no para decidir.
"""

from __future__ import annotations

import math
from typing import Callable

from .models import AttributeValue, FieldComparison, FieldStatus
from .normalize import normalize_text, similarity
from .schema import AttributeSpec, RuleSpec
from .units import DIMENSIONS, Quantity, format_quantity

__all__ = ["compare_attribute", "RuleOutcome"]

EPS = 1e-9

#: (estado, motivo, desviacion)
RuleOutcome = tuple[FieldStatus, str, str | None]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def _fmt(value: float | None, dimension: str | None) -> str:
    if value is None:
        return "-"
    if dimension and dimension in DIMENSIONS:
        return format_quantity(Quantity(value, dimension))
    return f"{value:g}"


def _rel_diff(catalog: float, query: float) -> float:
    if query == 0:
        return 0.0 if catalog == 0 else math.inf
    return (catalog - query) / abs(query)


def _deviation(catalog: float, query: float, dimension: str | None) -> str:
    delta = catalog - query
    sign = "+" if delta >= 0 else ""
    absolute = f"{sign}{_fmt(delta, dimension) if delta >= 0 else _fmt(delta, dimension)}"
    if query:
        return f"{absolute} ({sign}{_rel_diff(catalog, query) * 100:.2f}%)"
    return absolute


def _tolerance(rule: RuleSpec, query: float, prefix: str = "") -> float:
    """Tolerancia absoluta efectiva combinando abs_tol y rel_tol."""
    abs_tol = float(rule.get(f"{prefix}abs_tol", 0.0) or 0.0)
    rel_tol = float(rule.get(f"{prefix}rel_tol", 0.0) or 0.0)
    return max(abs_tol, rel_tol * abs(query), abs(query) * EPS, EPS)


# --------------------------------------------------------------------------
# Reglas numericas
# --------------------------------------------------------------------------


def _rule_numeric_equal(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    qv, cv = q.number, c.number
    assert qv is not None and cv is not None
    strict = _tolerance(rule, qv)
    diff = abs(cv - qv)
    deviation = _deviation(cv, qv, dim)
    if diff <= strict:
        return FieldStatus.MATCH, f"{_fmt(cv, dim)} coincide con {_fmt(qv, dim)}", None
    loose = max(strict, _tolerance(rule, qv, "alt_"))
    if rule.get("alt_abs_tol") or rule.get("alt_rel_tol"):
        if diff <= loose:
            return (
                FieldStatus.CLOSE,
                f"{_fmt(cv, dim)} frente a {_fmt(qv, dim)}: dentro de la tolerancia de alternativa",
                deviation,
            )
    return FieldStatus.MISMATCH, f"{_fmt(cv, dim)} no es {_fmt(qv, dim)}", deviation


def _rule_at_least(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    qv, cv = q.number, c.number
    assert qv is not None and cv is not None
    deviation = _deviation(cv, qv, dim)
    if cv >= qv - _tolerance(rule, qv):
        return FieldStatus.MATCH, f"{_fmt(cv, dim)} cubre el minimo pedido ({_fmt(qv, dim)})", None
    floor = qv * float(rule.get("alt_ratio", 1.0)) - float(rule.get("alt_abs_tol", 0.0) or 0.0)
    if cv >= floor - EPS and floor < qv:
        return (
            FieldStatus.CLOSE,
            f"{_fmt(cv, dim)} queda por debajo de {_fmt(qv, dim)} pero dentro del margen admitido",
            deviation,
        )
    return FieldStatus.MISMATCH, f"{_fmt(cv, dim)} es insuficiente frente a {_fmt(qv, dim)}", deviation


def _rule_at_most(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    qv, cv = q.number, c.number
    assert qv is not None and cv is not None
    deviation = _deviation(cv, qv, dim)
    if cv <= qv + _tolerance(rule, qv):
        return FieldStatus.MATCH, f"{_fmt(cv, dim)} no empeora el maximo pedido ({_fmt(qv, dim)})", None
    ceiling = qv * float(rule.get("alt_ratio", 1.0)) + float(rule.get("alt_abs_tol", 0.0) or 0.0)
    if cv <= ceiling + EPS and ceiling > qv:
        return (
            FieldStatus.CLOSE,
            f"{_fmt(cv, dim)} supera {_fmt(qv, dim)} pero dentro del margen admitido",
            deviation,
        )
    return FieldStatus.MISMATCH, f"{_fmt(cv, dim)} supera el maximo pedido {_fmt(qv, dim)}", deviation


# --------------------------------------------------------------------------
# Reglas de rango
# --------------------------------------------------------------------------


def _span(interval: tuple[float, float]) -> float:
    low, high = interval
    return high - low if math.isfinite(high - low) else math.inf


def _fmt_range(interval: tuple[float, float], dim: str | None) -> str:
    return f"{_fmt(interval[0], dim)} - {_fmt(interval[1], dim)}"


def _rule_range_covers(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    qi, ci = q.interval, c.interval
    assert qi is not None and ci is not None
    q_lo, q_hi = qi
    c_lo, c_hi = ci
    tol = _tolerance(rule, max(abs(q_lo), abs(q_hi)) or 1.0)
    if c_lo <= q_lo + tol and c_hi >= q_hi - tol:
        return FieldStatus.MATCH, f"{_fmt_range(ci, dim)} cubre {_fmt_range(qi, dim)}", None

    margin = float(rule.get("alt_margin", 0.0) or 0.0)
    span = _span(qi)
    allowed = span * margin if math.isfinite(span) else 0.0
    uncovered = max(0.0, c_lo - q_lo) + max(0.0, q_hi - c_hi)
    detail = []
    if c_lo > q_lo + tol:
        detail.append(f"no llega por abajo (empieza en {_fmt(c_lo, dim)})")
    if c_hi < q_hi - tol:
        detail.append(f"no llega por arriba (termina en {_fmt(c_hi, dim)})")
    deviation = f"{_fmt(uncovered, dim)} del rango sin cubrir"
    if margin and uncovered <= allowed + EPS:
        return FieldStatus.CLOSE, f"{_fmt_range(ci, dim)} casi cubre {_fmt_range(qi, dim)}: " + " y ".join(detail), deviation
    return FieldStatus.MISMATCH, f"{_fmt_range(ci, dim)} " + " y ".join(detail), deviation


def _rule_range_within(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    swapped_q = AttributeValue(q.attribute, q.raw, kind="range", interval=c.interval, dimension=dim)
    swapped_c = AttributeValue(c.attribute, c.raw, kind="range", interval=q.interval, dimension=dim)
    status, reason, deviation = _rule_range_covers(rule, swapped_q, swapped_c, dim)
    return status, reason.replace("cubre", "queda dentro de"), deviation


def _rule_range_overlaps(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    qi, ci = q.interval, c.interval
    assert qi is not None and ci is not None
    if ci[0] <= qi[1] and qi[0] <= ci[1]:
        return FieldStatus.MATCH, f"{_fmt_range(ci, dim)} se solapa con {_fmt_range(qi, dim)}", None
    return FieldStatus.MISMATCH, f"{_fmt_range(ci, dim)} no se solapa con {_fmt_range(qi, dim)}", None


# --------------------------------------------------------------------------
# Reglas de texto / listas
# --------------------------------------------------------------------------


def _rule_text_equal(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    qt, ct = (q.text or q.raw), (c.text or c.raw)
    if normalize_text(qt) == normalize_text(ct):
        return FieldStatus.MATCH, f"'{ct}' coincide con '{qt}'", None
    threshold = float(rule.get("alt_similarity", 0.0) or 0.0)
    if threshold:
        score = similarity(qt, ct)
        if score >= threshold:
            return FieldStatus.CLOSE, f"'{ct}' se parece a '{qt}' ({score:.0%})", f"similitud {score:.0%}"
    return FieldStatus.MISMATCH, f"'{ct}' no coincide con '{qt}'", None


def _rule_enum_equal(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    qt, ct = (q.text or q.raw), (c.text or c.raw)
    if normalize_text(qt) == normalize_text(ct):
        return FieldStatus.MATCH, f"'{ct}' es el valor pedido", None
    equivalents = {normalize_text(v) for v in rule.get("alt_values", {}).get(normalize_text(qt), [])}
    if normalize_text(ct) in equivalents:
        return FieldStatus.CLOSE, f"'{ct}' esta declarado como intercambiable con '{qt}'", "valor alternativo"
    return FieldStatus.MISMATCH, f"'{ct}' no es '{qt}'", None


def _rule_enum_in(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    accepted = {normalize_text(v) for v in (c.values or [c.text or c.raw])}
    qt = normalize_text(q.text or q.raw)
    if qt in accepted:
        return FieldStatus.MATCH, f"'{q.text or q.raw}' esta entre los valores del catalogo", None
    return FieldStatus.MISMATCH, f"'{q.text or q.raw}' no esta entre {sorted(accepted)}", None


def _rule_list_contains(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    wanted = [normalize_text(v) for v in (q.values or ([q.text] if q.text else []))]
    have = {normalize_text(v) for v in (c.values or ([c.text] if c.text else []))}
    missing = [v for v in wanted if v not in have]
    if not missing:
        return FieldStatus.MATCH, "el catalogo incluye todos los valores pedidos", None
    ratio = 1 - len(missing) / max(1, len(wanted))
    alt_ratio = float(rule.get("alt_ratio", 0.0) or 0.0)
    deviation = f"faltan: {', '.join(missing)}"
    if alt_ratio and ratio >= alt_ratio:
        return FieldStatus.CLOSE, f"cubre {ratio:.0%} de los valores pedidos", deviation
    return FieldStatus.MISMATCH, f"no incluye {', '.join(missing)}", deviation


def _rule_list_equal(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    wanted = {normalize_text(v) for v in (q.values or ([q.text] if q.text else []))}
    have = {normalize_text(v) for v in (c.values or ([c.text] if c.text else []))}
    if wanted == have:
        return FieldStatus.MATCH, "misma lista de valores", None
    diff = sorted(wanted ^ have)
    return FieldStatus.MISMATCH, f"listas distintas ({', '.join(diff)})", None


def _rule_bool_equal(rule: RuleSpec, q: AttributeValue, c: AttributeValue, dim: str | None) -> RuleOutcome:
    if q.boolean == c.boolean:
        return FieldStatus.MATCH, "mismo valor", None
    if q.boolean is False and c.boolean is True:
        return FieldStatus.MATCH, "el catalogo lo cumple aunque no se exigia", None
    return FieldStatus.MISMATCH, "valor distinto", None


_RULES: dict[str, Callable[[RuleSpec, AttributeValue, AttributeValue, str | None], RuleOutcome]] = {
    "numeric_equal": _rule_numeric_equal,
    "within": _rule_numeric_equal,
    "at_least": _rule_at_least,
    "at_most": _rule_at_most,
    "range_covers": _rule_range_covers,
    "range_within": _rule_range_within,
    "range_overlaps": _rule_range_overlaps,
    "text_equal": _rule_text_equal,
    "enum_equal": _rule_enum_equal,
    "enum_in": _rule_enum_in,
    "list_contains": _rule_list_contains,
    "list_equal": _rule_list_equal,
    "bool_equal": _rule_bool_equal,
}


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------


def _compare_against_published_range(
    query: AttributeValue, catalog: AttributeValue, dimension: str | None
) -> dict:
    """El catalogo publica un rango (el de una serie) donde se pedia un valor.

    Que el valor pedido caiga dentro del rango de la serie NO demuestra que
    exista una referencia con ese valor exacto: como mucho es un candidato.
    """
    assert query.number is not None and catalog.interval is not None
    low, high = catalog.interval
    span = _fmt_range(catalog.interval, dimension)
    value = _fmt(query.number, dimension)
    if low <= query.number <= high:
        # Un rango estrecho alrededor del valor pedido es una senal mucho mas
        # fuerte que uno amplisimo: se guarda para poder ordenar por ello.
        relative_span = (high - low) / max(abs(query.number), EPS)
        specificity = 1.0 / (1.0 + relative_span)
        return {
            "status": FieldStatus.CLOSE,
            "reason": (
                f"{value} cae dentro del rango publicado ({span}), pero el catalogo no "
                "detalla el valor de cada referencia: hay que confirmar la referencia concreta"
            ),
            "deviation": f"rango de serie, ajuste {specificity:.0%}",
            "specificity": round(specificity, 4),
        }
    return {
        "status": FieldStatus.MISMATCH,
        "reason": f"{value} queda fuera del rango publicado ({span})",
        "deviation": "fuera del rango de serie",
    }


def compare_attribute(
    spec: AttributeSpec,
    query: AttributeValue | None,
    catalog: AttributeValue | None,
) -> FieldComparison:
    """Compara un atributo y devuelve el resultado explicado."""
    q_display = query.display() if query and not query.is_empty() else None
    c_display = catalog.display() if catalog and not catalog.is_empty() else None
    base = dict(
        attribute=spec.id,
        label=spec.label,
        required=spec.required,
        rule=spec.rule.describe(),
        query_value=q_display,
        catalog_value=c_display,
        weight=spec.weight,
    )

    if spec.rule.kind == "informative":
        return FieldComparison(status=FieldStatus.NOT_APPLICABLE,
                               reason="campo informativo: no interviene en el veredicto", **base)

    if (query is None or query.is_empty()) and (catalog is None or catalog.is_empty()):
        return FieldComparison(status=FieldStatus.NOT_APPLICABLE,
                               reason="sin dato en ninguna de las dos partes", **base)
    if query is None or query.is_empty():
        return FieldComparison(status=FieldStatus.MISSING_QUERY,
                               reason="la peticion no indica este valor", **base)
    if catalog is None or catalog.is_empty():
        return FieldComparison(status=FieldStatus.MISSING_CATALOG,
                               reason="la ficha del catalogo no publica este valor", **base)

    if query.kind == "number" and catalog.kind == "range" and catalog.interval:
        return FieldComparison(**base, **_compare_against_published_range(query, catalog, spec.dimension))

    if query.kind != catalog.kind:
        return FieldComparison(status=FieldStatus.MISSING_CATALOG,
                               reason=f"tipos no comparables ({query.kind} vs {catalog.kind})", **base)

    handler = _RULES.get(spec.rule.kind)
    if handler is None:  # pragma: no cover - protegido por el validador del esquema
        return FieldComparison(status=FieldStatus.MISSING_CATALOG,
                               reason=f"regla no implementada: {spec.rule.kind}", **base)

    status, reason, deviation = handler(spec.rule, query, catalog, spec.dimension)
    return FieldComparison(status=status, reason=reason, deviation=deviation, **base)
