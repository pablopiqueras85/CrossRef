"""Interpretacion de la peticion: de texto libre o campos sueltos a valores.

La extraccion es determinista y trazable: todo lo que no se sabe mapear se
devuelve en `unparsed` en lugar de adivinarse en silencio.
"""

from __future__ import annotations

import re
from typing import Iterable

from .models import AttributeValue, ComponentQuery
from .normalize import normalize_pn, normalize_text, slug, tokens
from .schema import AttributeSpec, FamilySpec, Registry
from .units import UnitError, looks_like_range, parse_interval, parse_quantity

__all__ = ["coerce_value", "map_fields", "extract_from_text", "build_query"]

# Cualificadores que hay que quitar antes de parsear un numero.
_QUALIFIER_RE = re.compile(
    r"^\s*(?:max\.?|min\.?|typ\.?|typical|nom\.?|nominal|maximo|máximo|minimo|mínimo|"
    r"hasta|up\s+to|desde|from|aprox\.?|approx\.?|about|≈|~|<=|>=|≤|≥|<|>|±|\+/-|\+-)\s*",
    re.IGNORECASE,
)
_TRAILING_NOTE_RE = re.compile(r"\s*(?:[(\[]|,(?=\s)|;).*$")

_BOOL_TRUE = {"si", "sí", "yes", "true", "1", "y", "s", "cumple", "compliant", "rohs"}
_BOOL_FALSE = {"no", "false", "0", "n", "no cumple", "not compliant"}

_LIST_SPLIT_RE = re.compile(r"\s*(?:[;/+]|,(?!\d)|\band\b|\by\b)\s*")


# --------------------------------------------------------------------------
# Conversion de un valor suelto segun el tipo del atributo
# --------------------------------------------------------------------------


def coerce_value(spec: AttributeSpec, raw: str, source_field: str | None = None) -> AttributeValue:
    """Convierte un texto al valor normalizado que exige `spec`.

    Nunca lanza: si no se puede interpretar, deja el valor vacio y anota el
    motivo en `note`, para que aparezca como "requiere revision".
    """
    raw = "" if raw is None else str(raw).strip()
    value = AttributeValue(attribute=spec.id, raw=raw, kind=spec.type,
                           dimension=spec.dimension, source_field=source_field)
    if not raw:
        return value

    numeric = spec.type in ("number", "range")
    cleaned = (_TRAILING_NOTE_RE.sub("", _QUALIFIER_RE.sub("", raw)).strip() or raw) if numeric else raw

    try:
        if spec.type == "number":
            if looks_like_range(cleaned):
                # "10 to 2700 Ohm": el catalogo publica el rango de una serie,
                # no el valor de una referencia concreta.
                iv = parse_interval(cleaned, spec.dimension or "ratio", spec.unit)
                value.kind = "range"
                value.interval = (iv.low, iv.high)
                value.note = "el catalogo publica un rango, no un valor concreto"
            else:
                q = parse_quantity(cleaned, spec.dimension or "ratio", spec.unit)
                value.number = q.value
        elif spec.type == "range":
            iv = parse_interval(cleaned, spec.dimension or "ratio", spec.unit)
            value.interval = (iv.low, iv.high)
        elif spec.type == "bool":
            key = normalize_text(cleaned)
            value.boolean = True if key in _BOOL_TRUE else False if key in _BOOL_FALSE else None
            if value.boolean is None:
                value.note = f"valor booleano no reconocido: {raw!r}"
        elif spec.type == "enum":
            resolved = _resolve_enum(spec, raw)
            if resolved is None:
                value.text = normalize_text(raw)
                value.note = f"valor fuera de la lista conocida de '{spec.label}'"
            else:
                value.text = resolved
        elif spec.type == "list":
            parts = [p for p in _LIST_SPLIT_RE.split(raw) if p.strip()]
            value.values = [_resolve_enum(spec, p) or normalize_text(p) for p in parts]
        else:
            value.text = normalize_text(raw)
    except (UnitError, ValueError) as exc:
        value.note = f"no interpretable ({exc})"
    return value


def _resolve_enum(spec: AttributeSpec, raw: str) -> str | None:
    """Busca el valor canonico; admite que venga embebido en una frase."""
    if not spec.values:
        return normalize_text(raw) or None
    direct = spec.values.canonical(raw)
    if direct:
        return direct
    haystack = normalize_text(raw)
    best: tuple[int, str] | None = None
    for canonical in spec.values.known():
        for candidate in _alias_variants(spec, canonical):
            if candidate and candidate in haystack:
                score = len(candidate)
                if best is None or score > best[0]:
                    best = (score, canonical)
    return best[1] if best else None


def _alias_variants(spec: AttributeSpec, canonical: str) -> list[str]:
    variants = {normalize_text(canonical)}
    for alias, target in spec.values._index.items():  # noqa: SLF001 - tabla interna propia
        if target == canonical:
            variants.add(alias)
    return sorted(variants, key=len, reverse=True)


# --------------------------------------------------------------------------
# Mapeo de campos con nombre
# --------------------------------------------------------------------------


def map_fields(
    family: FamilySpec,
    fields: dict[str, str],
) -> tuple[dict[str, AttributeValue], dict[str, str]]:
    """Mapea {'Frecuencia máx': '18 GHz'} a atributos de la familia.

    Devuelve los atributos reconocidos y los campos que no se supieron mapear.
    """
    mapped: dict[str, AttributeValue] = {}
    unmapped: dict[str, str] = {}
    range_parts: dict[str, dict[str, str]] = {}

    for name, raw in (fields or {}).items():
        if raw is None or not str(raw).strip():
            continue
        bound = _range_bound(name)
        spec = family.attribute_for(name) or (family.attributes.get(slug(name).replace(" ", "_")))
        if spec is None:
            unmapped[name] = str(raw)
            continue
        if bound and spec.type == "range":
            range_parts.setdefault(spec.id, {})[bound] = str(raw)
            continue
        mapped[spec.id] = coerce_value(spec, str(raw), source_field=name)

    # "Frecuencia mín" + "Frecuencia máx" en dos columnas -> un unico rango
    for attr_id, bounds in range_parts.items():
        spec = family.attributes[attr_id]
        if attr_id in mapped:
            continue
        low, high = bounds.get("min"), bounds.get("max")
        text = f"{low} - {high}" if low and high else (f"hasta {high}" if high else f"desde {low}")
        mapped[attr_id] = coerce_value(spec, text, source_field=" + ".join(bounds))
    return mapped, unmapped


_MIN_RE = re.compile(r"\b(min|minimo|minima|inferior|desde|low|from|start)\b")
_MAX_RE = re.compile(r"\b(max|maximo|maxima|superior|hasta|high|to|end)\b")


def _range_bound(field_name: str) -> str | None:
    key = slug(field_name)
    if _MIN_RE.search(key):
        return "min"
    if _MAX_RE.search(key):
        return "max"
    return None


# --------------------------------------------------------------------------
# Extraccion desde texto libre
# --------------------------------------------------------------------------

_KV_RE = re.compile(r"^\s*([^:=]{2,60}?)\s*[:=]\s*(.+?)\s*$")
_SEGMENT_SPLIT_RE = re.compile(r"[\n\r;|]+|(?<!\d),(?!\d)|\s{3,}")

_NUM = r"[+-]?\d+(?:[.,]\d+)?"
_UNIT = r"[a-zA-ZΩµμ%°º]{1,8}(?:/[a-zA-ZΩµμ°º]{1,6})?"
_RANGE_RE = re.compile(
    rf"(?<![\w.]) (?P<lo>{_NUM}\s*(?:{_UNIT})?|dc|cc)\s*(?:-{{1,2}}|–|—|\.{{2,}}|~|\ba\b|\bto\b|\bhasta\b)\s*"
    rf"(?P<hi>{_NUM})\s*(?P<unit>{_UNIT})?".replace(" ", "", 1),
    re.IGNORECASE,
)
_QTY_RE = re.compile(rf"(?<![\w.])(?P<num>{_NUM})\s*(?P<unit>{_UNIT})")
_RKM_RE = re.compile(r"(?<![\w.])\d+[RrKkMmpnuµμ]\d+(?![\w.])")
_PN_RE = re.compile(
    r"(?<![\w/-])(?=[A-Za-z0-9][A-Za-z0-9\-/_.]{3,})(?=[^\s]*\d)(?=[^\s]*[A-Za-z])"
    r"[A-Za-z0-9][A-Za-z0-9\-/_.]{3,}\+?"
)

#: por debajo de esta confianza no se da por buena la familia detectada:
#: es preferible caer en 'generic' y avisar que comparar con el esquema equivocado
MIN_FAMILY_CONFIDENCE = 0.35

#: palabras que nunca aportan informacion tecnica y no deben ir a `unparsed`
_STOPWORDS = {
    "necesito", "necesitamos", "quiero", "busco", "buscamos", "para", "con", "sin", "por",
    "del", "las", "los", "una", "uno", "unos", "unas", "que", "the", "and", "for", "with",
    "need", "want", "looking", "please", "favor", "gracias", "referencia", "ref", "equivalente",
    "equivalencia", "similar", "alternativa", "componente", "producto", "articulo", "unidad",
    "unidades", "pieza", "piezas", "tipo", "modelo", "aprox", "sobre", "cliente", "pedido",
    "conector", "conectores", "connector", "connectors", "salida", "entrada",
}


def extract_from_text(
    registry: Registry,
    text: str,
    family_id: str | None = None,
) -> ComponentQuery:
    """Interpreta una peticion escrita en lenguaje natural."""
    raw_text = (text or "").strip()
    query = ComponentQuery(raw_text=raw_text, description=raw_text or None)
    if family_id and registry.get(family_id) is not None:
        query.family, query.family_confidence = family_id, 1.0
    if not raw_text:
        # Sin texto libre no hay nada que interpretar, pero la familia indicada
        # a mano debe conservarse para que luego se mapeen los campos del formulario.
        if not family_id:
            query.warnings.append("peticion vacia")
        return query

    segments = [s.strip() for s in _SEGMENT_SPLIT_RE.split(raw_text) if s and s.strip()]

    # 1. Familia: la indicada por el usuario, o la deducida del texto completo.
    if family_id and registry.get(family_id) is None:
        query.warnings.append(f"familia desconocida '{family_id}', se usa deteccion automatica")
    if query.family is None:
        candidates = registry.detect(raw_text)
        query.family_candidates = candidates
        if candidates and candidates[0][1] >= MIN_FAMILY_CONFIDENCE:
            query.family, query.family_confidence = candidates[0]
        elif candidates:
            query.warnings.append(
                "no se reconoce con claridad el tipo de componente (mejor opcion: "
                + ", ".join(f"{fid} {score:.0%}" for fid, score in candidates)
                + "). Indica la familia a mano para comparar con las reglas correctas."
            )
        if len(candidates) > 1 and candidates[0][1] >= MIN_FAMILY_CONFIDENCE \
                and candidates[0][1] - candidates[1][1] < 0.1:
            query.warnings.append(
                "familia ambigua: " + ", ".join(f"{fid} ({score:.0%})" for fid, score in candidates)
            )
    family = registry.get(query.family) or registry.get("generic")
    if family is None:  # pragma: no cover - el registro siempre trae 'generic'
        query.warnings.append("no hay familia aplicable")
        return query
    query.family = query.family or family.id
    if query.family == "generic":
        query.warnings.append(
            "no se ha identificado la familia: solo se compararan los campos que coincidan por nombre"
        )

    # 2. Pares "campo: valor" explicitos.
    leftovers: list[str] = []
    for segment in segments:
        match = _KV_RE.match(segment)
        if not match:
            leftovers.append(segment)
            continue
        name, value = match.group(1), match.group(2)
        spec = family.attribute_for(name)
        if spec is None:
            leftovers.append(segment)
            continue
        bound = _range_bound(name)
        if bound and spec.type == "range" and spec.id in query.attributes:
            merged = _merge_bound(query.attributes[spec.id], value, bound)
            query.attributes[spec.id] = coerce_value(spec, merged, source_field=name)
            continue
        if bound and spec.type == "range":
            value = f"hasta {value}" if bound == "max" else f"desde {value}"
        query.attributes[spec.id] = coerce_value(spec, value, source_field=name)

    rest = " ".join(leftovers) or raw_text

    # 3. Valores con unidad y valores de lista. Se anotan los tramos consumidos
    #    para que no se confundan luego con una referencia de fabricante.
    consumed: list[tuple[int, int]] = []
    consumed += _extract_values(query, rest, family)
    consumed += _extract_enums(query, rest, family)

    # 4. Referencia y fabricante en lo que queda sin consumir.
    _extract_identity(query, rest, family, consumed)

    query.unparsed = _remaining_tokens(rest, query, family)
    return query


def _merge_bound(existing: AttributeValue, value: str, bound: str) -> str:
    if existing.interval:
        low, high = existing.interval
        return f"{value} - {high}" if bound == "min" else f"{low} - {value}"
    return value


_MANUF_RE = re.compile(
    r"\b(?:fabricante|manufacturer|marca|brand)\s*[:=]?\s*([A-Za-z][\w&.\- ]{2,30})", re.IGNORECASE
)


def _overlaps(span: tuple[int, int], spans: Iterable[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < e and s < end for s, e in spans)


def _extract_identity(
    query: ComponentQuery,
    text: str,
    family: FamilySpec,
    consumed: list[tuple[int, int]],
) -> None:
    if not query.manufacturer:
        m = _MANUF_RE.search(text)
        if m:
            query.manufacturer = m.group(1).strip(" .,")

    if query.part_number:
        return
    family_words = {t for alias in [family.label, *family.aliases, *family.keywords] for t in tokens(alias)}
    for match in _PN_RE.finditer(text):
        candidate = match.group(0)
        if _overlaps(match.span(), consumed) or _looks_like_value(candidate):
            continue
        norm = normalize_text(candidate)
        if norm in family_words or norm in _STOPWORDS:
            continue
        query.part_number = candidate.strip(" .,")
        return


_DC_PREFIX_RE = re.compile(r"^(?:dc|cc)\s*[-–]\s*\d", re.IGNORECASE)


def _looks_like_value(token: str) -> bool:
    """'18GHz', '4K7', 'DC-18' o '2.4mm' son valores, no part numbers."""
    from .units import dimension_of_unit

    if _DC_PREFIX_RE.match(token):
        return True
    m = re.fullmatch(rf"({_NUM})\s*([A-Za-zΩµμ%]+)", token)
    if m and dimension_of_unit(m.group(2)):
        return True
    # patron RKM: 4K7, 1R5, 4n7
    return bool(re.fullmatch(r"\d+[a-zA-ZΩµμ]\d+", token))


def _extract_values(query: ComponentQuery, text: str, family: FamilySpec) -> list[tuple[int, int]]:
    """Asigna 'DC-18 GHz' o '2 W' al atributo cuya dimension encaje."""
    from .units import dimension_of_unit

    consumed: list[tuple[int, int]] = []

    # Rangos primero: consumen dos numeros de golpe.
    for match in _RANGE_RE.finditer(text):
        unit = match.group("unit") or _unit_of(match.group("lo"))
        dimension = dimension_of_unit(unit) if unit else None
        if not dimension:
            continue
        spec = _pick_attribute(family, dimension, ("range",), text, match.start(), query)
        if spec is None:
            continue
        query.attributes[spec.id] = coerce_value(spec, match.group(0), source_field="texto libre")
        consumed.append(match.span())

    for match in _QTY_RE.finditer(text):
        if _overlaps(match.span(), consumed):
            continue
        dimension = dimension_of_unit(match.group("unit"))
        if not dimension:
            continue
        spec = _pick_attribute(family, dimension, ("number", "range"), text, match.start(), query)
        if spec is None:
            continue
        if spec.type == "range":
            # "atenuador 6 GHz" = tiene que funcionar en 6 GHz, no "hasta 6 GHz".
            query.warnings.append(
                f"'{match.group(0)}' se ha interpretado como un punto de '{spec.label}'; "
                "indica un rango (por ejemplo 'DC-6 GHz') si querias otra cosa"
            )
        query.attributes[spec.id] = coerce_value(spec, match.group(0), source_field="texto libre")
        consumed.append(match.span())

    # Notacion RKM ("4K7" = 4,7 kohm) usando las dimensiones que tenga la familia.
    for match in _RKM_RE.finditer(text):
        if _overlaps(match.span(), consumed):
            continue
        for dimension in ("resistance", "capacitance", "inductance"):
            spec = _pick_attribute(family, dimension, ("number",), text, match.start(), query)
            if spec is None:
                continue
            value = coerce_value(spec, match.group(0), source_field="texto libre")
            if value.number is not None:
                query.attributes[spec.id] = value
                consumed.append(match.span())
            break

    # Numeros desnudos que solo pueden ser un atributo concreto ("4 vias").
    norm_text = normalize_text(text)
    for spec in family.attributes.values():
        if spec.id in query.attributes or spec.type != "number" or spec.dimension != "ratio":
            continue
        for alias in [spec.label, *spec.aliases]:
            alias_norm = normalize_text(alias)
            if len(alias_norm) < 2:
                continue
            m = re.search(rf"({_NUM})\s*(?:de\s+)?{re.escape(alias_norm)}\b", norm_text, re.IGNORECASE)
            if m:
                query.attributes[spec.id] = coerce_value(spec, m.group(1), source_field="texto libre")
                break
    return consumed


def _unit_of(text: str) -> str | None:
    m = re.search(r"([A-Za-zΩµμ%]+)\s*$", text.strip())
    return m.group(1) if m else None


def _pick_attribute(
    family: FamilySpec,
    dimension: str,
    kinds: tuple[str, ...],
    text: str,
    position: int,
    query: ComponentQuery,
) -> AttributeSpec | None:
    """Elige a que atributo pertenece un valor suelto de esa dimension."""
    candidates = [
        spec
        for spec in family.attributes.values()
        if spec.dimension == dimension and spec.type in kinds and not spec.informative
    ]
    if not candidates:
        return None

    # 1) Palabra clave del atributo cerca del valor (ventana previa de 40 caracteres).
    context = normalize_text(text[max(0, position - 40) : position + 15])
    for spec in sorted(candidates, key=lambda s: -s.weight):
        for alias in [spec.label, *spec.aliases]:
            alias_norm = normalize_text(alias)
            if len(alias_norm) >= 3 and alias_norm in context:
                return spec

    # 2) Sin pista, el primero libre por prioridad: tipo preferido, obligatorio y peso.
    def priority(spec: AttributeSpec) -> tuple:
        return (kinds.index(spec.type), not spec.required, -spec.weight, spec.id)

    for spec in sorted(candidates, key=priority):
        if spec.id not in query.attributes:
            return spec
    return None


def _alias_pattern(alias: str) -> re.Pattern[str]:
    """'sma m' -> regex que tambien casa 'SMA-M', 'SMA (M)' o 'sma_m'."""
    chunks = [re.escape(c) for c in re.split(r"[^a-z0-9]+", normalize_text(alias)) if c]
    if not chunks:
        return re.compile(r"(?!x)x")
    body = r"[\s\-_.()/]*".join(chunks)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE)


#: generos de conector, para resolver abreviaturas del tipo "SMA macho/hembra"
_GENDERS: dict[str, tuple[str, ...]] = {
    "macho": ("macho", "male", "m", "plug"),
    "hembra": ("hembra", "female", "f", "h", "jack"),
}
_BARE_GENDER_RE = re.compile(
    r"^\s*(?:[/\-]|\s+a\s+|\s+to\s+)?\s*(" + "|".join(sorted({g for v in _GENDERS.values() for g in v}, key=len, reverse=True)) + r")(?![a-z0-9])"
)


def _extract_enums(query: ComponentQuery, text: str, family: FamilySpec) -> list[tuple[int, int]]:
    """Detecta conectores, encapsulados y demas valores de lista en el texto."""
    haystack = normalize_text(text)
    consumed: list[tuple[int, int]] = []
    for spec in family.attributes.values():
        if spec.type != "enum" or not spec.values or spec.id in query.attributes:
            continue
        hits: list[tuple[int, int, str]] = []
        for canonical in spec.values.known():
            for alias in spec.values.aliases_of(canonical):
                if len(normalize_text(alias)) < 2:
                    continue
                for m in _alias_pattern(alias).finditer(haystack):
                    hits.append((m.start(), m.end(), canonical))
        # Un valor ya asignado a otro atributo (p. ej. el conector 1) no se reutiliza.
        hits = [h for h in hits if not _overlaps((h[0], h[1]), consumed)]
        if not hits:
            continue
        # Se queda con el alias mas largo de cada posicion, sin solapamientos.
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        chosen: list[tuple[int, int, str]] = []
        last_end = -1
        for start, end, canonical in hits:
            if start < last_end:
                continue
            chosen.append((start, end, canonical))
            last_end = end

        query.attributes[spec.id] = AttributeValue(
            attribute=spec.id, raw=chosen[0][2], kind="enum", text=chosen[0][2],
            source_field="texto libre",
        )
        consumed.append((chosen[0][0], chosen[0][1]))

        partner = _partner_attribute(family, spec)
        if partner is None or partner.id in query.attributes:
            continue
        if len(chosen) > 1:
            query.attributes[partner.id] = AttributeValue(
                attribute=partner.id, raw=chosen[1][2], kind="enum", text=chosen[1][2],
                source_field="texto libre",
            )
            consumed.append((chosen[1][0], chosen[1][1]))
            continue
        # "SMA macho/hembra": el segundo conector solo indica el genero.
        implied = _implied_partner(spec, chosen[0][2], haystack, chosen[0][1])
        if implied:
            value, end = implied
            query.attributes[partner.id] = AttributeValue(
                attribute=partner.id, raw=value, kind="enum", text=value,
                source_field="texto libre",
                note=f"deducido de '{chosen[0][2]}' mas el genero indicado",
            )
            consumed.append((chosen[0][1], end))
    return consumed


def _implied_partner(
    spec: AttributeSpec, canonical: str, haystack: str, position: int
) -> tuple[str, int] | None:
    """De 'sma macho' + '/hembra' deduce 'sma hembra' si existe en la lista."""
    match = _BARE_GENDER_RE.match(haystack[position : position + 16])
    if not match:
        return None
    word = match.group(1)
    target = next((canon for canon, aliases in _GENDERS.items() if word in aliases), None)
    if target is None:
        return None
    current = next((canon for canon in _GENDERS if canon in canonical), None)
    if current is None or current == target:
        return None
    candidate = canonical.replace(current, target)
    resolved = spec.values.canonical(candidate)
    return (resolved, position + match.end()) if resolved else None


def _partner_attribute(family: FamilySpec, spec: AttributeSpec) -> AttributeSpec | None:
    """connector_a -> connector_b, para repartir dos conectores citados seguidos."""
    if spec.id.endswith("_a"):
        return family.attributes.get(spec.id[:-2] + "_b")
    return None


def _remaining_tokens(text: str, query: ComponentQuery, family: FamilySpec) -> list[str]:
    """Palabras del texto que el sistema no ha sabido usar (se muestran al usuario)."""
    used = set()
    for value in query.attributes.values():
        used |= set(tokens(value.raw)) | set(tokens(value.display()))
    used |= set(tokens(query.part_number or "")) | set(tokens(query.manufacturer or ""))
    used |= {t for alias in [family.label, family.id, *family.aliases, *family.keywords] for t in tokens(alias)}
    used |= {t for spec in family.attributes.values() for alias in [spec.label, *spec.aliases] for t in tokens(alias)}

    out: list[str] = []
    for token in tokens(text):
        if token in used or token in _STOPWORDS or len(token) < 3 or token.replace(".", "").isdigit():
            continue
        out.append(token)
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def build_query(
    registry: Registry,
    *,
    text: str | None = None,
    family_id: str | None = None,
    fields: dict[str, str] | None = None,
    part_number: str | None = None,
    manufacturer: str | None = None,
) -> ComponentQuery:
    """Construye la peticion combinando texto libre y campos del formulario.

    Los campos explicitos del formulario siempre ganan al texto libre.
    """
    query = extract_from_text(registry, text or "", family_id)
    if part_number:
        query.part_number = part_number
    if manufacturer:
        query.manufacturer = manufacturer
    if fields:
        if (query.family is None or query.family == "generic") and not family_id:
            detected = registry.detect(" ".join(str(v) for v in fields.values()))
            if detected and detected[0][1] > query.family_confidence:
                query.family, query.family_confidence = detected[0]
                query.family_candidates = detected
        family = registry.get(query.family) or registry["generic"]
        mapped, unmapped = map_fields(family, fields)
        query.attributes.update(mapped)
        for name, value in unmapped.items():
            query.unparsed.append(f"{name}={value}")
            query.warnings.append(f"campo no reconocido en la familia '{family.id}': {name}")
    apply_assumed_values(registry, query)
    return query


def apply_assumed_values(registry: Registry, query: ComponentQuery) -> None:
    """Rellena los valores que la familia da por supuestos (p. ej. 50 ohm en RF).

    Nunca es silencioso: el valor queda marcado como asumido y se avisa, para
    que quien revise la equivalencia sepa que ese dato no venia del cliente.
    """
    family = registry.get(query.family)
    if family is None:
        return
    for spec in family.attributes.values():
        if not spec.assume:
            continue
        current = query.attributes.get(spec.id)
        if current is not None and not current.is_empty():
            continue
        value = coerce_value(spec, spec.assume, source_field="valor por defecto de la familia")
        if value.is_empty():
            continue
        value.note = f"no venia en la peticion; se asume {spec.assume}"
        query.attributes[spec.id] = value
        query.warnings.append(
            f"'{spec.label}' no estaba en la peticion: se asume {spec.assume} "
            f"(valor por defecto de la familia '{family.label}'). Confirmalo con el cliente."
        )


def describe_query(query: ComponentQuery, family: FamilySpec | None) -> list[dict[str, str]]:
    """Resumen legible de lo que el sistema ha entendido."""
    rows = []
    for attr_id, value in query.attributes.items():
        spec = family.attributes.get(attr_id) if family else None
        rows.append(
            {
                "attribute": attr_id,
                "label": spec.label if spec else attr_id,
                "raw": value.raw,
                "normalized": value.display(),
                "source": value.source_field or "",
                "note": value.note or "",
            }
        )
    return rows
