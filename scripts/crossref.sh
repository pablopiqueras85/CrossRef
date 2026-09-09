#!/usr/bin/env bash
# Arranque de CrossRef en macOS y Linux.
#
# La primera vez crea el entorno e instala las dependencias. Despues arranca
# en segundos. Con --sync reconstruye el indice desde el catalogo web.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
    echo "Preparando el entorno por primera vez..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip --quiet
    .venv/bin/python -m pip install -e . --quiet
fi

if [ "${1:-}" = "--sync" ]; then
    # Va a media peticion por segundo: la primera vez son un par de horas.
    exec .venv/bin/crossref sync config/sources/we_online.yaml --deactivate-missing
fi

if [ ! -f data/catalog.db ]; then
    echo "No hay catalogo indexado todavia. Ejecuta: $0 --sync"
    exit 1
fi

url="http://127.0.0.1:8000"
echo "Abriendo CrossRef en $url ..."
(sleep 2; (open "$url" || xdg-open "$url") >/dev/null 2>&1 || true) &
exec .venv/bin/crossref serve
