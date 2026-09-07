"""API HTTP de CrossRef (FastAPI) y servidor de la interfaz web."""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Any, Sequence

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .schema import SchemaError
from .service import DEFAULT_DB_PATH, DEFAULT_FAMILIES_DIR, CrossRefService

__all__ = ["create_app", "app"]

WEB_DIR = Path(__file__).parent / "web"


class CrossRefRequest(BaseModel):
    """Peticion de equivalencia: texto libre, campos del formulario, o ambos."""

    text: str | None = Field(None, description="Peticion tal y como llega del cliente")
    family: str | None = Field(None, description="Familia; si se omite, se detecta")
    fields: dict[str, str] = Field(default_factory=dict, description="Campos ya separados")
    part_number: str | None = None
    manufacturer: str | None = None
    limit: int = Field(10, ge=1, le=100)
    include_rejected: bool = Field(False, description="Incluir descartados y su motivo")
    strict: bool = Field(False, description="Devolver solo equivalencias 1:1")


class BatchRequest(BaseModel):
    rows: list[CrossRefRequest]
    limit: int = Field(3, ge=1, le=20)


class SyncRequest(BaseModel):
    source: str = Field(..., description="Ruta al YAML de configuracion de la fuente")
    limit: int | None = Field(None, description="Maximo de fichas (util para probar)")
    deactivate_missing: bool = Field(
        False, description="Marcar como inactivas las referencias que ya no aparezcan"
    )


def create_app(
    families_dir: str | Path | Sequence[str | Path] | None = None,
    db_path: str | Path | None = None,
) -> FastAPI:
    """Crea la aplicacion.

    Sin argumentos toma la configuracion de las variables de entorno
    CROSSREF_FAMILIES y CROSSREF_DB, para que `uvicorn crossref.api:app`
    (con o sin --reload) use la misma que la linea de comandos.
    """
    families_dir = families_dir or os.environ.get("CROSSREF_FAMILIES") or DEFAULT_FAMILIES_DIR
    db_path = db_path or os.environ.get("CROSSREF_DB") or DEFAULT_DB_PATH
    service = CrossRefService(families_dir, db_path)
    admin_token = os.environ.get("CROSSREF_ADMIN_TOKEN")

    app = FastAPI(
        title="CrossRef",
        version="0.1.0",
        description=(
            "Encuentra la equivalencia 1:1 de un componente en el catalogo propio, "
            "o la alternativa mas cercana, explicando siempre por que."
        ),
    )

    def require_admin(x_admin_token: str | None = Header(None)) -> None:
        """Protege las operaciones que modifican el catalogo."""
        if admin_token and x_admin_token != admin_token:
            raise HTTPException(status_code=401, detail="token de administracion invalido")

    # ------------------------------------------------------------- consultas

    @app.post("/api/v1/crossref", summary="Buscar equivalencia")
    def crossref(request: CrossRefRequest) -> dict[str, Any]:
        if not request.text and not request.fields and not request.part_number:
            raise HTTPException(status_code=422, detail="indica texto, campos o una referencia")
        return service.crossref(
            text=request.text,
            family=request.family,
            fields=request.fields,
            part_number=request.part_number,
            manufacturer=request.manufacturer,
            limit=request.limit,
            include_rejected=request.include_rejected,
            strict=request.strict,
        )

    @app.post("/api/v1/parse", summary="Ver como se interpreta la peticion")
    def parse(request: CrossRefRequest) -> dict[str, Any]:
        query = service.parse(
            text=request.text,
            family=request.family,
            fields=request.fields,
            part_number=request.part_number,
            manufacturer=request.manufacturer,
        )
        family = service.registry.get(query.family)
        from .extract import describe_query

        return {
            "family": query.family,
            "family_confidence": round(query.family_confidence, 3),
            "family_candidates": query.family_candidates,
            "part_number": query.part_number,
            "manufacturer": query.manufacturer,
            "understood": describe_query(query, family),
            "unparsed": query.unparsed,
            "warnings": query.warnings,
        }

    @app.post("/api/v1/crossref/batch", summary="Procesar una lista de peticiones")
    def batch(request: BatchRequest) -> dict[str, Any]:
        rows = [row.model_dump() for row in request.rows]
        results = service.batch(rows, limit=request.limit)
        for result in results:
            result.pop("response", None)
        return {"rows": len(results), "results": results}

    @app.post("/api/v1/crossref/batch/csv", summary="Procesar un CSV de peticiones")
    async def batch_csv(
        file: UploadFile = File(...),
        column: str = Query("peticion", description="Columna con la peticion"),
        limit: int = Query(3, ge=1, le=20),
    ) -> PlainTextResponse:
        raw = (await file.read()).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(raw))
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise HTTPException(
                status_code=422,
                detail=f"el CSV no tiene la columna '{column}' (columnas: {reader.fieldnames})",
            )
        rows = [
            {"row": index, "text": row.get(column, ""), "family": row.get("familia") or None,
             "part_number": row.get("referencia") or None}
            for index, row in enumerate(reader, start=1)
            if str(row.get(column, "")).strip()
        ]
        results = service.batch(rows, limit=limit)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["fila", "peticion", "familia", "estado", "referencia_catalogo",
                         "url", "puntuacion", "motivo", "alternativas"])
        for result in results:
            writer.writerow([
                result["row"], result["input"], result["family"], result["status"],
                result["catalog_reference"] or "", result["catalog_url"] or "",
                f"{result['score']:.2f}", result["reason"], ", ".join(result["alternatives"]),
            ])
        return PlainTextResponse(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="crossref_resultados.csv"'},
        )

    # -------------------------------------------------------------- esquema

    @app.get("/api/v1/families", summary="Familias configuradas")
    def families() -> dict[str, Any]:
        return {
            "families": [
                {
                    "id": family.id,
                    "label": family.label,
                    "aliases": family.aliases,
                    "required": [spec.id for spec in family.required_attributes],
                    "attributes": len(family.attributes),
                }
                for family in service.registry.families.values()
            ]
        }

    @app.get("/api/v1/families/{family_id}", summary="Detalle de una familia")
    def family_detail(family_id: str) -> dict[str, Any]:
        try:
            return service.family_detail(family_id)
        except SchemaError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v1/families/reload", summary="Recargar los YAML de familias",
              dependencies=[Depends(require_admin)])
    def reload_families() -> dict[str, Any]:
        try:
            service.reload_families()
        except SchemaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"families": len(service.registry.families)}

    # ------------------------------------------------------------- catalogo

    @app.get("/api/v1/catalog/stats", summary="Estado del catalogo indexado")
    def stats() -> dict[str, Any]:
        return service.stats()

    @app.get("/api/v1/catalog/coverage/{family_id}", summary="Cobertura de datos por atributo")
    def coverage(family_id: str) -> dict[str, Any]:
        try:
            return service.coverage(family_id)
        except SchemaError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/catalog/items/{item_id:path}", summary="Ficha indexada")
    def item(item_id: str) -> dict[str, Any]:
        found = service.store.get(item_id)
        if found is None:
            raise HTTPException(status_code=404, detail="referencia no encontrada")
        return {
            "id": found.id,
            "reference": found.reference,
            "family": found.family,
            "manufacturer": found.manufacturer,
            "description": found.description,
            "url": found.url,
            "specs": found.specs,
            "attributes": {k: v.display() for k, v in found.attributes.items()},
            "source": found.source,
            "fetched_at": found.fetched_at.isoformat(),
        }

    @app.post("/api/v1/catalog/sync", summary="Sincronizar el catalogo desde una fuente",
              dependencies=[Depends(require_admin)])
    def sync(request: SyncRequest) -> dict[str, Any]:
        try:
            report = service.sync(
                request.source, limit=request.limit, deactivate_missing=request.deactivate_missing
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
        return report.as_dict()

    @app.get("/healthz", summary="Comprobacion de vida")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "families": len(service.registry.families),
                "items": service.stats()["items"]}

    # ------------------------------------------------------------ interfaz

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(WEB_DIR / "index.html"))

    app.state.service = service
    return app


app = create_app()
