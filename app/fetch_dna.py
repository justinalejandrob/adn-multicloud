#!/usr/bin/env python3
"""
fetch_dna.py - Descarga el archivo de ADN real directamente en la nube.

Así cada nube descarga el genoma desde la fuente (Dropbox del docente o
NCBI) a la velocidad de su datacenter, en vez de subir 3 GB desde la laptop.

- Acepta enlaces de Dropbox (convierte dl=0 -> dl=1 automáticamente) y de
  OneDrive / SharePoint (agrega download=1 o usa la API de "shares").
- Si el enlace devuelve una página web (inicio de sesión, vista previa) en vez
  del archivo, se detiene con un mensaje claro en lugar de guardar HTML.
- Si el archivo viene comprimido (.gz) lo descomprime en el camino.
- --limit-mb permite procesar solo los primeros N MB (útil en PaaS o VMs
  con poco disco). Sin límite descarga el archivo completo.
- Calcula el SHA-256 para demostrar que todas las nubes usaron el MISMO archivo.

Uso:
  python fetch_dna.py --url "https://www.dropbox.com/...?dl=0" --output data/adn.txt
  python fetch_dna.py --url URL --limit-mb 500
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request
import zlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

BLOCK = 4 * 1024 * 1024


def _onedrive_share_api(url: str) -> str:
    """OneDrive personal (1drv.ms / onedrive.live.com): API pública de "shares".
    https://learn.microsoft.com/onedrive/developer/rest-api/api/shares_get"""
    token = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f"https://api.onedrive.com/v1.0/shares/u!{token}/root/content"


def direct_link(url: str) -> str:
    """Convierte un enlace compartido (Dropbox, OneDrive, SharePoint) en descarga directa."""
    parts = urlparse(url)
    host = parts.netloc.lower()
    query = dict(parse_qsl(parts.query))
    if "dropbox.com" in host:
        query["dl"] = "1"
        return urlunparse(parts._replace(query=urlencode(query)))
    if host.endswith("sharepoint.com"):
        # OneDrive de la universidad (Microsoft 365): .../:u:/g/personal/...?e=xxx
        if "download.aspx" in parts.path.lower() or query.get("download") == "1":
            return url
        query["download"] = "1"
        return urlunparse(parts._replace(query=urlencode(query)))
    if host in ("1drv.ms", "onedrive.live.com") and "download" not in parts.path.lower():
        return _onedrive_share_api(url)
    return url


def looks_like_html(first: bytes) -> bool:
    head = first[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<?xml"))


def download(url: str, output: str, limit_mb: int, headers: dict | None = None,
             progress=None) -> tuple[str, int]:
    limit = limit_mb * 1024 * 1024 if limit_mb else None
    tmp = output + ".part"
    sha = hashlib.sha256()
    written = 0
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "adn-multicloud/1.0", **(headers or {})})
    t0 = time.perf_counter()
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        hint = (" El enlace no es público: en OneDrive elija «Cualquier persona con el vínculo»"
                " o use «Subir desde tu PC»." if exc.code in (401, 403) else "")
        raise RuntimeError(f"HTTP {exc.code} al descargar.{hint}") from exc
    with resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        first = resp.read(BLOCK)
        if "text/html" in resp.headers.get("Content-Type", "") or looks_like_html(first):
            out.close()
            os.remove(tmp)
            raise RuntimeError("el enlace devolvió una página web, no el archivo (¿pide iniciar "
                               "sesión o es el enlace de una CARPETA?). Comparta el ARCHIVO con "
                               "«Cualquier persona con el vínculo» o use «Subir desde tu PC».")
        gz = first[:2] == b"\x1f\x8b"  # firma de gzip
        dec = zlib.decompressobj(16 + zlib.MAX_WBITS) if gz else None
        received = 0
        chunk = first
        while chunk:
            received += len(chunk)
            data = chunk
            if dec is not None:
                data = dec.decompress(chunk)
                # archivos gzip con varios miembros (concatenados)
                while dec.unused_data:
                    rest = dec.unused_data
                    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    data += dec.decompress(rest)
            if limit is not None and written + len(data) >= limit:
                data = data[: limit - written]
            out.write(data)
            sha.update(data)
            written += len(data)
            elapsed = time.perf_counter() - t0
            pct = f"{received / total * 100:5.1f} %" if total else ""
            print(f"\r  descargado {received / 1024**2:,.0f} MB {pct} | "
                  f"escrito {written / 1024**2:,.0f} MB | "
                  f"{received / 1024**2 / max(elapsed, 1e-6):,.1f} MB/s",
                  end="", flush=True)
            if progress is not None:
                progress(received, total)
            if limit is not None and written >= limit:
                break
            chunk = resp.read(BLOCK)
    print()
    os.replace(tmp, output)
    return sha.hexdigest(), written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Descarga el ADN real a la nube")
    p.add_argument("--url", default=os.getenv("DNA_URL", ""),
                   help="URL del archivo (Dropbox, NCBI, etc.)")
    p.add_argument("--output", "-o", default=os.getenv("DNA_FILE", "data/adn.txt"))
    p.add_argument("--limit-mb", type=int, default=int(os.getenv("DNA_LIMIT_MB", "0")),
                   help="Solo los primeros N MB (0 = archivo completo)")
    p.add_argument("--force", action="store_true", help="Descargar aunque ya exista")
    args = p.parse_args(argv)

    if not args.url:
        print("ERROR: falta --url o la variable DNA_URL", file=sys.stderr)
        return 1
    url = direct_link(args.url)
    stamp = args.output + ".source"
    wanted = f"{url}|{args.limit_mb}"
    if (os.path.exists(args.output) and os.path.exists(stamp) and not args.force
            and open(stamp).read() == wanted):
        print(f"{args.output} ya fue descargado de la misma fuente; se reutiliza.")
        return 0

    print(f"Descargando {urlparse(url).netloc} -> {args.output}"
          + (f" (primeros {args.limit_mb} MB)" if args.limit_mb else " (completo)"))
    t0 = time.perf_counter()
    try:
        digest, size = download(url, args.output, args.limit_mb)
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR en la descarga: {exc}", file=sys.stderr)
        return 1
    secs = time.perf_counter() - t0
    print(f"Listo: {size:,} bytes en {secs:.1f}s | SHA-256: {digest}")
    with open(args.output + ".sha256", "w") as fh:
        fh.write(f"{digest}  {os.path.basename(args.output)}\n")
    with open(stamp, "w") as fh:
        fh.write(wanted)
    with open(args.output + ".download_seconds", "w") as fh:
        fh.write(f"{secs:.1f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
