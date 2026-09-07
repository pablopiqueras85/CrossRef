"""Modelos de datos compartidos por el motor, el almacen y la API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .units import Interval, Quantity

__all__ = [
    "FieldStatus",
    "Verdict",
    "AttributeValue",
    "ComponentQuery",
    "CatalogItem",
    "FieldComparison",
    "MatchResult",
    "utcnow",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FieldStatus(str, Enum):
    """Resultado de comparar un atributo concreto."""

    MATCH = "coincide"            # cumple la regla estricta -> vale para 1:1
    CLOSE = "aproximado"          # dentro de la tolerancia de alternativa
    MISMATCH = "no coincide"      # incumple la regla
    MISSING_QUERY = "no informado en la peticion"
    MISSING_CATALOG = "no informado en el catalogo"
    NOT_APPLICABLE = "no aplicable"


class Verdict(str, Enum):
    """Veredicto global de una referencia del catalogo frente a la peticion."""

    EQUIVALENT = "equivalente"        # 1:1 en todos los campos obligatorios
    ALTERNATIVE = "alternativa"       # funciona, con desviaciones dentro de tolerancia
    REVIEW = "requiere revision"      # faltan datos para poder confirmar
    REJECTED = "descartado"           # incumple un campo obligatorio


@dataclass
class AttributeValue:
    """Valor de un atributo ya normalizado, conservando siempre el original."""

    attribute: str
    raw: str
    kind: str = "text"                 # number | range | text | enum | list | bool
    number: float | None = None        # valor canonico si kind == number
    interval: tuple[float, float] | None = None  # canonico si kind == range
    text: str | None = None            # texto normalizado / valor canonico enum
    values: list[str] = field(default_factory=list)  # kind == list
    boolean: bool | None = None
    dimension: str | None = None
    source_field: str | None = None    # nombre del campo tal y como llego
    note: str | None = None            # incidencia de parseo, si la hubo

    @classmethod
    def from_quantity(cls, attribute: str, q: Quantity, **kw: Any) -> "AttributeValue":
        return cls(attribute=attribute, raw=q.raw, kind="number", number=q.value,
                   dimension=q.dimension, **kw)

    @classmethod
    def from_interval(cls, attribute: str, iv: Interval, **kw: Any) -> "AttributeValue":
        return cls(attribute=attribute, raw=iv.raw, kind="range",
                   interval=(iv.low, iv.high), dimension=iv.dimension, **kw)

    def display(self) -> str:
        """Representacion legible del valor canonico."""
        from .units import format_quantity

        if self.kind == "number" and self.number is not None and self.dimension:
            return format_quantity(Quantity(self.number, self.dimension))
        if self.kind == "range" and self.interval and self.dimension:
            lo, hi = self.interval
            return f"{format_quantity(Quantity(lo, self.dimension))} - {format_quantity(Quantity(hi, self.dimension))}"
        if self.kind == "list":
            return ", ".join(self.values)
        if self.kind == "bool" and self.boolean is not None:
            return "si" if self.boolean else "no"
        return self.text or self.raw

    def is_empty(self) -> bool:
        return (
            self.number is None
            and self.interval is None
            and self.boolean is None
            and not self.values
            and not (self.text or "").strip()
        )


@dataclass
class ComponentQuery:
    """Lo que pide el cliente, ya interpretado."""

    family: str | None = None
    family_confidence: float = 0.0
    family_candidates: list[tuple[str, float]] = field(default_factory=list)
    part_number: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    raw_text: str | None = None
    attributes: dict[str, AttributeValue] = field(default_factory=dict)
    unparsed: list[str] = field(default_factory=list)   # trozos que no se supo mapear
    warnings: list[str] = field(default_factory=list)

    def get(self, attribute: str) -> AttributeValue | None:
        value = self.attributes.get(attribute)
        return None if value is None or value.is_empty() else value


@dataclass
class CatalogItem:
    """Una referencia del catalogo propio, con su procedencia."""

    id: str
    reference: str
    family: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    url: str | None = None
    datasheet_url: str | None = None
    category_path: list[str] = field(default_factory=list)
    #: specs tal cual aparecen en la ficha: {"Impedancia": "50 Ohm", ...}
    specs: dict[str, str] = field(default_factory=dict)
    #: specs mapeadas al esquema de la familia y normalizadas
    attributes: dict[str, AttributeValue] = field(default_factory=dict)
    source: str = "manual"
    fetched_at: datetime = field(default_factory=utcnow)
    active: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def get(self, attribute: str) -> AttributeValue | None:
        value = self.attributes.get(attribute)
        return None if value is None or value.is_empty() else value


@dataclass
class FieldComparison:
    """Comparacion explicable de un atributo: entrada vs catalogo."""

    attribute: str
    label: str
    status: FieldStatus
    required: bool
    rule: str
    reason: str
    query_value: str | None = None
    catalog_value: str | None = None
    deviation: str | None = None
    weight: float = 1.0

    @property
    def blocking(self) -> bool:
        return self.required and self.status in (FieldStatus.MISMATCH,)


@dataclass
class MatchResult:
    """Resultado de evaluar una referencia del catalogo frente a la peticion."""

    item: CatalogItem
    verdict: Verdict
    score: float
    comparisons: list[FieldComparison] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    matched_fields: list[str] = field(default_factory=list)
    differing_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    pn_exact: bool = False
