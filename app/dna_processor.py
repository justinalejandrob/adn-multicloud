#!/usr/bin/env python3
"""
dna_processor.py - Procesamiento de cadenas de ADN (secuencial vs. paralelo).

Proyecto: Comparación de ADN migrando entre nubes mediante contenedores.
Materia : Computación Paralela, Distribuida y en la Nube (PDN) - Cloud Computing.

Qué hace
--------
1. Lee un archivo de ADN (texto plano o FASTA) de cualquier tamaño (4 MB, 4 GB...)
   por bloques ("chunks"), sin cargarlo completo en memoria.
2. Cuenta los nucleótidos A, C, G, T, los indeterminados (N) y los caracteres
   inválidos (cualquier otro símbolo), con el detalle de cada carácter inválido.
3. Busca un patrón genético (por defecto GATTACA) contando ocurrencias
   solapadas, incluso si el patrón cruza el borde entre dos bloques.
4. Ejecuta en modo SECUENCIAL (1 proceso) y/o PARALELO (N procesos
   configurables) y calcula speedup y eficiencia.
5. Guarda un JSON con los resultados y los metadatos de la nube donde corrió
   (proveedor, región, CPU, RAM), para comparar luego las 4 nubes.

Uso
---
    python dna_processor.py --input data/adn.txt --mode both --workers 4
    python dna_processor.py --input data/adn.txt --mode benchmark
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import socket
import sys
import time
from collections import Counter
from datetime import datetime, timezone

VALID = b"ACGT"
LOWER_VALID = b"acgt"
AMBIGUOUS = b"Nn"
WHITESPACE = b"\r\n\t "
# Separador interno entre registros FASTA (cromosomas): evita contar un patrón
# que "cruce" de un cromosoma a otro. No se cuenta como base ni como inválido.
SEP = b"\x00"
# Hasta cuántos bytes se busca un salto de línea para alinear un bloque.
# Si el archivo es una sola línea gigante no se encuentra y se corta en bruto.
ALIGN_WINDOW = 1 << 20  # 1 MiB
# Bytes extra leídos después del bloque para encontrar patrones en el borde.
LOOKAHEAD_BYTES = 4096


# ---------------------------------------------------------------------------
# División del archivo en bloques
# ---------------------------------------------------------------------------
def build_chunks(path: str, chunk_size: int) -> list[tuple[int, int]]:
    """Divide el archivo en rangos [inicio, fin) de ~chunk_size bytes.

    Cada corte se mueve hasta el siguiente salto de línea (si hay uno cerca)
    para no partir un encabezado FASTA (">...") a la mitad.
    """
    size = os.path.getsize(path)
    if size == 0:
        return []
    cuts = [0]
    with open(path, "rb") as fh:
        pos = chunk_size
        while pos < size:
            fh.seek(pos)
            window = fh.read(ALIGN_WINDOW)
            nl = window.find(b"\n")
            cut = pos + nl + 1 if nl != -1 else pos
            if cut <= cuts[-1]:
                cut = pos
            if cut >= size:
                break
            cuts.append(cut)
            pos = cut + chunk_size
    cuts.append(size)
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


def clean_sequence(raw: bytes, starts_at_line: bool) -> tuple[bytes, int]:
    """Quita encabezados FASTA y espacios/saltos de línea.

    Un encabezado es una línea que empieza con '>'. Solo se reconoce si el
    bloque empieza al inicio de una línea (o la línea está dentro del bloque).
    Cada encabezado se reemplaza por SEP. Devuelve (secuencia, n_encabezados).
    """
    headers = 0
    if b">" in raw:
        lines = raw.split(b"\n")
        kept = []
        for i, line in enumerate(lines):
            at_line_start = i > 0 or starts_at_line
            if at_line_start and line.startswith(b">"):
                headers += 1
                kept.append(SEP)
                continue
            kept.append(line)
        raw = b"".join(kept)
    return raw.translate(None, WHITESPACE), headers


# ---------------------------------------------------------------------------
# Trabajo de cada proceso (worker)
# ---------------------------------------------------------------------------
def count_overlapping(seq: bytes, pattern: bytes, limit: int) -> int:
    """Cuenta ocurrencias (solapadas) de pattern que empiezan antes de limit."""
    count, i = 0, seq.find(pattern)
    while i != -1 and i < limit:
        count += 1
        i = seq.find(pattern, i + 1)
    return count


def process_chunk(args: tuple) -> dict:
    """Procesa un bloque del archivo y devuelve sus conteos parciales."""
    path, start, end, pattern = args
    with open(path, "rb") as fh:
        starts_at_line = start == 0
        if start > 0:
            fh.seek(start - 1)
            starts_at_line = fh.read(1) == b"\n"
        fh.seek(start)
        raw = fh.read(end - start)
        tail_raw = fh.read(LOOKAHEAD_BYTES) if pattern else b""

    seq, records = clean_sequence(raw, starts_at_line)
    upper = seq.upper()
    separators = seq.count(SEP)

    counts = {b: upper.count(bytes([b])) for b in VALID}
    n_count = upper.count(b"N")
    lowercase = sum(seq.count(bytes([b])) for b in LOWER_VALID)

    # Caracteres inválidos = todo lo que no es A, C, G, T ni N.
    invalid_bytes = upper.translate(None, VALID + b"N" + SEP)
    invalid_detail = Counter(invalid_bytes)

    pattern_hits = 0
    if pattern:
        tail = clean_sequence(tail_raw, raw.endswith(b"\n"))[0].upper()
        window = upper + tail[: len(pattern) - 1]
        pattern_hits = count_overlapping(window, pattern, len(upper))

    return {
        "bytes_read": end - start,
        "length": len(seq) - separators,
        "records": records,
        "A": counts[ord("A")],
        "C": counts[ord("C")],
        "G": counts[ord("G")],
        "T": counts[ord("T")],
        "N": n_count,
        "lowercase": lowercase,
        "invalid": len(invalid_bytes),
        "invalid_detail": {chr(k): v for k, v in invalid_detail.items()},
        "pattern_hits": pattern_hits,
    }


def merge(partials) -> dict:
    """Reduce (suma) los resultados parciales de todos los bloques."""
    total = {k: 0 for k in ("bytes_read", "length", "records", "A", "C", "G", "T",
                            "N", "lowercase", "invalid", "pattern_hits")}
    detail: Counter = Counter()
    for p in partials:
        for k in total:
            total[k] += p[k]
        detail.update(p["invalid_detail"])
    total["invalid_detail"] = dict(sorted(detail.items(), key=lambda x: -x[1]))
    return total


# ---------------------------------------------------------------------------
# Ejecución secuencial y paralela
# ---------------------------------------------------------------------------
def with_progress(iterable, label: str, total: int):
    """Emite eventos de avance (bloques terminados) para el dashboard web.

    Solo se activa con DNA_PROGRESS=1 (lo define el modo servidor), así la
    salida en la terminal de las VMs sigue limpia.
    """
    if os.getenv("DNA_PROGRESS") != "1":
        yield from iterable
        return
    for i, item in enumerate(iterable, 1):
        print(f"@@progress {label} {i} {total}", flush=True)
        yield item


def run_sequential(path, chunks, pattern) -> tuple[dict, float]:
    t0 = time.perf_counter()
    result = merge(with_progress(
        (process_chunk((path, s, e, pattern)) for s, e in chunks),
        "sequential:1", len(chunks)))
    return result, time.perf_counter() - t0


def run_parallel(path, chunks, pattern, workers) -> tuple[dict, float]:
    t0 = time.perf_counter()
    tasks = [(path, s, e, pattern) for s, e in chunks]
    # Pool con número EXPLÍCITO de procesos (control de núcleos).
    with mp.Pool(processes=workers) as pool:
        result = merge(with_progress(pool.imap_unordered(process_chunk, tasks),
                                     f"parallel:{workers}", len(tasks)))
    return result, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Metadatos del entorno (para saber en qué nube corrió)
# ---------------------------------------------------------------------------
def total_ram_gb() -> float | None:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal"):
                    return round(int(line.split()[1]) / 1024 / 1024, 2)
    except OSError:
        pass
    return None


def cpu_model() -> str:
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.lower().startswith(("model name", "cpu model")):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "desconocido"


def environment_info() -> dict:
    return {
        "cloud_provider": os.getenv("CLOUD_PROVIDER", "local"),
        "cloud_region": os.getenv("CLOUD_REGION", "desconocida"),
        "cloud_origin": os.getenv("CLOUD_ORIGIN", "desconocido"),
        "instance_type": os.getenv("INSTANCE_TYPE", "desconocido"),
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "cpu_model": cpu_model(),
        "cpu_count": os.cpu_count(),
        "ram_gb": total_ram_gb(),
        "python": platform.python_version(),
        "in_container": os.path.exists("/.dockerenv"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Presentación de resultados
# ---------------------------------------------------------------------------
def read_side_file(path: str, first_word=False, as_float=False):
    """Lee los archivos auxiliares que deja fetch/generate (SHA-256, tiempo)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
        if first_word:
            text = text.split()[0]
        return float(text) if as_float else text
    except (OSError, ValueError, IndexError):
        return None


def summarize(result: dict) -> dict:
    valid = result["A"] + result["C"] + result["G"] + result["T"]
    length = result["length"] or 1
    gc = (result["G"] + result["C"]) / valid * 100 if valid else 0.0
    return {
        "valid_bases": valid,
        "gc_content_pct": round(gc, 4),
        "invalid_pct": round(result["invalid"] / length * 100, 4),
        "n_pct": round(result["N"] / length * 100, 4),
        "lowercase_pct": round(result["lowercase"] / length * 100, 4),
    }


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def print_report(env, result, runs, pattern):
    s = summarize(result)
    print("=" * 64)
    print(f" ADN procesado en: {env['cloud_provider']} ({env['cloud_region']})")
    print(f" CPU: {env['cpu_model']} | núcleos: {env['cpu_count']} | "
          f"RAM: {env['ram_gb']} GB | arq: {env['architecture']}")
    print("=" * 64)
    print(f" Tamaño leído      : {human_bytes(result['bytes_read'])}")
    print(f" Longitud secuencia: {result['length']:,}")
    for b in "ACGT":
        pct = result[b] / max(result["length"], 1) * 100
        print(f"   {b}: {result[b]:>15,}  ({pct:6.3f} %)")
    print(f"   N (indeterminado): {result['N']:,}")
    print(f" Secuencias (registros FASTA): {result['records']:,}")
    print(f" Bases en minúscula (regiones repetitivas enmascaradas): "
          f"{result['lowercase']:,}")
    print(f" Contenido GC      : {s['gc_content_pct']} %")
    print(f" Caracteres inválidos: {result['invalid']:,} ({s['invalid_pct']} %)")
    if result["invalid_detail"]:
        top = list(result["invalid_detail"].items())[:10]
        print("   Detalle: " + ", ".join(f"'{k}'={v:,}" for k, v in top))
    if pattern:
        print(f" Patrón {pattern.decode()}: {result['pattern_hits']:,} ocurrencias")
    print("-" * 64)
    print(f" {'Modo':<12}{'Procesos':>9}{'Tiempo (s)':>12}{'MB/s':>10}"
          f"{'Speedup':>9}{'Efic.':>8}")
    for r in runs:
        print(f" {r['mode']:<12}{r['workers']:>9}{r['seconds']:>12.3f}"
              f"{r['throughput_mb_s']:>10.1f}{r['speedup']:>9.2f}"
              f"{r['efficiency']:>8.2f}")
    print("=" * 64)


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Procesador de ADN secuencial/paralelo")
    p.add_argument("--input", "-i", default=os.getenv("DNA_FILE", "data/adn.txt"),
                   help="Archivo de ADN (texto plano o FASTA)")
    p.add_argument("--mode", "-m", default=os.getenv("MODE", "both"),
                   choices=["sequential", "parallel", "both", "benchmark"],
                   help="both = secuencial + paralelo; benchmark = 1,2,4.. procesos")
    p.add_argument("--workers", "-w", type=int,
                   default=int(os.getenv("WORKERS", "0")) or os.cpu_count(),
                   help="Número de procesos en modo paralelo (por defecto: todos)")
    p.add_argument("--chunk-mb", type=int, default=int(os.getenv("CHUNK_MB", "32")),
                   help="Tamaño de cada bloque en MB (afecta la RAM usada)")
    p.add_argument("--pattern", "-p", default=os.getenv("PATTERN", "GATTACA"),
                   help="Patrón genético a buscar ('' para desactivar)")
    p.add_argument("--output", "-o", default=os.getenv("OUTPUT_DIR", "results"),
                   help="Carpeta donde se guarda el JSON de resultados")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not os.path.isfile(args.input):
        print(f"ERROR: no existe el archivo {args.input}. "
              "Genere uno con generate_dna.py o monte la carpeta data/.",
              file=sys.stderr)
        return 1

    pattern = args.pattern.strip().upper().encode() if args.pattern else b""
    chunks = build_chunks(args.input, args.chunk_mb * 1024 * 1024)
    env = environment_info()
    size = os.path.getsize(args.input)

    print(f"Archivo: {args.input} ({human_bytes(size)}) -> {len(chunks)} bloques "
          f"de {args.chunk_mb} MB")

    runs, result, reference_result, t_seq = [], None, None, None

    def record(mode, workers, res, seconds):
        nonlocal t_seq
        if mode == "sequential":
            t_seq = seconds
        speedup = (t_seq / seconds) if t_seq else 1.0
        runs.append({
            "mode": mode,
            "workers": workers,
            "seconds": round(seconds, 4),
            "throughput_mb_s": round(size / 1024 / 1024 / seconds, 2) if seconds else 0,
            "speedup": round(speedup, 3),
            "efficiency": round(speedup / workers, 3),
        })
        print(f"  [{mode}] procesos={workers} tiempo={seconds:.3f}s")

    if args.mode in ("sequential", "both", "benchmark"):
        result, secs = run_sequential(args.input, chunks, pattern)
        reference_result = result
        record("sequential", 1, result, secs)

    if args.mode in ("parallel", "both"):
        result, secs = run_parallel(args.input, chunks, pattern, args.workers)
        record("parallel", args.workers, result, secs)

    if args.mode == "benchmark":
        n, workers_list = 2, []
        while n <= max(args.workers, os.cpu_count() or 1):
            workers_list.append(n)
            n *= 2
        if args.workers not in workers_list and args.workers > 1:
            workers_list.append(args.workers)
        for w in sorted(workers_list):
            result, secs = run_parallel(args.input, chunks, pattern, w)
            record("parallel", w, result, secs)

    # Validación de integridad: el paralelo debe dar EXACTAMENTE lo mismo.
    consistent = True
    if reference_result is not None and result is not reference_result:
        consistent = reference_result == result
        print("  Validación secuencial == paralelo:", "OK" if consistent else "ERROR")

    print_report(env, result, runs, pattern)

    os.makedirs(args.output, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = os.path.join(args.output, f"resultado_{env['cloud_provider']}_{stamp}.json")
    payload = {
        "environment": env,
        "input": {"file": os.path.basename(args.input), "size_bytes": size,
                  "chunk_mb": args.chunk_mb, "chunks": len(chunks),
                  "pattern": pattern.decode(),
                  "sha256": read_side_file(args.input + ".sha256", first_word=True),
                  "download_seconds": read_side_file(args.input + ".download_seconds",
                                                     as_float=True)},
        "result": result,
        "summary": summarize(result),
        "runs": runs,
        "sequential_equals_parallel": consistent,
    }
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"Resultados guardados en {out_file}")
    return 0 if consistent else 2


if __name__ == "__main__":
    sys.exit(main())
