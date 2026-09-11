"""Grandes bloques del catalogo, para acotar la busqueda.

Un comercial que atiende conectores no quiere que una ferrita compita con un
bornero. El grupo se deduce de la categoria raiz con la que se indexo la
ficha, asi que no hay que mantener una lista de familias en paralelo: si
manana aparece una familia nueva bajo "Electromechanic Components", entra
sola.
"""

from __future__ import annotations

__all__ = ["GRUPOS", "raices", "etiqueta", "grupo_de", "ids"]

#: id -> (etiqueta visible, categorias raiz del catalogo que lo componen)
GRUPOS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pasivos": (
        "Pasivos",
        # Automocion son los mismos componentes con cualificacion AEC-Q.
        ("Passive Components", "EMC Components", "Automotive"),
    ),
    "electromecanica": (
        "Electromecanica",
        ("Electromechanic Components",),
    ),
    "optoelectronica": (
        "Optoelectronica",
        ("Optoelectronic Components",),
    ),
    "otros": (
        "Otros",
        ("Active Components", "Thermal Management"),
    ),
}


def ids() -> list[str]:
    return list(GRUPOS)


def etiqueta(grupo: str) -> str:
    return GRUPOS[grupo][0] if grupo in GRUPOS else grupo


def raices(grupo: str | None) -> tuple[str, ...]:
    """Categorias raiz de un grupo. Vacio si no se filtra."""
    if not grupo:
        return ()
    if grupo not in GRUPOS:
        raise KeyError(f"grupo desconocido: {grupo}")
    return GRUPOS[grupo][1]


def grupo_de(category_path: list[str] | None) -> str | None:
    """A que grupo pertenece una ficha, por su categoria raiz."""
    if not category_path:
        return None
    raiz = str(category_path[0])
    for gid, (_, roots) in GRUPOS.items():
        if raiz in roots:
            return gid
    return None
