"""Indice local del catalogo en SQLite.

Guarda la ficha tal y como llega (`specs`) y su version normalizada
(`attributes`), junto con la fuente y la fecha, para que cualquier resultado
pueda justificar de donde sale el dato.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .models import AttributeValue, CatalogItem, utcnow
from .grupos import grupo_de, raices
from .normalize import normalize_pn, normalize_text

__all__ = ["CatalogStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id             TEXT PRIMARY KEY,
    reference      TEXT NOT NULL,
    reference_norm TEXT NOT NULL,
    family         TEXT,
    manufacturer   TEXT,
    description    TEXT,
    url            TEXT,
    datasheet_url  TEXT,
    category_path  TEXT NOT NULL DEFAULT '[]',
    specs          TEXT NOT NULL DEFAULT '{}',
    attributes     TEXT NOT NULL DEFAULT '{}',
    source         TEXT NOT NULL DEFAULT 'manual',
    fetched_at     TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    extra          TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_items_family ON items(family);
CREATE INDEX IF NOT EXISTS idx_items_refnorm ON items(reference_norm);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    id UNINDEXED,
    haystack,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS sync_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    items      INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'running',
    detail     TEXT
);
"""


class CatalogStore:
    """Acceso al indice local. Seguro para uso concurrente basico (WAL)."""

    def __init__(self, path: str | Path = "data/catalog.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._conn:
            self._conn.executescript(_SCHEMA)

    # ---------------------------------------------------------------- escritura

    def upsert(self, items: Iterable[CatalogItem]) -> int:
        """Inserta o actualiza fichas. Devuelve cuantas se han escrito."""
        rows = [_to_row(item) for item in items]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO items (id, reference, reference_norm, family, manufacturer,
                                   description, url, datasheet_url, category_path, specs,
                                   attributes, source, fetched_at, active, extra)
                VALUES (:id, :reference, :reference_norm, :family, :manufacturer,
                        :description, :url, :datasheet_url, :category_path, :specs,
                        :attributes, :source, :fetched_at, :active, :extra)
                ON CONFLICT(id) DO UPDATE SET
                    reference=excluded.reference,
                    reference_norm=excluded.reference_norm,
                    family=excluded.family,
                    manufacturer=excluded.manufacturer,
                    description=excluded.description,
                    url=excluded.url,
                    datasheet_url=excluded.datasheet_url,
                    category_path=excluded.category_path,
                    specs=excluded.specs,
                    attributes=excluded.attributes,
                    source=excluded.source,
                    fetched_at=excluded.fetched_at,
                    active=excluded.active,
                    extra=excluded.extra
                """,
                rows,
            )
            ids = [row["id"] for row in rows]
            self._conn.executemany("DELETE FROM items_fts WHERE id = ?", [(i,) for i in ids])
            self._conn.executemany(
                "INSERT INTO items_fts (id, haystack) VALUES (?, ?)",
                [(row["id"], row["_haystack"]) for row in rows],
            )
        return len(rows)

    def deactivate_missing(self, source: str, seen_ids: Iterable[str]) -> int:
        """Marca como inactivas las fichas de `source` que ya no vienen en el volcado."""
        seen = list(seen_ids)
        placeholders = ",".join("?" * len(seen)) or "''"
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE items SET active = 0 WHERE source = ? AND active = 1 AND id NOT IN ({placeholders})",
                [source, *seen],
            )
        return cursor.rowcount

    def clear(self, source: str | None = None) -> int:
        with self._conn:
            if source:
                cursor = self._conn.execute("DELETE FROM items WHERE source = ?", (source,))
                self._conn.execute(
                    "DELETE FROM items_fts WHERE id NOT IN (SELECT id FROM items)"
                )
            else:
                cursor = self._conn.execute("DELETE FROM items")
                self._conn.execute("DELETE FROM items_fts")
        return cursor.rowcount

    def start_sync(self, source: str) -> int:
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO sync_log (source, started_at) VALUES (?, ?)",
                (source, utcnow().isoformat()),
            )
        return int(cursor.lastrowid)

    def finish_sync(self, sync_id: int, items: int, status: str = "ok", detail: str | None = None) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE sync_log SET ended_at = ?, items = ?, status = ?, detail = ? WHERE id = ?",
                (utcnow().isoformat(), items, status, detail, sync_id),
            )

    # ----------------------------------------------------------------- lectura

    def get(self, item_id: str) -> CatalogItem | None:
        row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _from_row(row) if row else None

    def by_reference(self, reference: str) -> list[CatalogItem]:
        rows = self._conn.execute(
            "SELECT * FROM items WHERE reference_norm = ? AND active = 1", (normalize_pn(reference),)
        ).fetchall()
        return [_from_row(row) for row in rows]

    def iter_items(
        self,
        family: str | None = None,
        active_only: bool = True,
        group: str | None = None,
    ) -> Iterator[CatalogItem]:
        sql = "SELECT * FROM items WHERE 1=1"
        params: list[object] = []
        if family:
            sql += " AND family = ?"
            params.append(family)
        if group:
            # category_path se guarda como JSON: la raiz es el primer elemento,
            # asi que basta con mirar el principio de la cadena.
            roots = raices(group)
            if roots:
                sql += " AND (" + " OR ".join(["category_path LIKE ?"] * len(roots)) + ")"
                params.extend(f'["{r}"%' for r in roots)
        if active_only:
            sql += " AND active = 1"
        with closing(self._conn.execute(sql, params)) as cursor:
            for row in cursor:
                yield _from_row(row)

    def candidates(
        self,
        family: str | None,
        text: str | None = None,
        limit: int = 5000,
        group: str | None = None,
    ) -> list[CatalogItem]:
        """Preselecciona fichas a evaluar: por familia y, si hace falta, por texto.

        `group` acota a un bloque del catalogo (pasivos, electromecanica...).
        Se aplica siempre, tambien sobre lo que devuelve la busqueda por texto:
        si se pide electromecanica, una ferrita no puede colarse.
        """
        def del_grupo(items: list[CatalogItem]) -> list[CatalogItem]:
            if not group:
                return items
            return [i for i in items if grupo_de(i.category_path) == group]

        if family and family != "generic":
            items = del_grupo(list(self.iter_items(family=family, group=group)))
            if items:
                return items[:limit]
        if text:
            hits = del_grupo(self.search_text(text, limit=limit))
            if hits:
                return hits
        return list(self.iter_items(group=group))[:limit]

    def search_text(self, text: str, limit: int = 100) -> list[CatalogItem]:
        """Busqueda libre por FTS; tolera consultas con sintaxis rara."""
        terms = [t for t in normalize_text(text).split() if len(t) > 1]
        if not terms:
            return []
        expression = " OR ".join(f'"{t}"' for t in terms[:20])
        try:
            rows = self._conn.execute(
                """
                SELECT items.* FROM items_fts
                JOIN items ON items.id = items_fts.id
                WHERE items_fts MATCH ? AND items.active = 1
                ORDER BY bm25(items_fts) LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [_from_row(row) for row in rows]

    def stats(self) -> dict[str, object]:
        total = self._conn.execute("SELECT COUNT(*) FROM items WHERE active = 1").fetchone()[0]
        by_family = {
            row["family"] or "sin clasificar": row["n"]
            for row in self._conn.execute(
                "SELECT family, COUNT(*) AS n FROM items WHERE active = 1 GROUP BY family ORDER BY n DESC"
            )
        }
        by_source = {
            row["source"]: {"items": row["n"], "last_fetch": row["last_fetch"]}
            for row in self._conn.execute(
                "SELECT source, COUNT(*) AS n, MAX(fetched_at) AS last_fetch "
                "FROM items WHERE active = 1 GROUP BY source"
            )
        }
        last_sync = self._conn.execute(
            "SELECT source, started_at, ended_at, items, status, detail FROM sync_log ORDER BY id DESC LIMIT 5"
        ).fetchall()
        by_group: dict[str, int] = {}
        for row in self._conn.execute(
            "SELECT category_path, COUNT(*) AS n FROM items WHERE active = 1 GROUP BY category_path"
        ):
            try:
                camino = json.loads(row["category_path"] or "[]")
            except (TypeError, ValueError):
                camino = []
            gid = grupo_de(camino) or "sin grupo"
            by_group[gid] = by_group.get(gid, 0) + row["n"]
        return {
            "items": total,
            "by_family": by_family,
            "by_group": by_group,
            "by_source": by_source,
            "recent_syncs": [dict(row) for row in last_sync],
        }

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------
# (De)serializacion
# --------------------------------------------------------------------------


def _to_row(item: CatalogItem) -> dict[str, object]:
    haystack = " ".join(
        filter(
            None,
            [
                item.reference,
                normalize_pn(item.reference),
                item.manufacturer or "",
                item.description or "",
                " ".join(item.category_path),
                " ".join(f"{k} {v}" for k, v in item.specs.items()),
            ],
        )
    )
    return {
        "id": item.id,
        "reference": item.reference,
        "reference_norm": normalize_pn(item.reference),
        "family": item.family,
        "manufacturer": item.manufacturer,
        "description": item.description,
        "url": item.url,
        "datasheet_url": item.datasheet_url,
        "category_path": json.dumps(item.category_path, ensure_ascii=False),
        "specs": json.dumps(item.specs, ensure_ascii=False),
        "attributes": json.dumps(
            {k: asdict(v) for k, v in item.attributes.items()}, ensure_ascii=False
        ),
        "source": item.source,
        "fetched_at": item.fetched_at.isoformat(),
        "active": 1 if item.active else 0,
        "extra": json.dumps(item.extra, ensure_ascii=False, default=str),
        "_haystack": normalize_text(haystack),
    }


def _from_row(row: sqlite3.Row) -> CatalogItem:
    attributes = {
        key: AttributeValue(**_normalize_attribute_payload(payload))
        for key, payload in json.loads(row["attributes"]).items()
    }
    return CatalogItem(
        id=row["id"],
        reference=row["reference"],
        family=row["family"],
        manufacturer=row["manufacturer"],
        description=row["description"],
        url=row["url"],
        datasheet_url=row["datasheet_url"],
        category_path=json.loads(row["category_path"]),
        specs=json.loads(row["specs"]),
        attributes=attributes,
        source=row["source"],
        fetched_at=_parse_dt(row["fetched_at"]),
        active=bool(row["active"]),
        extra=json.loads(row["extra"]),
    )


def _normalize_attribute_payload(payload: dict) -> dict:
    data = dict(payload)
    if isinstance(data.get("interval"), list):
        data["interval"] = tuple(data["interval"])
    return data


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):  # pragma: no cover - datos externos raros
        return utcnow()
