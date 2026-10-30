#!/usr/bin/env python3
"""
server.py - Modo servidor HTTP + dashboard web del procesador de ADN.

Sirve para dos cosas:
  1. Nubes PaaS (GuaraCloud, Railway, Heroku...): no dan VM ni SSH, arrancan
     el contenedor y esperan que escuche en un puerto HTTP.
  2. Interfaz gráfica: un dashboard (app/web/) para lanzar el procesamiento,
     ver el avance en tiempo real y comparar las nubes.

API (JSON):
  GET /api/info      Nube, hardware, fuente del ADN y archivo preparado
  GET /api/state     Estado del trabajo, fase, % de avance y log
  GET /api/results   TODOS los resultados de OUTPUT_DIR (incluye subcarpetas
                     results/<nube>/ traídas por los scripts de despliegue)
  GET /run           Lanza preparar + procesar en segundo plano
                     Parámetros: limit_mb (genoma real) | size (sintético),
                     mode, workers, chunk_mb, pattern
Compatibilidad (scripts/run_paas.sh):
  GET /health  /status  /results

Solo usa la biblioteca estándar de Python (sin dependencias extra).
"""

from __future__ import annotations

import glob
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")
DNA_FILE = os.getenv("DNA_FILE", "/data/adn.txt")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/results")
MAX_SIZE_MB = int(os.getenv("MAX_SIZE_MB", "4096"))  # límite del ADN sintético
SIZE_RE = re.compile(r"^\d+(\.\d+)?(B|KB|MB|GB)$", re.IGNORECASE)
PROGRESS_RE = re.compile(r"^@@progress (\S+):(\d+) (\d+) (\d+)$")
DOWNLOAD_RE = re.compile(r"descargado ([\d,.]+) MB\s*([\d.]+)?\s*%?.*?escrito ([\d,.]+) MB.*?([\d,.]+) MB/s")
GENERATE_RE = re.compile(r"generado ([\d,.]+) / ([\d,.]+) MB")
STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

STATE = {"status": "idle", "phase": None, "progress": None, "started": None,
         "finished": None, "seconds": None, "params": None, "log": [],
         "error": None, "steps": {}}
LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Ejecución de los pasos (subprocesos) y lectura del avance
# ---------------------------------------------------------------------------
def to_float(text: str) -> float:
    return float(text.replace(",", ""))


def handle_line(line: str) -> None:
    """Interpreta una línea de salida: avance o log normal."""
    m = PROGRESS_RE.match(line)
    with LOCK:
        if m:
            mode, workers, done, total = m.groups()
            pct = int(done) / int(total) * 100
            STATE["phase"] = mode
            STATE["progress"] = {"label": mode, "workers": int(workers),
                                 "done": int(done), "total": int(total),
                                 "pct": round(pct, 1)}
            STATE["steps"][f"{mode}:{workers}"] = round(pct, 1)
            return
        m = DOWNLOAD_RE.search(line)
        if m:
            received, pct, written, speed = m.groups()
            STATE["phase"] = "download"
            STATE["progress"] = {"label": "download", "pct": float(pct) if pct else None,
                                 "mb": to_float(written), "speed": to_float(speed)}
            STATE["steps"]["prepare"] = float(pct) if pct else None
            return
        m = GENERATE_RE.search(line)
        if m:
            done, total = to_float(m.group(1)), to_float(m.group(2))
            pct = done / total * 100 if total else 0
            STATE["phase"] = "generate"
            STATE["progress"] = {"label": "generate", "pct": round(pct, 1), "mb": done}
            STATE["steps"]["prepare"] = round(pct, 1)
            return
        if line.strip():
            STATE["log"].append(line)
            STATE["log"] = STATE["log"][-300:]


def run_step(cmd: list[str]) -> int:
    """Ejecuta un paso como subproceso y procesa su salida línea a línea.

    text=True usa "universal newlines": las actualizaciones con '\\r' de la
    descarga llegan como líneas separadas y se convierten en % de avance.
    """
    env = dict(os.environ, DNA_PROGRESS="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, cwd=APP_DIR, stdout=subprocess.PIPE, env=env,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        line = line.rstrip()
        if not line.startswith("@@progress"):
            print(line, flush=True)  # también aparece en los logs de la nube
        handle_line(line)
    return proc.wait()


def job(params: dict) -> None:
    t0 = time.perf_counter()
    try:
        if os.getenv("DNA_URL"):
            # La URL se configura SOLO como variable de entorno del servidor
            # (nunca desde el navegador -> evita que se descarguen URLs ajenas)
            prep = [sys.executable, "fetch_dna.py", "--output", DNA_FILE,
                    "--limit-mb", params["limit_mb"]]
        else:
            prep = [sys.executable, "generate_dna.py", "--size", params["size"],
                    "--output", DNA_FILE, "--seed", os.getenv("SEED", "2026")]
        proc = [sys.executable, "dna_processor.py", "--input", DNA_FILE,
                "--mode", params["mode"], "--chunk-mb", params["chunk_mb"],
                "--pattern", params["pattern"], "--output", OUTPUT_DIR]
        if params["workers"] != "0":
            proc += ["--workers", params["workers"]]
        with LOCK:
            STATE["phase"] = "prepare"
        rc = run_step(prep)
        if rc == 0:
            with LOCK:
                STATE["steps"]["prepare"] = 100.0
                STATE["phase"], STATE["progress"] = "process", None
            rc = run_step(proc)
        with LOCK:
            STATE["status"] = "done" if rc == 0 else "error"
            STATE["error"] = None if rc == 0 else f"el proceso terminó con código {rc}"
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            STATE["status"], STATE["error"] = "error", str(exc)
    finally:
        with LOCK:
            STATE["phase"] = None
            STATE["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            STATE["seconds"] = round(time.perf_counter() - t0, 2)


def size_mb(text: str) -> float:
    text = text.upper()
    for unit, m in (("GB", 1024), ("MB", 1), ("KB", 1 / 1024), ("B", 1 / 1024**2)):
        if text.endswith(unit):
            return float(text[: -len(unit)]) * m
    return 0


def start_job(query: dict) -> tuple[int, dict]:
    def q(name, env, default):
        return str(query.get(name, [os.getenv(env, default)])[0]).strip()

    params = {
        "size": q("size", "DNA_SIZE", "100MB"),
        "mode": q("mode", "MODE", "both"),
        "workers": q("workers", "WORKERS", "0"),
        "chunk_mb": q("chunk_mb", "CHUNK_MB", "32"),
        "pattern": q("pattern", "PATTERN", "GATTACA").upper(),
        "limit_mb": q("limit_mb", "DNA_LIMIT_MB", "0"),
        "source": "url" if os.getenv("DNA_URL") else "sintetico",
    }
    # Validación (los parámetros llegan desde una URL pública)
    if not SIZE_RE.match(params["size"]) or size_mb(params["size"]) > MAX_SIZE_MB:
        return 400, {"error": f"Tamaño inválido o mayor a {MAX_SIZE_MB} MB"}
    if params["mode"] not in ("sequential", "parallel", "both", "benchmark"):
        return 400, {"error": "Modo inválido"}
    if not all(params[k].isdigit() for k in ("workers", "chunk_mb", "limit_mb")):
        return 400, {"error": "Trabajadores, bloque y límite deben ser enteros"}
    if not 1 <= int(params["chunk_mb"]) <= 512:
        return 400, {"error": "El bloque debe estar entre 1 y 512 MB"}
    if int(params["workers"]) > 256:
        return 400, {"error": "Máximo 256 trabajadores"}
    if not re.fullmatch(r"[ACGTN]{1,64}", params["pattern"]):
        return 400, {"error": "El patrón solo admite A, C, G, T, N (máx. 64)"}

    with LOCK:
        if STATE["status"] == "running":
            return 409, {"error": "Ya hay un procesamiento en curso"}
        STATE.update(status="running", phase="prepare", progress=None, params=params,
                     log=[], error=None, steps={},
                     started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     finished=None, seconds=None)
    threading.Thread(target=job, args=(params,), daemon=True).start()
    return 202, {"message": "procesamiento iniciado", "params": params,
                 "status_url": "/status", "results_url": "/results"}


# ---------------------------------------------------------------------------
# Lectura de resultados e información del entorno
# ---------------------------------------------------------------------------
def result_files() -> list[str]:
    files = glob.glob(os.path.join(OUTPUT_DIR, "**", "resultado_*.json"), recursive=True)
    return sorted(files, key=os.path.getmtime)[-500:]


def load_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["_file"] = os.path.relpath(path, OUTPUT_DIR)
        return data
    except (OSError, ValueError):
        return None


def latest_result() -> dict | None:
    for path in reversed(result_files()):
        data = load_json(path)
        if data:
            data.pop("_file", None)
            return data
    return None


def info() -> dict:
    sys.path.insert(0, APP_DIR)
    import dna_processor  # noqa: E402  (reutiliza la detección de hardware)

    env = dna_processor.environment_info()
    dna = {"exists": os.path.isfile(DNA_FILE), "size_bytes": None, "sha256": None,
           "download_seconds": None}
    if dna["exists"]:
        dna["size_bytes"] = os.path.getsize(DNA_FILE)
        dna["sha256"] = dna_processor.read_side_file(DNA_FILE + ".sha256", first_word=True)
        dna["download_seconds"] = dna_processor.read_side_file(
            DNA_FILE + ".download_seconds", as_float=True)
    return {
        "environment": env,
        "source": "url" if os.getenv("DNA_URL") else "sintetico",
        "source_host": urlparse(os.getenv("DNA_URL", "")).netloc or None,
        "dna_file": dna,
        "defaults": {"limit_mb": os.getenv("DNA_LIMIT_MB", "0"),
                     "size": os.getenv("DNA_SIZE", "100MB"),
                     "mode": os.getenv("MODE", "both"),
                     "workers": os.getenv("WORKERS", "0"),
                     "chunk_mb": os.getenv("CHUNK_MB", "32"),
                     "pattern": os.getenv("PATTERN", "GATTACA")},
        "server_started": STARTED_AT,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
STATIC = {"/": "index.html", "/index.html": "index.html",
          "/app.js": "app.js", "/styles.css": "styles.css"}


class Handler(BaseHTTPRequestHandler):
    def send(self, code: int, body, ctype="application/json"):
        if ctype == "application/json":
            body = json.dumps(body, indent=2, ensure_ascii=False)
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        path = url.path
        if path == "/health":
            self.send(200, "ok", "text/plain")
        elif path == "/run":
            code, body = start_job(parse_qs(url.query))
            if "text/html" in self.headers.get("Accept", "") and code == 202:
                self.send_response(303)
                self.send_header("Location", "/#adn")
                self.end_headers()
            else:
                self.send(code, body)
        elif path in ("/status", "/api/state"):
            with LOCK:
                self.send(200, json.loads(json.dumps(STATE)))
        elif path == "/results":
            res = latest_result()
            self.send(200 if res else 404, res or {"error": "sin resultados aún"})
        elif path == "/api/results":
            data = [d for d in (load_json(p) for p in result_files()) if d]
            self.send(200, {"results": data})
        elif path == "/api/info":
            self.send(200, info())
        elif path in STATIC:
            name = STATIC[path]
            try:
                with open(os.path.join(WEB_DIR, name), "rb") as fh:
                    body = fh.read()
            except OSError:
                self.send(404, {"error": f"falta app/web/{name}"})
                return
            ctype = mimetypes.guess_type(name)[0] or "text/plain"
            self.send(200, body, ctype)
        else:
            self.send(404, {"error": "no encontrado"})

    def do_HEAD(self):  # noqa: N802  (algunas PaaS verifican la salud con HEAD)
        self.send_response(200 if urlparse(self.path).path in ("/health", "/", *STATIC) else 404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        first = str(args[0]) if args else ""
        if not any(p in first for p in ("/health", "/api/state", "/status")):
            sys.stderr.write("[http] " + fmt % args + "\n")


def main() -> int:
    os.makedirs(os.path.dirname(DNA_FILE) or ".", exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    port = int(os.getenv("PORT", "8080"))
    if os.getenv("AUTO_RUN", "false").lower() == "true":
        start_job({})
    print(f"Dashboard ADN en http://localhost:{port} "
          f"(nube: {os.getenv('CLOUD_PROVIDER', 'local')})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
