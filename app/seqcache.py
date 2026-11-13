"""
seqcache.py - Caché del FASTA limpio (<archivo>.seq) y plan de fragmentos.

El FASTA se limpia una sola vez: se quitan encabezados y saltos de línea y los
registros (cromosomas) quedan separados por el byte 0x00. Lo usan el maestro y
cada worker (que lee sus fragmentos de su propia copia local, por referencia).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time

from dna_processor import clean_sequence

MB = 1024 * 1024
CACHE_BLOCK = 64 * MB
_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    with _GLOBAL:
        return _LOCKS.setdefault(os.path.abspath(path), threading.Lock())


def cached_meta(path: str, cache_dir: str | None = None) -> dict | None:
    """Meta de la caché si ya existe y está al día (sin construirla)."""
    try:
        st = os.stat(path)
        folder = cache_dir or os.path.join(os.path.dirname(os.path.abspath(path)), ".cache")
        seq_path = os.path.join(folder, os.path.basename(path) + ".seq")
        with open(seq_path + ".json", encoding="utf-8") as fh:
            meta = json.load(fh)
        if (meta.get("src_size") == st.st_size and meta.get("src_mtime") == int(st.st_mtime)
                and os.path.getsize(seq_path) == meta.get("seq_size")):
            return meta
    except (OSError, ValueError):
        pass
    return None


def seq_cache(path: str, cache_dir: str | None = None, log=print) -> dict:
    """Limpia el FASTA una sola vez. Devuelve info de la caché.

    Es determinista: el mismo FASTA produce la misma caché (mismo seq_sha256)
    en cualquier nube, así los desplazamientos (offset) de un fragmento
    significan lo mismo en todos los nodos.
    """
    with _lock_for(path):
        return _seq_cache(path, cache_dir, log)


def _seq_cache(path, cache_dir, log):
    st = os.stat(path)
    base = os.path.basename(path)
    folder = cache_dir or os.path.join(os.path.dirname(os.path.abspath(path)), ".cache")
    os.makedirs(folder, exist_ok=True)
    seq_path = os.path.join(folder, base + ".seq")
    meta_path = seq_path + ".json"
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        if (meta.get("src_size") == st.st_size and meta.get("src_mtime") == int(st.st_mtime)
                and os.path.getsize(seq_path) == meta.get("seq_size")):
            return meta
    except (OSError, ValueError):
        pass

    log(f"Limpiando {base} ({st.st_size / MB:,.1f} MB) -> caché .seq ...")
    t0 = time.perf_counter()
    sha, seq_sha = hashlib.sha256(), hashlib.sha256()
    records, written = 0, 0
    with open(path, "rb") as src, open(seq_path + ".part", "wb") as out:
        while True:
            block = src.read(CACHE_BLOCK)
            if not block:
                break
            if not block.endswith(b"\n"):
                block += src.readline()          # termina la línea en curso
            sha.update(block)
            seq, headers = clean_sequence(block, True)
            records += headers
            out.write(seq)
            seq_sha.update(seq)
            written += len(seq)
    os.replace(seq_path + ".part", seq_path)
    meta = {"file": base, "src_size": st.st_size, "src_mtime": int(st.st_mtime),
            "src_sha256": sha.hexdigest(), "seq_sha256": seq_sha.hexdigest(), "seq_path": seq_path, "seq_size": written,
            "records": records, "seconds": round(time.perf_counter() - t0, 2)}
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    log(f"Caché lista en {meta['seconds']} s: {written / MB:,.1f} MB, {records} secuencias")
    return meta


def plan_pieces(size: int, chunk: int, overlap: int) -> list[tuple[int, int, int]]:
    """[(inicio, longitud_sin_solape, solape)] cubriendo [0, size)."""
    pieces, off = [], 0
    while off < size:
        n = min(chunk, size - off)
        ov = min(overlap, size - off - n)
        pieces.append((off, n, ov))
        off += n
    return pieces
