"""Esquema de familias de producto cargado desde YAML.

Cada familia declara sus atributos, sus unidades canonicas, cuales son
obligatorios y con que regla se comparan. Anadir una familia nueva no
requiere tocar el codigo del motor.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .normalize import SynonymTable, normalize_text, slug, tokens

__all__ = ["RuleSpec", "AttributeSpec", "FamilySpec", "Registry", "load_registry", "SchemaError"]

VALID_TYPES = {"number", "range", "text", "enum", "list", "bool"}
VALID_RULES = {
    "numeric_equal",
    "at_least",
    "at_most",
    "within",
    "range_covers",
    "range_within",
    "range_overlaps",
    "text_equal",
    "enum_equal",
    "enum_in",
    "list_contains",
    "list_equal",
    "bool_equal",
    "informative",
}


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class RuleSpec:
    """Regla de comparacion de un atributo, con su banda de alternativa."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    def describe(self) -> str:
        human = {
            "numeric_equal": "valor igual",
            "at_least": "catalogo >= peticion",
            "at_most": "catalogo <= peticion",
            "within": "dentro de tolerancia",
            "range_covers": "el rango del catalogo cubre el pedido",
            "range_within": "el rango del catalogo cabe en el pedido",
            "range_overlaps": "los rangos se solapan",
            "text_equal": "texto igual tras normalizar",
            "enum_equal": "mismo valor de lista",
            "enum_in": "valor entre los aceptados",
            "list_contains": "el catalogo incluye lo pedido",
            "list_equal": "misma lista de valores",
            "bool_equal": "mismo si/no",
            "informative": "informativo, no decide",
        }.get(self.kind, self.kind)
        extras = []
        if self.get("rel_tol"):
            extras.append(f"tol. {self.get('rel_tol') * 100:g}%")
        if self.get("abs_tol"):
            extras.append(f"tol. +-{self.get('abs_tol'):g}")
        if self.get("alt_rel_tol"):
            extras.append(f"alternativa hasta {self.get('alt_rel_tol') * 100:g}%")
        if self.get("alt_abs_tol"):
            extras.append(f"alternativa +-{self.get('alt_abs_tol'):g}")
        return human + (f" ({'; '.join(extras)})" if extras else "")


@dataclass
class AttributeSpec:
    """Un atributo comparable dentro de una familia."""

    id: str
    label: str
    type: str = "text"
    dimension: str | None = None
    unit: str | None = None                 # unidad asumida si llega un numero desnudo
    required: bool = False
    weight: float = 1.0
    aliases: list[str] = field(default_factory=list)
    rule: RuleSpec = field(default_factory=lambda: RuleSpec("text_equal"))
    values: SynonymTable = field(default_factory=SynonymTable)
    description: str | None = None
    #: si es True, el atributo se muestra pero nunca descarta una referencia
    informative: bool = False
    #: valor que se da por supuesto cuando la peticion no lo indica
    #: (p. ej. 50 ohm en RF). Siempre se marca como asumido en el resultado.
    assume: str | None = None

    def alias_keys(self) -> set[str]:
        return {slug(a) for a in [self.id, self.label, *self.aliases] if a}


@dataclass
class FamilySpec:
    """Una familia de producto (p. ej. atenuadores coaxiales)."""

    id: str
    label: str
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    attributes: dict[str, AttributeSpec] = field(default_factory=dict)
    description: str | None = None
    source_categories: list[str] = field(default_factory=list)

    @property
    def required_attributes(self) -> list[AttributeSpec]:
        return [a for a in self.attributes.values() if a.required]

    def attribute_for(self, field_name: str) -> AttributeSpec | None:
        """Mapea un nombre de campo recibido ('Frecuencia máx') a un atributo."""
        key = slug(field_name)
        for attribute in self.attributes.values():
            if key in attribute.alias_keys():
                return attribute
        return None

    def match_score(self, text: str) -> float:
        """Cuanto encaja un texto libre con esta familia (0..1)."""
        norm = normalize_text(text)
        if not norm:
            return 0.0
        best = 0.0
        for alias in [self.label, self.id.replace("_", " "), *self.aliases]:
            alias_norm = normalize_text(alias)
            if not alias_norm:
                continue
            if alias_norm == norm:
                return 1.0
            position = norm.find(alias_norm)
            if position >= 0:
                # alias mas largo => senal mas especifica;
                # aparecer al principio del texto suele indicar el nucleo del pedido
                score = min(0.95, 0.55 + 0.05 * len(alias_norm.split()))
                if position <= max(12, len(norm) * 0.25):
                    score = min(0.98, score + 0.15)
                best = max(best, score)
        query_tokens = set(tokens(norm))
        if query_tokens:
            kw = {t for k in self.keywords for t in tokens(k)}
            if kw:
                overlap = len(query_tokens & kw) / len(kw)
                best = max(best, 0.5 * overlap)
        return best


class Registry:
    """Coleccion de familias mas los atributos comunes reutilizables."""

    def __init__(self, families: dict[str, FamilySpec], common: dict[str, dict[str, Any]] | None = None):
        self.families = families
        self.common = common or {}

    def __contains__(self, family_id: object) -> bool:
        return family_id in self.families

    def __getitem__(self, family_id: str) -> FamilySpec:
        try:
            return self.families[family_id]
        except KeyError as exc:
            raise SchemaError(f"familia desconocida: {family_id}") from exc

    def get(self, family_id: str | None) -> FamilySpec | None:
        return self.families.get(family_id) if family_id else None

    def ids(self) -> list[str]:
        return list(self.families)

    def detect(self, text: str, top: int = 3) -> list[tuple[str, float]]:
        """Devuelve las familias mas probables para un texto libre."""
        scored = [(f.id, f.match_score(text)) for f in self.families.values()]
        scored = [(fid, round(score, 3)) for fid, score in scored if score > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top]

    def detect_from_category(self, category_path: Iterable[str]) -> str | None:
        """Asigna familia a un item del catalogo por su ruta de categorias."""
        path = [normalize_text(p) for p in category_path if p]
        for family in self.families.values():
            wanted = {normalize_text(c) for c in family.source_categories}
            if wanted & set(path):
                return family.id
        if path:
            best = self.detect(" ".join(path), top=1)
            if best and best[0][1] >= 0.5:
                return best[0][0]
        return None


# --------------------------------------------------------------------------
# Carga desde YAML
# --------------------------------------------------------------------------


def _parse_rule(raw: Any, attr_type: str) -> RuleSpec:
    if raw is None:
        default = {
            "number": "numeric_equal",
            "range": "range_covers",
            "enum": "enum_equal",
            "list": "list_contains",
            "bool": "bool_equal",
            "text": "text_equal",
        }[attr_type]
        return RuleSpec(default)
    if isinstance(raw, str):
        raw = {"kind": raw}
    if not isinstance(raw, dict) or "kind" not in raw:
        raise SchemaError(f"regla mal formada: {raw!r}")
    kind = str(raw["kind"])
    if kind not in VALID_RULES:
        raise SchemaError(f"regla desconocida: {kind} (validas: {sorted(VALID_RULES)})")
    params = {k: v for k, v in raw.items() if k != "kind"}
    return RuleSpec(kind, params)


def _parse_values(raw: Any) -> SynonymTable:
    table = SynonymTable()
    if not raw:
        return table
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, str):
                table.add(normalize_text(entry))
            elif isinstance(entry, dict):
                for canonical, aliases in entry.items():
                    table.add(normalize_text(canonical), [str(a) for a in (aliases or [])])
    elif isinstance(raw, dict):
        for canonical, aliases in raw.items():
            table.add(normalize_text(canonical), [str(a) for a in (aliases or [])])
    else:
        raise SchemaError(f"lista de valores mal formada: {raw!r}")
    return table


def _build_attribute(raw: dict[str, Any], common: dict[str, dict[str, Any]]) -> AttributeSpec:
    data: dict[str, Any] = {}
    use = raw.get("use")
    if use:
        if use not in common:
            raise SchemaError(f"atributo comun desconocido: {use}")
        data = copy.deepcopy(common[use])
        data.setdefault("id", use)
    data.update({k: v for k, v in raw.items() if k != "use"})

    attr_id = data.get("id")
    if not attr_id:
        raise SchemaError(f"atributo sin id: {raw!r}")
    attr_type = data.get("type", "text")
    if attr_type not in VALID_TYPES:
        raise SchemaError(f"tipo de atributo no valido: {attr_type}")
    dimension = data.get("dimension")
    if attr_type in ("number", "range") and not dimension:
        raise SchemaError(f"'{attr_id}' es {attr_type} y necesita 'dimension'")

    informative = bool(data.get("informative", False))
    rule = _parse_rule(data.get("rule"), attr_type)
    if informative:
        rule = RuleSpec("informative", rule.params)

    return AttributeSpec(
        id=str(attr_id),
        label=str(data.get("label", attr_id)),
        type=attr_type,
        dimension=dimension,
        unit=data.get("unit"),
        required=bool(data.get("required", False)) and not informative,
        weight=float(data.get("weight", 1.0)),
        aliases=[str(a) for a in data.get("aliases", [])],
        rule=rule,
        values=_parse_values(data.get("values")),
        description=data.get("description"),
        informative=informative,
        assume=str(data["assume"]) if data.get("assume") is not None else None,
    )


def _build_family(data: dict[str, Any], common: dict[str, dict[str, Any]]) -> FamilySpec:
    family_id = data.get("id")
    if not family_id:
        raise SchemaError("familia sin 'id'")
    attributes: dict[str, AttributeSpec] = {}
    for raw_attr in data.get("attributes", []):
        spec = _build_attribute(raw_attr, common)
        if spec.id in attributes:
            raise SchemaError(f"atributo duplicado '{spec.id}' en familia '{family_id}'")
        attributes[spec.id] = spec
    return FamilySpec(
        id=str(family_id),
        label=str(data.get("label", family_id)),
        aliases=[str(a) for a in data.get("aliases", [])],
        keywords=[str(k) for k in data.get("keywords", [])],
        attributes=attributes,
        description=data.get("description"),
        source_categories=[str(c) for c in data.get("source_categories", [])],
    )


def load_registry(path: str | Path) -> Registry:
    """Carga todas las familias de un directorio (`_common.yaml` aparte)."""
    directory = Path(path)
    if not directory.exists():
        raise SchemaError(f"directorio de familias inexistente: {directory}")

    common: dict[str, dict[str, Any]] = {}
    common_file = directory / "_common.yaml"
    if common_file.exists():
        loaded = yaml.safe_load(common_file.read_text(encoding="utf-8")) or {}
        common = loaded.get("attributes", {}) or {}

    families: dict[str, FamilySpec] = {}
    for yaml_file in sorted(directory.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        for entry in data if isinstance(data, list) else [data]:
            family = _build_family(entry, common)
            if family.id in families:
                raise SchemaError(f"familia duplicada: {family.id}")
            families[family.id] = family
    if not families:
        raise SchemaError(f"no se encontro ninguna familia en {directory}")
    return Registry(families, common)
