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

import base64
import glob
import hmac
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
DASH_PASS = os.getenv("DASH_PASS", "")
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
sys.path.insert(0, APP_DIR)
import cluster_api  # noqa: E402  (API del clúster: maestro que reparte a las nubes)

STATIC = {"/": "index.html", "/index.html": "index.html",
          "/app.js": "app.js", "/cluster.js": "cluster.js", "/styles.css": "styles.css",
          "/secciones.js": "secciones.js", "/evaluacion.js": "evaluacion.js"}


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

    def auth_ok(self) -> bool:
        """Clave opcional del dashboard (DASH_PASS, usuario "adn"). /health queda libre."""
        if not DASH_PASS or urlparse(self.path).path == "/health":
            return True
        expected = "Basic " + base64.b64encode(f"adn:{DASH_PASS}".encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="ADN Multinube"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_POST(self):  # noqa: N802
        if not self.auth_ok():
            return
        url = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0:
            self.send(411, {"error": "Content-Length requerido"})
            return
        if url.path == "/api/subir":
            code, body = receive_upload(self, parse_qs(url.query), length)
            self.send(code, body)
            return
        if url.path.startswith("/api/eval/"):
            if length > 64 * 1024:
                self.send(413, {"error": "cuerpo demasiado grande"})
                return
            code, body = cluster_api.eval_post(url.path, self.rfile.read(length))
        elif url.path.startswith("/api/cluster/") or url.path in ("/api/ejecutar", "/api/cancelar"):
            if length > 1024 * 1024:
                self.send(413, {"error": "cuerpo demasiado grande"})
                return
            code, body = cluster_api.handle_post(url.path, parse_qs(url.query), self.rfile.read(length))
        else:
            code, body = 404, {"error": "no encontrado"}
        self.send(code, body)

    def do_GET(self):  # noqa: N802
        if not self.auth_ok():
            return
        url = urlparse(self.path)
        path = url.path
        if path in ("/api/cluster/estado", "/api/estado"):
            self.send(200, cluster_api.estado())
            return
        if path == "/api/eval":
            self.send(200, cluster_api.eval_estado())
            return
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
        if not any(p in first for p in ("/health", "/api/state", "/status", "/api/cluster/estado")):
            sys.stderr.write("[http] " + fmt % args + "\n")


def receive_upload(handler, query: dict, length: int):
    """POST /api/subir?archivo=NOMBRE  (cuerpo = el FASTA tal cual).

    El archivo llega a la nube a la que está conectado el navegador (por el túnel
    SSH) y se escribe en /datos por bloques de 4 MB: nunca se carga entero en RAM.
    Después se prepara (.seq + SHA-256) y desde la pestaña «Datos» se replica a
    las demás nubes por WireGuard."""
    import shutil  # noqa: PLC0415
    import worker as W  # noqa: PLC0415
    name = (query.get("archivo") or [""])[0].strip()
    if not W.FILE_RE.match(name):
        return 400, {"error": "nombre inválido: use letras, números, . _ - y extensión .fna .fa .fasta .fas .txt"}
    if length <= 0:
        return 411, {"error": "Content-Length requerido"}
    if not os.path.isdir(W.DATA_DIR):
        return 503, {"error": f"esta instancia no tiene carpeta de datos ({W.DATA_DIR})"}
    free = shutil.disk_usage(W.DATA_DIR).free
    need = int(length * 2.1)  # el archivo + su caché .seq limpia
    if free < need:
        return 507, {"error": f"disco insuficiente en {W.NODE_NAME}: hay {free / 1024**3:.1f} GB "
                              f"libres y se necesitan ≈ {need / 1024**3:.1f} GB (archivo + caché)"}
    final = os.path.join(W.DATA_DIR, name)
    tmp = final + ".subiendo"
    got, t0 = 0, time.time()
    W.FILE_STATE[name] = {"estado": "subiendo", "recibido": 0, "total": length}
    try:
        with open(tmp, "wb") as out:
            while got < length:
                chunk = handler.rfile.read(min(4 * 1024 * 1024, length - got))
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                W.FILE_STATE[name] = {"estado": "subiendo", "recibido": got, "total": length,
                                      "mb_s": round(got / 1024**2 / max(time.time() - t0, 1e-3), 1)}
        if got != length:
            raise OSError(f"subida incompleta ({got} de {length} bytes)")
        os.replace(tmp, final)
    except OSError as exc:
        W.FILE_STATE[name] = {"estado": "error", "error": str(exc)[:200]}
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 500, {"error": str(exc)}
    threading.Thread(target=W.prepare_file, args=(final,), daemon=True).start()
    secs = time.time() - t0
    return 201, {"mensaje": f"{name} recibido en {W.NODE_NAME} ({got / 1024**2:,.0f} MB en {secs:,.0f} s); "
                            "preparando la caché", "nodo": W.NODE_NAME, "bytes": got, "segundos": round(secs, 1)}


def make_server(port: int, bind: str = "0.0.0.0") -> ThreadingHTTPServer:
    for d in (os.path.dirname(DNA_FILE) or ".", OUTPUT_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    srv = ThreadingHTTPServer((bind, port), Handler)
    srv.daemon_threads = True
    return srv


def main() -> int:
    port = int(os.getenv("PORT", "8080"))
    cluster_api.init()    # si hay ETCD_ENDPOINTS (p. ej. por túnel SSH), muestra el clúster
    if os.getenv("AUTO_RUN", "false").lower() == "true":
        start_job({})
    print(f"Dashboard ADN en http://localhost:{port} "
          f"(nube: {os.getenv('CLOUD_PROVIDER', 'local')})", flush=True)
    make_server(port, os.getenv("DASH_BIND", "0.0.0.0")).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
