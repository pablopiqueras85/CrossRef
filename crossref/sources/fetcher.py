"""Descarga de paginas web con buenos modales.

Lo comparten los conectores web: se respeta robots.txt, se limita el ritmo de
peticiones y se cachea lo descargado para no repetir trabajo.
"""

from __future__ import annotations

import hashlib
import time
import urllib.robotparser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .base import SourceError

__all__ = ["WebFetcher", "DEFAULT_USER_AGENT"]

DEFAULT_USER_AGENT = "CrossRefBot/0.1 (catalogo interno; contacto: it@empresa.local)"


class WebFetcher:
    """Cliente HTTP con robots.txt, limite de ritmo y cache en disco."""

    def __init__(self, config: dict[str, Any], client: httpx.Client | None = None) -> None:
        self.config = config
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        if not self.base_url:
            raise SourceError("la fuente web necesita 'base_url'")

        request = config.get("request") or {}
        self.user_agent = str(request.get("user_agent", DEFAULT_USER_AGENT))
        self.timeout = float(request.get("timeout", 20))
        self.rate_limit = float(request.get("rate_limit_per_sec", 1.0))
        self.max_pages = int(request.get("max_pages", 5000))
        self.respect_robots = bool(request.get("respect_robots", True))
        self.headers = {"User-Agent": self.user_agent, **(request.get("headers") or {})}
        self.cache_dir = Path(request["cache_dir"]) if request.get("cache_dir") else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        for name, value in self.headers.items():
            # Las cabeceras HTTP son ASCII: un acento en el user-agent aborta
            # la sesion con un error muy poco informativo.
            if not str(value).isascii():
                raise SourceError(
                    f"la cabecera '{name}' tiene caracteres no ASCII: {value!r}. "
                    "Usa solo ASCII en 'request.user_agent' y 'request.headers'."
                )
        self._client = client or httpx.Client(
            headers=self.headers, timeout=self.timeout, follow_redirects=True
        )
        self._owns_client = client is None
        self._last_request = 0.0
        self._robots: urllib.robotparser.RobotFileParser | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get(self, url: str) -> str | None:
        """HTML de `url`, o None si la pagina responde con error."""
        return self._get(url)

    # ------------------------------------------------------------------- red

    def _get(self, url: str) -> str | None:
        local = _local_path(url)
        if local is not None:
            # Ficha guardada en disco: util para ajustar los selectores sin red.
            if not local.exists():
                raise SourceError(f"no existe el fichero: {local}")
            return local.read_text(encoding="utf-8", errors="ignore")

        if self.respect_robots and not self._robots_allows(url):
            raise SourceError(
                f"robots.txt no permite descargar {url}. Pide una API o una exportacion "
                "del catalogo, o autorizacion expresa para rastrearlo."
            )
        cached = self._read_cache(url)
        if cached is not None:
            return cached

        wait = (1.0 / self.rate_limit) - (time.monotonic() - self._last_request) if self.rate_limit else 0
        if wait > 0:
            time.sleep(wait)
        try:
            response = self._client.get(url)
            self._last_request = time.monotonic()
            if response.status_code >= 400:
                return None
            text = response.text
        except httpx.HTTPError as exc:
            raise SourceError(f"error descargando {url}: {exc}") from exc
        self._write_cache(url, text)
        return text

    def _robots_allows(self, url: str) -> bool:
        if self._robots is None:
            parser = urllib.robotparser.RobotFileParser()
            robots_url = urljoin(self.base_url + "/", "/robots.txt")
            try:
                response = self._client.get(robots_url)
                parser.parse(response.text.splitlines() if response.status_code < 400 else [])
            except httpx.HTTPError:
                parser.parse([])
            self._robots = parser
        return self._robots.can_fetch(self.user_agent, url)

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{digest}.html"

    def _read_cache(self, url: str) -> str | None:
        path = self._cache_path(url)
        if path and path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
        return None

    def _write_cache(self, url: str, text: str) -> None:
        path = self._cache_path(url)
        if path:
            path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# Utilidades de extraccion
# --------------------------------------------------------------------------

def _local_path(url: str) -> Path | None:
    """Devuelve la ruta si `url` apunta a un fichero local (file:// o ruta suelta)."""
    if url.startswith("file://"):
        return Path(url_to_path(url))
    if url.startswith(("http://", "https://")):
        return None
    candidate = Path(url)
    return candidate if candidate.suffix.lower() in (".html", ".htm") else None


def url_to_path(url: str) -> str:
    from urllib.parse import unquote

    return unquote(urlparse(url).path)
