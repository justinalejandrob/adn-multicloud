#!/usr/bin/env python3
"""
compare_clouds.py - Compara los resultados del contenedor de ADN en cada nube.

Lee results/<nube>/*.json (los trae deploy_remote.sh) y genera en results/:
  - comparacion_nubes.csv  : tabla con tiempos, speedup, hardware por nube
  - comparacion_nubes.md   : misma tabla en Markdown + validación de integridad
  - grafico_tiempos.png    : secuencial vs. paralelo por nube
  - grafico_throughput.png : MB/s procesados por nube
  - grafico_speedup.png    : speedup vs. procesos (si se usó --mode benchmark)

La validación de integridad comprueba que TODAS las nubes obtuvieron
exactamente los mismos conteos: es la evidencia de que el contenedor es
portable (mismo código + mismos datos = mismo resultado en cualquier nube).

Uso:  python analysis/compare_clouds.py results
Requiere: pip install matplotlib
"""

from __future__ import annotations

import csv
import glob
import json
import os
import sys

# Paleta categórica validada (modo claro), en orden fijo.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
TEXT, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
KEYS = ("A", "C", "G", "T", "N", "invalid", "pattern_hits", "length", "records")


def load_latest(results_dir: str) -> dict[str, dict]:
    """Devuelve el JSON más reciente de cada proveedor."""
    latest: dict[str, dict] = {}
    files = glob.glob(os.path.join(results_dir, "**", "resultado_*.json"), recursive=True)
    for path in files:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        name = data["environment"]["cloud_provider"]
        ts = data["environment"]["timestamp_utc"]
        if name not in latest or ts > latest[name]["environment"]["timestamp_utc"]:
            latest[name] = data
    return latest


def run_of(data: dict, mode: str, workers: int | None = None) -> dict | None:
    runs = [r for r in data["runs"] if r["mode"] == mode]
    if workers is not None:
        runs = [r for r in runs if r["workers"] == workers]
    if not runs:
        return None
    return max(runs, key=lambda r: r["workers"])


def build_rows(latest: dict[str, dict]) -> list[dict]:
    rows = []
    for name, d in latest.items():
        env, seq, par = d["environment"], run_of(d, "sequential"), run_of(d, "parallel")
        rows.append({
            "nube": name,
            "origen": env.get("cloud_origin"),
            "region": env.get("cloud_region"),
            "tipo_vm": env.get("instance_type"),
            "arquitectura": env.get("architecture"),
            "cpu": env.get("cpu_model"),
            "nucleos": env.get("cpu_count"),
            "ram_gb": env.get("ram_gb"),
            "archivo_mb": round(d["input"]["size_bytes"] / 1024 / 1024, 1),
            "t_secuencial_s": seq["seconds"] if seq else "",
            "t_paralelo_s": par["seconds"] if par else "",
            "procesos": par["workers"] if par else 1,
            "speedup": par["speedup"] if par else "",
            "eficiencia": par["efficiency"] if par else "",
            "mb_s_paralelo": par["throughput_mb_s"] if par else (seq or {}).get("throughput_mb_s", ""),
            "invalidos": d["result"]["invalid"],
            "patron": d["result"]["pattern_hits"],
        })
    return sorted(rows, key=lambda r: r["nube"])


def integrity(latest: dict[str, dict]) -> tuple[bool, list[str]]:
    """Agrupa por tamaño de archivo y verifica que los conteos sean idénticos."""
    lines, all_ok = [], True
    groups: dict[int, list[str]] = {}
    for name, d in latest.items():
        groups.setdefault(d["input"]["size_bytes"], []).append(name)
    for size, names in sorted(groups.items()):
        ref = latest[names[0]]["result"]
        diffs = [n for n in names[1:]
                 if any(latest[n]["result"][k] != ref[k] for k in KEYS)]
        ok = not diffs
        all_ok &= ok
        estado = "IDÉNTICOS en todas las nubes" if ok else f"DIFERENCIAS en {', '.join(diffs)}"
        lines.append(f"- Archivo de {size / 1024 / 1024:,.1f} MB "
                     f"({', '.join(sorted(names))}): {estado}")
    return all_ok, lines


def write_tables(rows, latest, out_dir):
    csv_path = os.path.join(out_dir, "comparacion_nubes.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    ok, lines = integrity(latest)
    cols = ["nube", "origen", "region", "arquitectura", "nucleos", "ram_gb",
            "archivo_mb", "t_secuencial_s", "t_paralelo_s", "procesos",
            "speedup", "eficiencia", "mb_s_paralelo"]
    md = ["# Comparación del contenedor de ADN entre nubes", "",
          "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    md += ["", "## Validación de integridad (portabilidad)", ""] + lines
    md_path = os.path.join(out_dir, "comparacion_nubes.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))
    return ok


def style_axes(ax, title, ylabel):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=TEXT, fontsize=13, pad=30)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0)


def charts(rows, latest, out_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib no instalado: se omiten los gráficos (pip install matplotlib)")
        return

    names = [r["nube"] for r in rows]
    x = range(len(names))

    # 1) Tiempos secuencial vs paralelo (dos series, mismo eje)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.36
    seq = [r["t_secuencial_s"] or 0 for r in rows]
    par = [r["t_paralelo_s"] or 0 for r in rows]
    b1 = ax.bar([i - width / 2 - 0.01 for i in x], seq, width, color=SERIES[0],
                label="Secuencial (1 proceso)")
    b2 = ax.bar([i + width / 2 + 0.01 for i in x], par, width, color=SERIES[1],
                label="Paralelo (todos los núcleos)")
    for bars in (b1, b2):
        ax.bar_label(bars, fmt="%.1f s", padding=3, color=TEXT, fontsize=9)
    ax.set_xticks(list(x), names)
    style_axes(ax, "Tiempo de procesamiento del ADN por nube", "segundos (menos es mejor)")
    ax.set_ylim(0, max(seq + par + [1]) * 1.15)
    ax.legend(frameon=False, labelcolor=TEXT, ncol=2, loc="lower left",
              bbox_to_anchor=(0, 1.0), borderaxespad=0.2)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "grafico_tiempos.png"), dpi=160)
    plt.close(fig)

    # 2) Throughput (una sola serie: sin leyenda)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    vals = [r["mb_s_paralelo"] or 0 for r in rows]
    bars = ax.bar(list(x), vals, 0.5, color=SERIES[0])
    ax.bar_label(bars, fmt="%.1f", padding=3, color=TEXT, fontsize=9)
    ax.set_xticks(list(x), names)
    style_axes(ax, "Velocidad de procesamiento en paralelo", "MB/s (más es mejor)")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "grafico_throughput.png"), dpi=160)
    plt.close(fig)

    # 3) Speedup vs procesos (solo si hay benchmark con varios procesos)
    series = {n: [r for r in latest[n]["runs"]] for n in names}
    if any(len(v) > 2 for v in series.values()):
        fig, ax = plt.subplots(figsize=(8, 4.5))
        max_w = 1
        for i, n in enumerate(names[:4]):
            pts = sorted({r["workers"]: r["speedup"] for r in series[n]}.items())
            xs, ys = zip(*pts)
            max_w = max(max_w, max(xs))
            ax.plot(xs, ys, color=SERIES[i], linewidth=2, marker="o", markersize=6,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, label=n)
        ax.plot([1, max_w], [1, max_w], color=MUTED, linewidth=1, linestyle="--",
                label="Speedup ideal")
        style_axes(ax, "Speedup vs. número de procesos", "speedup (veces)")
        ax.set_xlabel("procesos", color=MUTED)
        ax.legend(frameon=False, labelcolor=TEXT)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, "grafico_speedup.png"), dpi=160)
        plt.close(fig)
    print(f"\nGráficos guardados en {out_dir}")


def main() -> int:
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    latest = load_latest(results_dir)
    if not latest:
        print(f"No hay resultados en {results_dir}")
        return 1
    rows = build_rows(latest)
    ok = write_tables(rows, latest, results_dir)
    charts(rows, latest, results_dir)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
