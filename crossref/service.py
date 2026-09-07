"""Capa de servicio: une esquema, catalogo y motor en una sola llamada.

Es lo que usan la API, la interfaz web y la linea de comandos, para que las
tres den exactamente el mismo resultado.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .extract import build_query, describe_query
from .ingest import IngestReport, field_coverage, ingest_source
from .matching import rank, summarize
from .models import ComponentQuery, MatchResult, Verdict
from .schema import Registry, load_registry
from .sources.base import load_source
from .store import CatalogStore

__all__ = ["CrossRefService", "DEFAULT_FAMILIES_DIR", "DEFAULT_DB_PATH"]

DEFAULT_FAMILIES_DIR = Path("config/families")
DEFAULT_DB_PATH = Path("data/catalog.db")


class CrossRefService:
    """Punto unico de entrada al sistema."""

    def __init__(
        self,
        families_dir: str | Path = DEFAULT_FAMILIES_DIR,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self.families_dir = Path(families_dir)
        self.registry: Registry = load_registry(self.families_dir)
        self.store = CatalogStore(db_path)

    def reload_families(self) -> None:
        """Recarga los YAML sin reiniciar el servicio (las reglas se tocan a menudo)."""
        self.registry = load_registry(self.families_dir)

    # ------------------------------------------------------------------ consulta

    def parse(
        self,
        *,
        text: str | None = None,
        family: str | None = None,
        fields: dict[str, str] | None = None,
        part_number: str | None = None,
        manufacturer: str | None = None,
    ) -> ComponentQuery:
        return build_query(
            self.registry,
            text=text,
            family_id=family,
            fields=fields,
            part_number=part_number,
            manufacturer=manufacturer,
        )

    def crossref(
        self,
        *,
        text: str | None = None,
        family: str | None = None,
        fields: dict[str, str] | None = None,
        part_number: str | None = None,
        manufacturer: str | None = None,
        limit: int = 10,
        include_rejected: bool = False,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Busca la equivalencia y devuelve el resultado ya explicado."""
        query = self.parse(
            text=text, family=family, fields=fields,
            part_number=part_number, manufacturer=manufacturer,
        )
        family_spec = self.registry.get(query.family) or self.registry["generic"]

        candidates = self.store.candidates(query.family, text=text or query.description)
        results = rank(
            self.registry,
            query,
            candidates,
            limit=limit if not include_rejected else limit * 3,
            include_rejected=True,
        )
        accepted = [r for r in results if r.verdict is not Verdict.REJECTED][:limit]
        if strict:
            accepted = [r for r in accepted if r.verdict is Verdict.EQUIVALENT]
        rejected = [r for r in results if r.verdict is Verdict.REJECTED][:limit] if include_rejected else []

        return {
            "query": _query_to_dict(query, family_spec),
            "family": {
                "id": family_spec.id,
                "label": family_spec.label,
                "confidence": round(query.family_confidence, 3),
                "candidates": [
                    {"id": fid, "label": self.registry[fid].label, "score": score}
                    for fid, score in query.family_candidates
                ],
                "required_attributes": [
                    {"id": spec.id, "label": spec.label, "rule": spec.rule.describe()}
                    for spec in family_spec.required_attributes
                ],
            },
            "counts": summarize(results),
            "catalog_candidates": len(candidates),
            "results": [_result_to_dict(r) for r in accepted],
            "rejected": [_result_to_dict(r) for r in rejected],
            "warnings": query.warnings,
        }

    def batch(self, rows: Iterable[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
        """Procesa una lista de peticiones (una RFQ entera, por ejemplo)."""
        output = []
        for index, row in enumerate(rows, start=1):
            row = dict(row)
            fields = row.pop("fields", None) or {}
            response = self.crossref(
                text=row.pop("text", None),
                family=row.pop("family", None),
                part_number=row.pop("part_number", None),
                manufacturer=row.pop("manufacturer", None),
                fields=fields,
                limit=limit,
            )
            best = response["results"][0] if response["results"] else None
            output.append(
                {
                    "row": row.get("row", index),
                    "input": row.get("text") or row.get("part_number") or "",
                    "family": response["family"]["id"],
                    "status": best["verdict"] if best else Verdict.REVIEW.value,
                    "catalog_reference": best["reference"] if best else None,
                    "catalog_url": best["url"] if best else None,
                    "score": best["score"] if best else 0.0,
                    "reason": "; ".join(best["reasons"]) if best else "sin candidatos en el catalogo",
                    "alternatives": [r["reference"] for r in response["results"][1:]],
                    "response": response,
                }
            )
        return output

    # ------------------------------------------------------------------ catalogo

    def sync(self, source_path: str | Path, limit: int | None = None,
             deactivate_missing: bool = False) -> IngestReport:
        source = load_source(source_path)
        return ingest_source(
            self.registry, self.store, source, limit=limit, deactivate_missing=deactivate_missing
        )

    def stats(self) -> dict[str, Any]:
        data = self.store.stats()
        data["families"] = [
            {
                "id": family.id,
                "label": family.label,
                "attributes": len(family.attributes),
                "required": [spec.id for spec in family.required_attributes],
            }
            for family in self.registry.families.values()
        ]
        return data

    def coverage(self, family_id: str) -> dict[str, Any]:
        return field_coverage(self.registry, self.store, family_id)

    def family_detail(self, family_id: str) -> dict[str, Any]:
        family = self.registry[family_id]
        return {
            "id": family.id,
            "label": family.label,
            "aliases": family.aliases,
            "attributes": [
                {
                    "id": spec.id,
                    "label": spec.label,
                    "type": spec.type,
                    "unit": spec.unit,
                    "dimension": spec.dimension,
                    "required": spec.required,
                    "weight": spec.weight,
                    "rule": spec.rule.describe(),
                    "aliases": spec.aliases,
                    "values": spec.values.known(),
                }
                for spec in family.attributes.values()
            ],
        }


# --------------------------------------------------------------------------
# Serializacion para la API
# --------------------------------------------------------------------------


def _query_to_dict(query: ComponentQuery, family_spec) -> dict[str, Any]:
    return {
        "raw_text": query.raw_text,
        "part_number": query.part_number,
        "manufacturer": query.manufacturer,
        "family": query.family,
        "understood": describe_query(query, family_spec),
        "unparsed": query.unparsed,
    }


def _result_to_dict(result: MatchResult) -> dict[str, Any]:
    item = result.item
    return {
        "id": item.id,
        "reference": item.reference,
        "manufacturer": item.manufacturer,
        "description": item.description,
        "url": item.url,
        "datasheet_url": item.datasheet_url,
        "family": item.family,
        "verdict": result.verdict.value,
        "score": result.score,
        "exact_reference": result.pn_exact,
        "matched_fields": result.matched_fields,
        "differing_fields": result.differing_fields,
        "missing_fields": result.missing_fields,
        "reasons": result.reasons,
        "comparisons": [asdict(c) | {"status": c.status.value} for c in result.comparisons],
        "specs": item.specs,
        "source": item.source,
        "fetched_at": item.fetched_at.isoformat(),
    }
