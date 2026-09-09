"""Parseo y conversion de magnitudes fisicas a una unidad canonica.

El objetivo es que "1,5 GHz", "1500 MHz" y "1500000000 Hz" produzcan
exactamente el mismo valor canonico, de forma determinista y explicable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

__all__ = [
    "Quantity",
    "Interval",
    "UnitError",
    "DIMENSIONS",
    "parse_number",
    "parse_quantity",
    "parse_interval",
    "format_quantity",
    "dimension_of_unit",
]


class UnitError(ValueError):
    """La cadena no se puede interpretar como magnitud de la dimension pedida."""


# --------------------------------------------------------------------------
# Prefijos SI
# --------------------------------------------------------------------------

# Sensible a mayusculas: 'm' = mili, 'M' = mega.
_PREFIXES: dict[str, float] = {
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,  # U+00B5 micro sign
    "μ": 1e-6,  # U+03BC greek mu
    "m": 1e-3,
    "": 1.0,
    "k": 1e3,
    "K": 1e3,  # tolerado: mucho catalogo escribe KHz / KOhm
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
}

# Prefijos adicionales que solo tienen sentido en longitud.
_LENGTH_PREFIXES: dict[str, float] = {"c": 1e-2, "d": 1e-1}


@dataclass(frozen=True)
class Dimension:
    """Una magnitud fisica y las formas en que el catalogo puede escribirla."""

    id: str
    base_unit: str
    #: alias de unidad -> factor a unidad base (antes de aplicar prefijo SI)
    units: dict[str, float]
    #: unidades que admiten prefijo SI (Hz, W, V, ...)
    prefixable: frozenset[str] = frozenset()
    #: notacion tipo RKM: 4K7 = 4700
    rkm: bool = False
    #: unidades logaritmicas: alias -> callable(valor) -> valor base
    log_units: tuple[str, ...] = ()
    allow_length_prefixes: bool = False


def _d(
    id: str,
    base_unit: str,
    units: dict[str, float],
    prefixable: Iterable[str] = (),
    rkm: bool = False,
    log_units: Iterable[str] = (),
    allow_length_prefixes: bool = False,
) -> Dimension:
    return Dimension(
        id=id,
        base_unit=base_unit,
        units=units,
        prefixable=frozenset(prefixable),
        rkm=rkm,
        log_units=tuple(log_units),
        allow_length_prefixes=allow_length_prefixes,
    )


DIMENSIONS: dict[str, Dimension] = {
    "frequency": _d(
        "frequency",
        "Hz",
        {"hz": 1.0, "hertz": 1.0, "hercios": 1.0, "cps": 1.0},
        prefixable=["hz", "hertz"],
        rkm=True,
    ),
    "resistance": _d(
        "resistance",
        "ohm",
        {"ohm": 1.0, "ohms": 1.0, "ohmios": 1.0, "Ω": 1.0, "ω": 1.0, "r": 1.0},
        prefixable=["ohm", "ohms", "ohmios", "Ω", "ω", "r"],
        rkm=True,
    ),
    "power": _d(
        "power",
        "W",
        {"w": 1.0, "watt": 1.0, "watts": 1.0, "vatios": 1.0},
        prefixable=["w", "watt", "watts", "vatios"],
        log_units=("dbm", "dbw"),
    ),
    "voltage": _d(
        "voltage",
        "V",
        {"v": 1.0, "volt": 1.0, "volts": 1.0, "voltios": 1.0, "vdc": 1.0, "vac": 1.0},
        prefixable=["v", "volt", "volts", "voltios", "vdc", "vac"],
    ),
    "current": _d(
        "current",
        "A",
        {"a": 1.0, "amp": 1.0, "amps": 1.0, "amperes": 1.0, "amperios": 1.0},
        prefixable=["a", "amp", "amps", "amperes", "amperios"],
    ),
    "capacitance": _d(
        "capacitance",
        "F",
        {"f": 1.0, "farad": 1.0, "faradios": 1.0},
        prefixable=["f", "farad", "faradios"],
        rkm=True,
    ),
    "inductance": _d(
        "inductance",
        "H",
        {"h": 1.0, "henry": 1.0, "henrios": 1.0},
        prefixable=["h", "henry", "henrios"],
        rkm=True,
    ),
    # dBi y dBd son ganancia de antena referida a un radiador ideal o a un
    # dipolo. Como magnitud comparable entre si valen igual que un dB.
    "decibel": _d("decibel", "dB", {"db": 1.0, "dbs": 1.0, "dbi": 1.0, "dbd": 1.0}),
    "length": _d(
        "length",
        "m",
        {
            "m": 1.0,
            "metro": 1.0,
            "metros": 1.0,
            "meter": 1.0,
            "meters": 1.0,
            "in": 0.0254,
            "inch": 0.0254,
            "inches": 0.0254,
            '"': 0.0254,
            "''": 0.0254,
            "mil": 0.0254e-3,
            "mils": 0.0254e-3,
            "thou": 0.0254e-3,
            "ft": 0.3048,
        },
        prefixable=["m", "metro", "metros", "meter", "meters"],
        allow_length_prefixes=True,
    ),
    "mass": _d(
        "mass",
        "g",
        {"g": 1.0, "gr": 1.0, "gram": 1.0, "grams": 1.0, "gramos": 1.0, "lb": 453.59237, "oz": 28.349523125},
        prefixable=["g", "gram", "grams", "gramos"],
    ),
    "temperature": _d(
        "temperature",
        "degC",
        {"c": 1.0, "degc": 1.0, "°c": 1.0, "celsius": 1.0, "º c": 1.0, "ºc": 1.0},
    ),
    "time": _d(
        "time",
        "s",
        {"s": 1.0, "sec": 1.0, "seg": 1.0, "segundos": 1.0, "min": 60.0, "h": 3600.0, "hora": 3600.0},
        prefixable=["s", "sec", "seg"],
    ),
    "angle": _d("angle", "deg", {"deg": 1.0, "°": 1.0, "º": 1.0, "grados": 1.0, "rad": 180.0 / math.pi}),
    # Nota: ppm/K (coeficiente de temperatura) se trata aqui como ppm. No es la
    # misma magnitud fisica, pero permite comparar dos TCR entre si, que es lo
    # unico que se necesita, sin inventar una dimension por cada coeficiente.
    "percent": _d(
        "percent",
        "%",
        {
            "%": 1.0, "pct": 1.0, "percent": 1.0, "por ciento": 1.0,
            "ppm": 1e-4, "ppm/k": 1e-4, "ppm/c": 1e-4, "ppm/°c": 1e-4, "ppmk": 1e-4,
        },
    ),
    "torque": _d("torque", "Nm", {"nm": 1.0, "n.m": 1.0, "n-m": 1.0, "in-lb": 0.112984829, "inlb": 0.112984829}),
    "luminous_intensity": _d(
        "luminous_intensity",
        "mcd",
        {"cd": 1000.0, "mcd": 1.0, "candela": 1000.0, "candelas": 1000.0, "ucd": 1e-3},
    ),
    "luminous_flux": _d(
        "luminous_flux", "lm", {"lm": 1.0, "lumen": 1.0, "lumens": 1.0, "mlm": 1e-3}
    ),
    "thermal_conductivity": _d(
        "thermal_conductivity",
        "W/mK",
        {
            "w/mk": 1.0, "w/m k": 1.0, "w/(m k)": 1.0, "w/(m·k)": 1.0, "wmk": 1.0,
            "w/mc": 1.0, "w/m°c": 1.0, "w m-1 k-1": 1.0,
        },
    ),
    "thermal_resistance": _d(
        "thermal_resistance",
        "K/W",
        {"k/w": 1.0, "kw": 1.0, "°c/w": 1.0, "c/w": 1.0, "k/w typ": 1.0},
    ),
    "energy": _d("energy", "J", {"j": 1.0, "joule": 1.0, "joules": 1.0, "julios": 1.0},
                 prefixable=["j", "joule", "joules"]),
    "charge": _d("charge", "C", {"c": 1.0, "culombios": 1.0, "coulomb": 1.0},
                 prefixable=["c", "coulomb"]),
    "ratio": _d("ratio", "", {":1": 1.0, "": 1.0}),
}


def dimension_of_unit(unit: str) -> str | None:
    """Devuelve el id de dimension al que pertenece una unidad escrita a mano.

    Respeta la caja al resolver el prefijo (mW != MW) y solo prueba variantes
    de mayusculas/minusculas si la forma original no encaja con nada.
    """
    raw = (unit or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    for dim in DIMENSIONS.values():
        if lower in dim.units or lower in dim.log_units:
            return dim.id
    for candidate in _case_variants(raw):
        for dim in DIMENSIONS.values():
            try:
                _split_prefix(candidate, dim)
            except UnitError:
                continue
            return dim.id
    return None


def _case_variants(unit: str) -> list[str]:
    """'GHz' tal cual; luego 'ghz' -> 'GHz' y 'MHZ' -> 'MHz' como respaldo."""
    variants = [unit]
    if len(unit) > 1:
        for prefix_case in (unit[0].upper(), unit[0].lower()):
            for rest_case in (unit[1:], unit[1:].capitalize(), unit[1:].lower()):
                candidate = prefix_case + rest_case
                if candidate not in variants:
                    variants.append(candidate)
    return variants


# --------------------------------------------------------------------------
# Numeros
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d+)*|[.,]\d+)(?:[eE][+-]?\d+)?$")
#: agrupacion de millares (1.234.567). El primer grupo nunca es "0": nadie
#: escribe "0.005" queriendo decir 5, asi que ahi el separador es decimal.
_THOUSANDS_RE = re.compile(r"^[+-]?(?!0[.,])\d{1,3}(?:([.,])\d{3})+$")


def parse_number(text: str) -> float:
    """Convierte un numero escrito en formato ES o EN a float.

    Regla: si aparecen coma y punto, manda el ultimo como separador decimal.
    Si solo hay un separador y el patron es de miles (1.234 / 1,234,567) se
    trata como separador de millares.
    """
    raw = text.strip().replace(" ", "").replace(" ", "")
    if not raw or not _NUM_RE.match(raw):
        raise UnitError(f"numero no reconocido: {text!r}")

    exp = ""
    if "e" in raw.lower():
        idx = raw.lower().index("e")
        raw, exp = raw[:idx], raw[idx:]

    has_dot, has_comma = "." in raw, "," in raw
    if has_dot and has_comma:
        decimal_sep = "." if raw.rindex(".") > raw.rindex(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        raw = raw.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        if _THOUSANDS_RE.match(raw) and raw.count(sep) >= 1 and len(raw.split(sep)[-1]) == 3:
            # 1.234 / 12,345,678 -> millares
            raw = raw.replace(sep, "")
        else:
            raw = raw.replace(sep, ".")
    return float(raw + exp)


# --------------------------------------------------------------------------
# Magnitudes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Quantity:
    """Un valor convertido a la unidad base de su dimension."""

    value: float
    dimension: str
    raw: str = ""

    @property
    def unit(self) -> str:
        return DIMENSIONS[self.dimension].base_unit

    def __str__(self) -> str:  # pragma: no cover - conveniencia
        return format_quantity(self)


@dataclass(frozen=True)
class Interval:
    """Rango cerrado [low, high] en unidad base."""

    low: float
    high: float
    dimension: str
    raw: str = ""

    def covers(self, other: "Interval", tol: float = 0.0) -> bool:
        return self.low <= other.low + tol and self.high >= other.high - tol

    def overlaps(self, other: "Interval") -> bool:
        return self.low <= other.high and other.low <= self.high

    def __str__(self) -> str:  # pragma: no cover - conveniencia
        lo = format_quantity(Quantity(self.low, self.dimension))
        hi = format_quantity(Quantity(self.high, self.dimension))
        return f"{lo} - {hi}"


def _split_prefix(unit: str, dim: Dimension) -> float:
    """Descompone 'GHz' en (prefijo G, unidad Hz) y devuelve el factor total."""
    unit = unit.strip()
    if not unit:
        raise UnitError("unidad vacia")
    lower = unit.lower()
    if lower in dim.units:
        return dim.units[lower]
    # El catalogo escribe unidades compuestas con espacios y con distintos
    # signos de multiplicacion: "ppm/ °C", "W/(m*K)", "W/(m·K)". Se comparan
    # sin espacios y con un unico separador.
    compacta = lower.replace(" ", "").replace("*", "·")
    if compacta in dim.units:
        return dim.units[compacta]
    for conocida, factor in dim.units.items():
        if conocida.replace(" ", "").replace("*", "·") == compacta:
            return factor

    prefixes = dict(_PREFIXES)
    if dim.allow_length_prefixes:
        prefixes.update(_LENGTH_PREFIXES)

    for plen in (2, 1):
        if len(unit) <= plen:
            continue
        prefix, rest = unit[:plen], unit[plen:]
        if prefix not in prefixes:
            continue
        rest_l = rest.lower()
        if rest_l in dim.prefixable:
            return prefixes[prefix] * dim.units[rest_l]
    raise UnitError(f"unidad no valida para {dim.id}: {unit!r}")


def _log_to_base(value: float, unit: str, dim: Dimension) -> float:
    unit = unit.lower()
    if dim.id == "power":
        if unit == "dbm":
            return 10 ** ((value - 30.0) / 10.0)
        if unit == "dbw":
            return 10 ** (value / 10.0)
    raise UnitError(f"unidad logaritmica no soportada: {unit}")


#: notacion RKM: 4K7 = 4,7 k. La 'E' queda fuera a proposito: no es un prefijo
#: SI y "1E3" es notacion cientifica, no "1 exa 3".
_RKM_RE = re.compile(r"^(\d+)\s*(?![eE])([a-zA-ZµμΩω])\s*(\d+)$")
_QTY_RE = re.compile(
    r"^\s*(?P<num>[+-]?(?:\d+(?:[.,]\d+)*|[.,]\d+)(?:[eE][+-]?\d+)?)\s*(?P<unit>[^\d\s].*?)?\s*$"
)


def parse_quantity(text: str, dimension: str, default_unit: str | None = None) -> Quantity:
    """Convierte texto a `Quantity` en la unidad base de `dimension`.

    Acepta "1,5 GHz", "1500MHz", "4K7" (RKM), "-3 dB", "30 dBm" o un numero
    desnudo (se asume `default_unit`, o la unidad base si no se indica).
    """
    if dimension not in DIMENSIONS:
        raise UnitError(f"dimension desconocida: {dimension}")
    dim = DIMENSIONS[dimension]
    raw = str(text).strip()
    if not raw:
        raise UnitError("valor vacio")

    cleaned = raw.replace(" ", " ").replace("Ohms", "ohm").replace("Ohm", "ohm")

    if dim.rkm:
        m = _RKM_RE.match(cleaned.replace(" ", ""))
        if m:
            whole, letter, frac = m.groups()
            factor = _split_prefix(letter + dim.base_unit if letter.lower() not in dim.units else letter, dim)
            value = parse_number(f"{whole}.{frac}") * factor
            return Quantity(value, dimension, raw)

    m = _QTY_RE.match(cleaned)
    if not m:
        raise UnitError(f"no interpretable como {dimension}: {text!r}")
    number = parse_number(m.group("num"))
    unit = (m.group("unit") or "").strip()
    if not unit:
        unit = default_unit or dim.base_unit
    unit = unit.rstrip(".").strip()
    if not unit:
        # Dimensiones adimensionales (numero de vias, VSWR...): el numero ya es el valor.
        return Quantity(number, dimension, raw)

    if unit.lower() in dim.log_units:
        return Quantity(_log_to_base(number, unit, dim), dimension, raw)

    factor = _split_prefix(unit, dim)
    return Quantity(number * factor, dimension, raw)


_SEPARATOR_RE = re.compile(
    r"\s*(?:\.{2,}|…|–|—|~|-{1,2}|/|\bto\b|\bhasta\b|\ba\b|\by\b)\s*", re.IGNORECASE
)
#: numero SIN signo: el signo se decide despues mirando el contexto, porque
#: en "700-2700 MHz" el guion separa y en "-55 a 125" es un valor negativo.
_VALUE_TOKEN_RE = re.compile(
    r"(?P<num>(?:\d+(?:[.,]\d+)*|[.,]\d+)(?:[eE][+-]?\d+)?)\s*(?P<unit>[a-zA-ZΩωµμ°º%\"']+)?"
)
_DC_START_RE = re.compile(r"^\s*(?:dc|cc)\b", re.IGNORECASE)
#: palabras que separan los extremos de un rango y no son unidades
_SEPARATOR_WORDS = {"a", "y", "to", "hasta", "and", "e"}


def _clean_unit(unit: str | None) -> str:
    """Descarta la palabra separadora que el patron puede haber tomado por unidad."""
    text = (unit or "").strip()
    return "" if text.lower() in _SEPARATOR_WORDS else text


@dataclass(frozen=True)
class _ValueToken:
    """Un valor localizado dentro de un texto, con su signo ya resuelto."""

    number: str
    unit: str
    start: int
    end: int


def _scan_values(text: str) -> list[_ValueToken]:
    """Localiza los valores del texto decidiendo si un '-' es signo o separador.

    Un signo pertenece al numero solo si lo que hay antes no es un valor:
    en "700-2700" el guion separa, en "-55 a 125" y en "20 a -5" es negativo.
    """
    tokens: list[_ValueToken] = []
    for match in _VALUE_TOKEN_RE.finditer(text):
        start = match.start()
        sign = ""
        cursor = start - 1
        while cursor >= 0 and text[cursor].isspace():
            cursor -= 1
        if cursor >= 0 and text[cursor] in "+-":
            previous = cursor - 1
            while previous >= 0 and text[previous].isspace():
                previous -= 1
            if previous < 0 or not text[previous].isalnum():
                sign = text[cursor]
                start = cursor
        tokens.append(
            _ValueToken(
                number=f"{sign}{match.group('num')}",
                unit=_clean_unit(match.group("unit")),
                start=start,
                end=match.end(),
            )
        )
    return tokens
_UPPER_BOUND_RE = re.compile(r"^\s*(?:hasta|up\s+to|<=|<|max\.?|maximo|máximo|≤)\s*", re.IGNORECASE)
_LOWER_BOUND_RE = re.compile(r"^\s*(?:desde|from|>=|>|min\.?|minimo|mínimo|≥)\s*", re.IGNORECASE)


def parse_interval(text: str, dimension: str, default_unit: str | None = None) -> Interval:
    """Convierte "DC-18 GHz", "-55 a 125 °C" o "2 GHz" en un `Interval`.

    En vez de partir la cadena por el separador (que se confunde con el signo
    menos), se localizan los valores numericos y se interpretan por posicion.
    """
    raw = str(text).strip()
    if not raw:
        raise UnitError("rango vacio")

    body = raw
    for prefix in ("de ", "from ", "entre ", "between "):
        if body.lower().startswith(prefix):
            body = body[len(prefix) :]

    starts_at_zero = bool(_DC_START_RE.match(body))
    if starts_at_zero:
        # "DC-18 GHz": se quita el "DC" y su separador para no leer "-18".
        body = _SEPARATOR_RE.sub("", _DC_START_RE.sub("", body), count=1)
    only_upper = bool(_UPPER_BOUND_RE.match(body))
    only_lower = bool(_LOWER_BOUND_RE.match(body))
    if only_upper:
        body = _UPPER_BOUND_RE.sub("", body)
    elif only_lower:
        body = _LOWER_BOUND_RE.sub("", body)

    tokens = _scan_values(body)
    if not tokens:
        raise UnitError(f"no interpretable como rango de {dimension}: {text!r}")

    def value_of(token: "_ValueToken", fallback_unit: str | None) -> float:
        return parse_quantity(
            f"{token.number} {token.unit}".strip(),
            dimension,
            token.unit or fallback_unit or default_unit,
        ).value

    last_unit = tokens[-1].unit or default_unit

    if starts_at_zero:
        return Interval(0.0, value_of(tokens[-1], last_unit), dimension, raw)
    if only_upper:
        return Interval(0.0, value_of(tokens[0], last_unit), dimension, raw)
    if only_lower:
        return Interval(value_of(tokens[0], last_unit), math.inf, dimension, raw)

    if len(tokens) == 1:
        point = value_of(tokens[0], last_unit)
        return Interval(point, point, dimension, raw)

    between = body[tokens[0].end : tokens[-1].start]
    if len(tokens) > 2 or not _SEPARATOR_RE.fullmatch(between or " "):
        # Formas raras ("1, 2 y 3 GHz"): se toma el menor y el mayor y se avisa
        # implicitamente conservando el texto original en `raw`.
        values = [value_of(t, last_unit) for t in tokens]
        return Interval(min(values), max(values), dimension, raw)

    low = value_of(tokens[0], last_unit)
    high = value_of(tokens[-1], last_unit)
    if low > high:
        low, high = high, low
    return Interval(low, high, dimension, raw)


def _trailing_unit(text: str) -> str | None:
    m = re.search(r"([a-zA-ZµμΩω%°º\"']+)\s*$", text.strip())
    return m.group(1) if m else None


_SI_STEPS = [
    (1e12, "T"),
    (1e9, "G"),
    (1e6, "M"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "µ"),
    (1e-9, "n"),
    (1e-12, "p"),
]


def format_quantity(q: Quantity, digits: int = 4) -> str:
    """Formatea con prefijo SI legible: 1.5e9 Hz -> '1.5 GHz'."""
    dim = DIMENSIONS[q.dimension]
    value = q.value
    if value == 0 or not math.isfinite(value):
        return f"{value:g} {dim.base_unit}".strip()
    if not dim.prefixable:
        return f"{_trim(value, digits)} {dim.base_unit}".strip()
    magnitude = abs(value)
    for factor, prefix in _SI_STEPS:
        if magnitude >= factor:
            return f"{_trim(value / factor, digits)} {prefix}{dim.base_unit}".strip()
    return f"{_trim(value, digits)} {dim.base_unit}".strip()


#: dos numeros unidos por un separador de rango ("10 to 2700 Ohm", "0.009 to 0.03")
_RANGE_TEXT_RE = re.compile(
    r"\d[\d.,]*\s*[a-zA-ZΩωµμ°º%]{0,8}\s*"
    r"(?:\.{2,}|…|–|—|~|-{1,2}|\bto\b|\bhasta\b|\ba\b|\by\b)"
    r"\s*[+-]?\d",
    re.IGNORECASE,
)


#: un unico numero en notacion cientifica: "3.3E-11" es 33 pF, no un rango
_SCIENTIFIC_RE = re.compile(
    r"^\s*[+-]?\d+(?:[.,]\d+)?\s*[eE]\s*[+-]?\d+\s*[a-zA-ZΩωµμ°º%/]*\s*$"
)


def looks_like_range(text: str) -> bool:
    """True si el texto contiene dos valores unidos por un separador de rango.

    Los catalogos publican a menudo el rango de una serie ("Z 10 to 2700 Ohm")
    en un campo que el esquema declara como numerico; conviene detectarlo en
    lugar de descartar el dato.

    La notacion cientifica se descarta antes: en "3.3E-11" el guion es el signo
    del exponente, no un separador de rango.
    """
    raw = str(text or "")
    if _SCIENTIFIC_RE.match(raw):
        return False
    return bool(_RANGE_TEXT_RE.search(raw))


def _trim(value: float, digits: int) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"
