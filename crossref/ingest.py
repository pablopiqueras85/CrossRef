"""Ingesta: convierte fichas en bruto en referencias normalizadas del catalogo.

Ademas del alta en el indice, produce un informe de calidad: que campos del
catalogo no encajan en ningun atributo y que fichas no se han podido
clasificar. Ese informe es la guia para ir ampliando los YAML de familias.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .extract import map_fields
from .models import CatalogItem, utcnow
from .normalize import normalize_text
from .schema import Registry
from .sources.base import CatalogSource, RawProduct
from .store import CatalogStore

__all__ = ["IngestReport", "ingest_source", "to_catalog_item", "resolve_family"]


@dataclass
class IngestReport:
    """Resumen de una sincronizacion, pensado para leerlo y actuar."""

    source: str
    #: fichas procesadas (una referencia listada en dos categorias cuenta dos veces)
    items: int = 0
    #: referencias distintas que quedan en el indice
    unique_items: int = 0
    by_family: Counter = field(default_factory=Counter)
    unclassified: list[str] = field(default_factory=list)
    #: campo del catalogo -> (veces que aparece, ejemplos de valor)
    unmapped_fields: dict[str, tuple[int, list[str]]] = field(default_factory=dict)
    incomplete: list[tuple[str, list[str]]] = field(default_factory=list)
    #: atributo -> (veces, unidad asumida, ejemplo). Un valor sin unidad se
    #: interpreta con la unidad por defecto del atributo: si esa unidad no es
    #: la que usa el catalogo, el error es silencioso y grave.
    assumed_units: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "items": self.items,
            "unique_items": self.unique_items,
            "by_family": dict(self.by_family),
            "unclassified": self.unclassified[:50],
            "unclassified_total": len(self.unclassified),
            "unmapped_fields": [
                {"field": name, "count": count, "examples": examples}
                for name, (count, examples) in sorted(
                    self.unmapped_fields.items(), key=lambda kv: -kv[1][0]
                )[:40]
            ],
            "incomplete": [
                {"reference": ref, "missing": missing} for ref, missing in self.incomplete[:50]
            ],
            "incomplete_total": len(self.incomplete),
            "assumed_units": [
                {"attribute": a, "count": c, "unit": u, "example": e}
                for a, (c, u, e) in sorted(self.assumed_units.items(), key=lambda kv: -kv[1][0])
            ],
            "errors": self.errors[:20],
        }

    def summary_lines(self) -> list[str]:
        if self.unique_items and self.unique_items != self.items:
            lines = [
                f"Fuente '{self.source}': {self.unique_items} referencias distintas "
                f"({self.items} fichas procesadas; el resto son referencias listadas "
                "en mas de una categoria)."
            ]
        else:
            lines = [f"Fuente '{self.source}': {self.items} referencias indexadas."]
        for family, count in self.by_family.most_common():
            lines.append(f"  - {family}: {count}")
        if self.unclassified:
            lines.append(
                f"  ! {len(self.unclassified)} fichas sin familia "
                f"(ejemplos: {', '.join(self.unclassified[:5])})"
            )
        if self.unmapped_fields:
            top = sorted(self.unmapped_fields.items(), key=lambda kv: -kv[1][0])[:10]
            lines.append("  ! campos del catalogo sin mapear (anadelos como alias en el YAML):")
            for name, (count, examples) in top:
                lines.append(f"      {name} (x{count}) p. ej. {examples[0] if examples else ''}")
        if self.assumed_units:
            lines.append("  ! valores sin unidad en la ficha: se ha asumido la del esquema")
            for attr, (count, unit, example) in sorted(
                self.assumed_units.items(), key=lambda kv: -kv[1][0]
            )[:8]:
                lines.append(f"      {attr} (x{count}) '{example}' -> {unit}. Confirma la unidad.")
        if self.incomplete:
            lines.append(
                f"  ! {len(self.incomplete)} fichas sin todos los campos obligatorios de su familia"
            )
        for error in self.errors[:5]:
            lines.append(f"  ! {error}")
        return lines


def resolve_family(registry: Registry, product: RawProduct) -> str | None:
    """Decide a que familia pertenece una ficha del catalogo."""
    hint = (product.family_hint or "").strip()
    if hint:
        if hint in registry:
            return hint
        detected = registry.detect(hint, top=1)
        if detected and detected[0][1] >= 0.5:
            return detected[0][0]

    from_category = registry.detect_from_category(product.category_path)
    if from_category:
        return from_category

    text = " ".join(filter(None, [product.description or "", product.reference]))
    detected = registry.detect(text, top=2)
    if detected and detected[0][1] >= 0.6:
        return detected[0][0]
    return None


def to_catalog_item(
    registry: Registry,
    product: RawProduct,
    source_id: str,
    report: IngestReport | None = None,
) -> CatalogItem:
    """Normaliza una ficha en bruto usando el esquema de su familia."""
    family_id = resolve_family(registry, product)
    family = registry.get(family_id) or registry["generic"]

    attributes, unmapped = map_fields(family, product.specs)
    if report is not None:
        for name, value in unmapped.items():
            count, examples = report.unmapped_fields.get(name, (0, []))
            if len(examples) < 3 and value:
                examples = [*examples, value]
            report.unmapped_fields[name] = (count + 1, examples)

    item = CatalogItem(
        id=product.stable_id(source_id),
        reference=product.reference,
        family=family_id,
        manufacturer=product.manufacturer,
        description=product.description,
        url=product.url,
        datasheet_url=product.datasheet_url,
        category_path=product.category_path,
        specs=product.specs,
        attributes=attributes,
        source=source_id,
        fetched_at=utcnow(),
        extra=product.extra,
    )

    if report is not None:
        for attr_id, value in attributes.items():
            spec = family.attributes.get(attr_id)
            if spec is None or not spec.unit or value.is_empty():
                continue
            # '%', '°' y 'Ω' son unidades aunque no sean letras.
            tiene_unidad = any(c.isalpha() or c in "%°ºΩω" for c in value.raw)
            if value.kind in ("number", "range") and not tiene_unidad:
                count, unit, example = report.assumed_units.get(attr_id, (0, spec.unit, value.raw))
                report.assumed_units[attr_id] = (count + 1, spec.unit, example)
        if family_id is None:
            report.unclassified.append(product.reference)
        else:
            report.by_family[family_id] += 1
            missing = [
                spec.label
                for spec in family.required_attributes
                if spec.id not in attributes or attributes[spec.id].is_empty()
            ]
            if missing:
                report.incomplete.append((product.reference, missing))
    return item


def ingest_source(
    registry: Registry,
    store: CatalogStore,
    source: CatalogSource,
    *,
    limit: int | None = None,
    batch_size: int = 500,
    deactivate_missing: bool = False,
) -> IngestReport:
    """Descarga la fuente completa y la deja indexada, con informe de calidad."""
    source_id = getattr(source, "id", "desconocida")
    report = IngestReport(source=source_id)
    sync_id = store.start_sync(source_id)
    seen: list[str] = []
    batch: list[CatalogItem] = []

    try:
        for product in source.fetch(limit=limit):
            item = to_catalog_item(registry, product, source_id, report)
            batch.append(item)
            seen.append(item.id)
            if len(batch) >= batch_size:
                report.items += store.upsert(batch)
                batch = []
        if batch:
            report.items += store.upsert(batch)
        report.unique_items = len(set(seen))
        if deactivate_missing:
            store.deactivate_missing(source_id, seen)
    except Exception as exc:  # se registra y se propaga el motivo al informe
        report.errors.append(f"{type(exc).__name__}: {exc}")
        store.finish_sync(sync_id, report.items, status="error", detail=str(exc)[:500])
        raise
    store.finish_sync(sync_id, report.items, status="ok")
    return report


def ingest_products(
    registry: Registry,
    store: CatalogStore,
    products: Iterable[RawProduct],
    source_id: str = "manual",
) -> IngestReport:
    """Igual que `ingest_source` pero con fichas ya obtenidas (util en pruebas)."""
    report = IngestReport(source=source_id)
    items = [to_catalog_item(registry, product, source_id, report) for product in products]
    report.items = store.upsert(items)
    report.unique_items = len({item.id for item in items})
    return report


def field_coverage(registry: Registry, store: CatalogStore, family_id: str) -> dict[str, dict]:
    """Cuanta informacion publica el catalogo por atributo de una familia.

    Sirve para saber si una familia puede resolverse 1:1 o si el catalogo
    todavia no tiene los datos necesarios.
    """
    family = registry[family_id]
    totals: dict[str, int] = defaultdict(int)
    count = 0
    for item in store.iter_items(family=family_id):
        count += 1
        for attr_id, value in item.attributes.items():
            if not value.is_empty():
                totals[attr_id] += 1
    return {
        spec.id: {
            "label": spec.label,
            "required": spec.required,
            "items_with_value": totals.get(spec.id, 0),
            "coverage": round(totals.get(spec.id, 0) / count, 3) if count else 0.0,
        }
        for spec in family.attributes.values()
    }
