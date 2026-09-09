"""Linea de comandos de CrossRef.

    crossref sync config/sources/ejemplo_csv.yaml
    crossref find "atenuador 3 dB SMA macho/hembra DC-18GHz 2W"
    crossref batch peticiones.csv --out resultados.csv
    crossref serve
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from .schema import SchemaError, load_registry
from .grupos import ids as grupo_ids
from .service import DEFAULT_DB_PATH, DEFAULT_FAMILIES_DIR, CrossRefService

__all__ = ["main"]

_COLOR = {
    "equivalente": "\033[32m",
    "alternativa": "\033[33m",
    "requiere revision": "\033[35m",
    "descartado": "\033[31m",
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
}


def _paint(text: str, key: str, enabled: bool) -> str:
    return f"{_COLOR.get(key, '')}{text}{_COLOR['reset']}" if enabled else text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crossref",
        description="Equivalencias de componentes contra el catalogo propio.",
    )
    parser.add_argument(
        "--families",
        default=str(DEFAULT_FAMILIES_DIR),
        help="directorio de familias (admite varios separados por comas)",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="ruta del indice SQLite")
    parser.add_argument("--no-color", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_find = sub.add_parser("find", help="buscar la equivalencia de una peticion")
    p_find.add_argument("text", help="peticion en texto libre")
    p_find.add_argument("--family", help="forzar familia")
    p_find.add_argument("--limit", type=int, default=5)
    p_find.add_argument("--rejected", action="store_true", help="mostrar tambien las descartadas")
    p_find.add_argument("--strict", action="store_true", help="solo equivalencias 1:1")
    p_find.add_argument(
        "--grupo", choices=grupo_ids(),
        help="acotar a un bloque del catalogo (pasivos, electromecanica...)",
    )
    p_find.add_argument("--json", action="store_true", help="salida JSON completa")

    p_batch = sub.add_parser("batch", help="procesar un fichero de peticiones")
    p_batch.add_argument("path", help="CSV con una columna de peticiones, o TXT con una por linea")
    p_batch.add_argument("--column", default="peticion", help="columna del CSV")
    p_batch.add_argument("--out", help="CSV de salida (por defecto, por pantalla)")
    p_batch.add_argument("--limit", type=int, default=3, help="alternativas por peticion")

    p_sync = sub.add_parser("sync", help="sincronizar el catalogo desde una fuente")
    p_sync.add_argument("source", help="YAML de configuracion de la fuente")
    p_sync.add_argument("--limit", type=int, help="maximo de fichas (para probar)")
    p_sync.add_argument("--deactivate-missing", action="store_true",
                        help="dar de baja las referencias que ya no aparecen")
    p_sync.add_argument("--json", action="store_true")

    p_xref = sub.add_parser(
        "crossrefs", help="cargar una tabla de equivalencias de la competencia"
    )
    p_xref.add_argument("path", help="CSV con la referencia ajena y la propia")
    p_xref.add_argument("--source", help="nombre de la lista (queda como procedencia)")
    p_xref.add_argument("--json", action="store_true")

    p_fam = sub.add_parser("families", help="listar familias o ver una")
    p_fam.add_argument("family_id", nargs="?")

    sub.add_parser("stats", help="estado del catalogo indexado")

    p_cov = sub.add_parser("coverage", help="cobertura de datos de una familia")
    p_cov.add_argument("family_id")

    sub.add_parser("check", help="validar los YAML de familias")

    p_probe = sub.add_parser(
        "probe", help="probar el conector web contra una ficha concreta del catalogo"
    )
    p_probe.add_argument("source", help="YAML de la fuente web")
    p_probe.add_argument("url", help="URL de una ficha de producto")

    p_serve = sub.add_parser("serve", help="levantar la API y la interfaz web")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    color = sys.stdout.isatty() and not args.no_color

    if args.command == "check":
        return _cmd_check(args.families)
    if args.command == "serve":
        return _cmd_serve(args)

    service = CrossRefService(args.families, args.db)
    handlers = {
        "probe": _cmd_probe,
        "find": _cmd_find,
        "batch": _cmd_batch,
        "sync": _cmd_sync,
        "crossrefs": _cmd_crossrefs,
        "families": _cmd_families,
        "stats": _cmd_stats,
        "coverage": _cmd_coverage,
    }
    return handlers[args.command](service, args, color)


# --------------------------------------------------------------------------


def _cmd_find(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    response = service.crossref(
        text=args.text, family=args.family, limit=args.limit,
        include_rejected=args.rejected, strict=args.strict, group=args.grupo,
    )
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0

    family = response["family"]
    print(_paint(f"Familia: {family['label']} ({family['confidence']:.0%})", "bold", color))
    understood = ", ".join(f"{u['label']}={u['normalized']}" for u in response["query"]["understood"])
    print(f"Entendido: {understood or '(nada)'}")
    if response["query"]["unparsed"]:
        print(_paint(f"Sin usar: {', '.join(response['query']['unparsed'])}", "dim", color))
    for warning in response["warnings"]:
        print(_paint(f"Aviso: {warning}", "dim", color))
    print(f"Evaluadas {response['catalog_candidates']} referencias del catalogo.\n")

    if not response["results"]:
        print("Sin equivalencia en el catalogo.")
    for result in response["results"]:
        _print_result(result, color)
    if response["rejected"]:
        print(_paint("\nDescartadas:", "bold", color))
        for result in response["rejected"]:
            _print_result(result, color, compact=True)
    return 0 if response["results"] else 2


def _print_result(result: dict[str, Any], color: bool, compact: bool = False) -> None:
    verdict = result["verdict"]
    head = f"[{verdict.upper()}] {result['reference']}  afinidad {result['score']:.0%}"
    print(_paint(head, verdict, color))
    if result.get("description"):
        print(f"    {result['description']}")
    if result.get("url"):
        print(_paint(f"    {result['url']}", "dim", color))
    for reason in result["reasons"][: 2 if compact else 6]:
        print(f"    · {reason}")
    if not compact:
        for c in result["comparisons"]:
            if c["status"] == "no aplicable":
                continue
            mark = {"coincide": "=", "aproximado": "~", "no coincide": "x"}.get(c["status"], "?")
            print(
                f"      {mark} {c['label']:<28} {str(c['query_value'] or '-'):<18}"
                f" {str(c['catalog_value'] or '-'):<18} {c['reason']}"
            )
    print()


def _cmd_batch(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"No existe el fichero: {path}", file=sys.stderr)
        return 1

    rows: list[dict[str, Any]] = []
    if path.suffix.lower() in (".csv", ".tsv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
            if reader.fieldnames is None or args.column not in reader.fieldnames:
                print(
                    f"El CSV no tiene la columna '{args.column}'. Columnas: {reader.fieldnames}",
                    file=sys.stderr,
                )
                return 1
            for index, row in enumerate(reader, start=1):
                if str(row.get(args.column, "")).strip():
                    rows.append({
                        "row": index,
                        "text": row[args.column],
                        "family": row.get("familia") or None,
                        "part_number": row.get("referencia") or None,
                    })
    else:
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                rows.append({"row": index, "text": line.strip()})

    results = service.batch(rows, limit=args.limit)
    header = ["fila", "peticion", "familia", "estado", "referencia_catalogo", "url",
              "puntuacion", "motivo", "alternativas"]
    output_rows = [
        [r["row"], r["input"], r["family"], r["status"], r["catalog_reference"] or "",
         r["catalog_url"] or "", f"{r['score']:.2f}", r["reason"], ", ".join(r["alternatives"])]
        for r in results
    ]

    if args.out:
        with Path(args.out).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(header)
            writer.writerows(output_rows)
        counts: dict[str, int] = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"{len(results)} peticiones -> {args.out}")
        for status, count in sorted(counts.items()):
            print(f"  {status}: {count}")
    else:
        for r in results:
            print(_paint(f"{r['row']:>4}  [{r['status']}]", r["status"], color),
                  f"{r['catalog_reference'] or '-':<24} {r['input'][:60]}")
    return 0


def _cmd_sync(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    report = service.sync(args.source, limit=args.limit, deactivate_missing=args.deactivate_missing)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print("\n".join(report.summary_lines()))
    return 0 if not report.errors else 1


def _cmd_crossrefs(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    try:
        report = service.load_cross_references(args.path, args.source)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print("\n".join(report.summary_lines()))
    return 0


def _cmd_families(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    if args.family_id:
        try:
            detail = service.family_detail(args.family_id)
        except SchemaError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(_paint(f"{detail['label']} ({detail['id']})", "bold", color))
        for attr in detail["attributes"]:
            flag = "obligatorio" if attr["required"] else "opcional   "
            print(f"  {flag}  {attr['id']:<20} {attr['type']:<7} {attr['rule']}")
            if attr["values"]:
                print(_paint(f"      valores: {', '.join(attr['values'][:12])}", "dim", color))
        return 0
    for family in service.registry.families.values():
        required = ", ".join(spec.id for spec in family.required_attributes) or "-"
        print(f"{family.id:<20} {family.label:<38} obligatorios: {required}")
    return 0


def _cmd_stats(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    stats = service.stats()
    print(_paint(f"{stats['items']} referencias activas", "bold", color))
    for family, count in stats["by_family"].items():
        print(f"  {family:<24} {count}")
    print("\nFuentes:")
    for source, info in stats["by_source"].items():
        print(f"  {source:<24} {info['items']} referencias, ultima carga {info['last_fetch']}")
    return 0


def _cmd_coverage(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    try:
        data = service.coverage(args.family_id)
    except SchemaError as exc:
        print(exc, file=sys.stderr)
        return 1
    for attr_id, info in data.items():
        flag = "*" if info["required"] else " "
        bar = "#" * int(info["coverage"] * 20)
        print(f" {flag} {info['label']:<30} {info['coverage']:>6.0%} {bar} ({info['items_with_value']})")
    return 0


def _cmd_check(families_dir: str) -> int:
    try:
        registry = load_registry(families_dir)
    except SchemaError as exc:
        print(f"Error en la configuracion: {exc}", file=sys.stderr)
        return 1
    problems = 0
    for family in registry.families.values():
        if family.id != "generic" and not family.required_attributes:
            print(f"aviso: la familia '{family.id}' no tiene campos obligatorios; "
                  "nunca podra confirmar un 1:1")
            problems += 1
    print(f"{len(registry.families)} familias validadas.")
    return 0 if problems == 0 else 0


def _cmd_probe(service: CrossRefService, args: argparse.Namespace, color: bool) -> int:
    """Descarga una ficha y ensena que ha entendido: para afinar los selectores."""
    from .ingest import resolve_family
    from .sources.base import load_source
    from .sources.web import WebCatalogSource

    source = load_source(args.source)
    if not isinstance(source, WebCatalogSource):
        print("El comando 'probe' es para fuentes de tipo 'web'.", file=sys.stderr)
        return 1

    html = source.get(args.url)
    if html is None:
        print(f"No se ha podido descargar {args.url}", file=sys.stderr)
        return 1
    product = source.parse_product(html, args.url)
    if product is None:
        print(_paint("No se ha encontrado referencia en la pagina.", "descartado", color))
        print("Revisa 'product.reference' en el YAML, o comprueba si la ficha publica JSON-LD.")
        return 2

    print(_paint(f"Referencia:   {product.reference}", "bold", color))
    print(f"Fabricante:   {product.manufacturer or '-'}")
    print(f"Descripcion:  {product.description or '-'}")
    print(f"Categorias:   {' > '.join(product.category_path) or '-'}")
    print(f"Datasheet:    {product.datasheet_url or '-'}")

    family_id = resolve_family(service.registry, product)
    family = service.registry.get(family_id)
    print(_paint(f"\nFamilia detectada: {family_id or 'ninguna'}", "bold", color))
    if family is None:
        print("Anade la categoria del catalogo a 'source_categories' de la familia que toque.")

    print(f"\n{len(product.specs)} especificaciones encontradas:")
    mapped, unmapped = ({}, product.specs)
    if family is not None:
        from .extract import map_fields

        mapped, unmapped = map_fields(family, product.specs)
        reverse = {value.source_field or key: key for key, value in mapped.items()}
        for name, raw in product.specs.items():
            attr = reverse.get(name)
            if attr:
                print(f"  = {name:<32} {raw:<24} -> {attr} = {mapped[attr].display()}")
    for name, raw in unmapped.items():
        print(_paint(f"  ? {name:<32} {raw:<24} -> sin mapear", "dim", color))
    if unmapped and family is not None:
        print(
            "\nPara usar esos campos, anadelos como 'aliases' del atributo correspondiente "
            f"en config/families (familia '{family.id}')."
        )
    if family is not None:
        faltan = [spec.label for spec in family.required_attributes
                  if spec.id not in mapped or mapped[spec.id].is_empty()]
        if faltan:
            print(_paint(f"\nFaltan campos obligatorios: {', '.join(faltan)}", "alternativa", color))
        else:
            print(_paint("\nLa ficha trae todos los campos obligatorios de su familia.",
                         "equivalente", color))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn

    # La app se crea dentro del proceso de uvicorn (necesario con --reload),
    # asi que la configuracion viaja por entorno.
    os.environ["CROSSREF_FAMILIES"] = args.families
    os.environ["CROSSREF_DB"] = args.db
    print(f"Familias: {args.families}\nCatalogo: {args.db}\nEscuchando en http://{args.host}:{args.port}")
    uvicorn.run("crossref.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
