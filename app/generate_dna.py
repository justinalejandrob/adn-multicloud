#!/usr/bin/env python3
"""
generate_dna.py - Genera un archivo de ADN sintético (formato FASTA).

- Bases A, C, G, T con una pequeña proporción de caracteres inválidos
  (errores de secuenciación simulados: X, R, Y, -, *, 0-9, etc.) y de N.
- Es DETERMINISTA: con la misma semilla y tamaño produce exactamente el mismo
  archivo en cualquier nube. Así no hay que subir 4 GB a cada proveedor y los
  resultados de las 4 nubes deben coincidir bit a bit (prueba de portabilidad).

Uso:
    python generate_dna.py --size 4GB --output data/adn.txt
    python generate_dna.py --size 100MB --error-rate 0.01 --seed 2026
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time

import numpy as np

LINE = 80                       # caracteres por línea (estándar FASTA)
BLOCK_LINES = 400_000           # ~32 MB por bloque generado
BASES = np.frombuffer(b"ACGT", dtype=np.uint8)
INVALID = np.frombuffer(b"XRYKMSWBDHV-*.0123456789", dtype=np.uint8)


def parse_size(text: str) -> int:
    text = text.strip().upper().replace(" ", "")
    units = {"GB": 1024**3, "MB": 1024**2, "KB": 1024, "B": 1}
    for unit, mult in units.items():
        if text.endswith(unit):
            return int(float(text[: -len(unit)]) * mult)
    return int(text)


def generate(path: str, size: int, error_rate: float, n_rate: float,
             seed: int) -> str:
    rng = np.random.default_rng(seed)
    header = f">ADN_sintetico seed={seed} size={size} error_rate={error_rate}\n".encode()
    sha = hashlib.sha256()
    written = 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    with open(path, "wb") as fh:
        fh.write(header)
        sha.update(header)
        written += len(header)
        while written < size:
            remaining = size - written
            lines = min(BLOCK_LINES, max(1, remaining // (LINE + 1)))
            block = BASES[rng.integers(0, 4, size=(lines, LINE), dtype=np.uint8)]

            # Errores de secuenciación (caracteres inválidos)
            mask = rng.random((lines, LINE)) < error_rate
            if mask.any():
                block[mask] = INVALID[rng.integers(0, len(INVALID), mask.sum())]
            # Bases indeterminadas (N)
            nmask = rng.random((lines, LINE)) < n_rate
            block[nmask] = ord("N")

            out = np.empty((lines, LINE + 1), dtype=np.uint8)
            out[:, :LINE] = block
            out[:, LINE] = ord("\n")
            data = out.tobytes()[:remaining]
            fh.write(data)
            sha.update(data)
            written += len(data)
            print(f"\r  generado {written / 1024**2:,.0f} / {size / 1024**2:,.0f} MB",
                  end="", flush=True)
    print()
    return sha.hexdigest()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Generador de ADN sintético FASTA")
    p.add_argument("--size", "-s", default=os.getenv("DNA_SIZE", "100MB"),
                   help="Tamaño del archivo: 4MB, 1GB, 4GB...")
    p.add_argument("--output", "-o", default=os.getenv("DNA_FILE", "data/adn.txt"))
    p.add_argument("--error-rate", type=float,
                   default=float(os.getenv("ERROR_RATE", "0.001")),
                   help="Proporción de caracteres inválidos (0.001 = 0.1 %%)")
    p.add_argument("--n-rate", type=float, default=float(os.getenv("N_RATE", "0.0005")),
                   help="Proporción de bases indeterminadas N")
    p.add_argument("--seed", type=int, default=int(os.getenv("SEED", "2026")))
    p.add_argument("--force", action="store_true",
                   help="Regenerar aunque el archivo ya exista")
    args = p.parse_args(argv)

    size = parse_size(args.size)
    if os.path.exists(args.output) and os.path.getsize(args.output) == size \
            and not args.force:
        print(f"{args.output} ya existe con {size:,} bytes; se reutiliza "
              "(use --force para regenerar).")
        return 0

    print(f"Generando {args.output}: {size:,} bytes, semilla {args.seed}")
    t0 = time.perf_counter()
    digest = generate(args.output, size, args.error_rate, args.n_rate, args.seed)
    print(f"Listo en {time.perf_counter() - t0:.1f}s | SHA-256: {digest}")
    with open(args.output + ".sha256", "w") as fh:
        fh.write(f"{digest}  {os.path.basename(args.output)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
