"""Normalizacion de texto: nombres de campo, valores enum y part numbers.

Todo lo que entra al motor de reglas pasa antes por aqui, de modo que
"SMA Hembra", "sma-female" y "SMA (F)" acaben siendo el mismo token.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "strip_accents",
    "normalize_text",
    "slug",
    "normalize_pn",
    "tokens",
    "SynonymTable",
    "similarity",
]

_WS_RE = re.compile(r"\s+")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {ord("‘"): "'", ord("’"): "'", ord("“"): '"', ord("”"): '"'}


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_text(text: str) -> str:
    """Minusculas, sin acentos, guiones y comillas unificados, sin espacios dobles."""
    if text is None:
        return ""
    out = str(text).translate(_DASHES).translate(_QUOTES)
    out = strip_accents(out).lower()
    out = out.replace("_", " ").replace("/", " / ")
    out = _WS_RE.sub(" ", out).strip()
    return out


#: en las tablas de datos el simbolo ES el nombre del parametro: "λPeak" y
#: "Φe" no son decoracion. Al quitar todo lo que no fuera a-z quedaban en
#: 'peak' y 'e', y dos columnas distintas podian acabar con la misma clave.
_GRIEGO = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta", "Θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "Λ": "lambda", "μ": "u", "µ": "u",
    "ν": "nu", "ξ": "xi", "π": "pi", "Π": "pi", "ρ": "rho", "σ": "sigma",
    "Σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi", "Φ": "phi",
    "χ": "chi", "ψ": "psi", "Ψ": "psi", "ω": "omega", "Ω": "ohm",
}


def slug(text: str) -> str:
    """Clave estable para comparar nombres de campo: 'Frecuencia máx.' -> 'frecuencia max'."""
    out = str(text or "")
    for simbolo, nombre in _GRIEGO.items():
        if simbolo in out:
            out = out.replace(simbolo, f" {nombre} ")
    out = normalize_text(out)
    out = re.sub(r"[^a-z0-9]+", " ", out)
    return _WS_RE.sub(" ", out).strip()


def normalize_pn(reference: str) -> str:
    """Part number comparable: sin espacios, guiones ni puntos, en mayusculas."""
    out = strip_accents(str(reference or "")).upper()
    return re.sub(r"[^A-Z0-9]+", "", out)


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9.]+", normalize_text(text)) if t]


class SynonymTable:
    """Mapa alias -> valor canonico, tolerante a formato.

    Se construye desde YAML:
        sma hembra: [sma-f, sma female, sma (f), sma h]
    """

    def __init__(self, mapping: dict[str, list[str]] | None = None) -> None:
        self._index: dict[str, str] = {}
        self._aliases: dict[str, list[str]] = {}
        self._canonical: list[str] = []
        for canonical, aliases in (mapping or {}).items():
            self.add(canonical, aliases)

    def add(self, canonical: str, aliases: list[str] | None = None) -> None:
        if canonical not in self._canonical:
            self._canonical.append(canonical)
        stored = self._aliases.setdefault(canonical, [])
        for alias in [canonical, *(aliases or [])]:
            self._index[_key(alias)] = canonical
            if alias not in stored:
                stored.append(str(alias))

    def canonical(self, value: str) -> str | None:
        """Devuelve el valor canonico, o None si el valor no esta en la tabla."""
        if value is None:
            return None
        return self._index.get(_key(value))

    def resolve(self, value: str) -> str:
        """Como `canonical`, pero devuelve el texto normalizado si no hay alias."""
        return self.canonical(value) or normalize_text(value)

    def known(self) -> list[str]:
        return list(self._canonical)

    def aliases_of(self, canonical: str) -> list[str]:
        """Alias tal y como se escribieron en el YAML, del mas largo al mas corto."""
        return sorted(self._aliases.get(canonical, [canonical]), key=len, reverse=True)

    def __bool__(self) -> bool:
        return bool(self._index)


def _key(value: str) -> str:
    """Clave de busqueda muy tolerante: sin acentos, sin separadores, minusculas."""
    return re.sub(r"[^a-z0-9]+", "", strip_accents(str(value)).lower())


def find_word(text: str, needle: str) -> int | None:
    """Posicion de `needle` en `text` exigiendo que sea palabra completa.

    Sin esta frontera, "screw" encaja dentro de "screwless" y un bornero sin
    tornillo acaba clasificado como de tornillo, que es justo lo contrario.
    La frontera solo se exige si el extremo del alias es alfanumerico: asi
    "0805" o "m12" siguen siendo palabra y un alias que empieza por simbolo no
    pide nada raro delante.
    """
    if not text or not needle:
        return None
    izquierda = r"(?<![0-9a-z])" if needle[:1].isalnum() else ""
    # El plural cuenta como la misma palabra: el catalogo titula sus series
    # "Thick Film Resistors" y "Aluminum Electrolytic Capacitors", en plural,
    # y el alias esta en singular. Sin esto, 1.500 fichas caian en la familia
    # equivocada. "screwless" sigue sin encajar en "screw": 'less' no es
    # plural.
    derecha = r"(?:e?s)?(?![0-9a-z])" if needle[-1:].isalpha() else (
        r"(?![0-9a-z])" if needle[-1:].isdigit() else ""
    )
    match = re.search(izquierda + re.escape(needle) + derecha, text)
    return match.start() if match else None


def similarity(a: str, b: str) -> float:
    """Similitud 0..1 entre dos textos (Dice sobre trigramas + bonus por igualdad)."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga, gb = _trigrams(na), _trigrams(nb)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    return 2 * inter / (len(ga) + len(gb))


def _trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}
