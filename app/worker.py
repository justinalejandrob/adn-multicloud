#!/usr/bin/env python3
"""
worker.py - Nodo de cómputo del clúster ADN (contenedor "adn-worker", puerto 8000).

Corre IGUAL en las 5 nubes (América, China, Latinoamérica, Ecuador, Europa).
Lo único que cambia por nodo son las variables de entorno:
    NODE_NAME      nombre del nodo (ej. nodo-europa)
    CLUSTER_TOKEN  clave compartida del clúster (obligatoria, nunca en el código)
    CLOUD_PROVIDER, CLOUD_ORIGIN (país), CLOUD_REGION, INSTANCE_TYPE, COST_HOUR

Recibe "pedazos" de ADN ya limpio (sin encabezados ni saltos de línea; los
cromosomas van separados por el byte 0x00) y los calcula con TODOS sus núcleos
(ProcessPoolExecutor). Los workers no se hablan entre sí: solo el maestro les
habla por HTTP.

Endpoints:
  GET  /health   (sin token)  {"node","cpus",...}
  GET  /stats    (token)      CPU total y por núcleo, procesos del pool, RAM,
                              carga, red rx/tx, contadores de trabajo
  POST /count    (token)      cuerpo = pedazo  -> A,C,G,T,N,otros,total,...
                              cabeceras opcionales: X-Overlap (bytes finales que
                              solo sirven de contexto), X-Pattern (patrón)
  POST /pattern  (token)      igual que /count pero solo cuenta el patrón
  POST /compare  (token)      cuerpo = pedazo A + pedazo B, cabecera X-Len-A
                              -> comparadas, iguales, diferentes, sobrantes
  POST /sink     (token)      mide la velocidad de SUBIDA (descarta el cuerpo)
  GET  /archivo?nombre=X (token) entrega un FASTA de /datos a otra nube
  GET  /source?mb=N (token)   mide la velocidad de BAJADA (envía N MB)
  POST /eval/<medición> (token) mediciones de la Evaluación S11 (evaluacion.py)
"""

from __future__ import annotations

import hmac
import json
import os
import platform
import socket
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = "2.0"
SEP = b"\x00"            # separador de registros FASTA en el ADN limpio
VALID = b"ACGTN"
MB = 1024 * 1024
NODE_NAME = os.getenv("NODE_NAME") or socket.gethostname()
TOKEN = os.getenv("CLUSTER_TOKEN", "")
PORT = int(os.getenv("WORKER_PORT") or os.getenv("PORT") or 8000)
MAX_BODY = int(os.getenv("MAX_BODY_MB", "300")) * MB
CPUS = os.cpu_count() or 1
MIN_PART = 1 * MB        # no se divide entre núcleos un pedazo más chico que esto


# =============================================================================
# Funciones puras (se ejecutan en los procesos del pool)
# =============================================================================
def count_region(data: bytes, overlap: int = 0, pattern: bytes = b"", patterns=None) -> dict:
    """Cuenta bases en data[:len-overlap] y los patrones que EMPIECEN en esa zona.

    Los últimos `overlap` bytes solo sirven de contexto para encontrar un patrón
    que cruza al pedazo siguiente (así no se cuenta dos veces ni se pierde).
    """
    end = len(data) - overlap
    region = data[:end]
    upper = region.upper()
    seps = region.count(SEP)
    a, c, g, t, n = (upper.count(bytes([x])) for x in VALID)
    lower = sum(region.count(x) for x in (b"a", b"c", b"g", b"t"))
    otros_bytes = upper.translate(None, VALID + SEP)
    pats = [p for p in (patterns or ([pattern] if pattern else [])) if p]
    found = {}
    if pats:
        window = upper + data[end:].upper()
        for pat in pats:
            hits, i = 0, window.find(pat)
            while i != -1 and i < end:
                hits += 1
                i = window.find(pat, i + 1)
            found[pat.decode()] = hits
    return {"A": a, "C": c, "G": g, "T": t, "N": n, "otros": len(otros_bytes),
            "total": end - seps, "registros": seps, "minusculas": lower,
            "patron": found[pats[0].decode()] if pats else 0, "patrones": found,
            "detalle_otros": {chr(k): v for k, v in Counter(otros_bytes).items()}}


def compare_region(a: bytes, b: bytes) -> dict:
    """Compara posición a posición (sin distinguir mayúsculas)."""
    import numpy as np  # noqa: PLC0415  (solo en los procesos que comparan)

    n = min(len(a), len(b))
    x = np.frombuffer(a[:n].upper(), dtype=np.uint8)
    y = np.frombuffer(b[:n].upper(), dtype=np.uint8)
    iguales = int(np.count_nonzero(x == y))
    return {"comparadas": n, "iguales": iguales, "diferentes": n - iguales,
            "sobrantes": abs(len(a) - len(b))}


SUM_KEYS = ("A", "C", "G", "T", "N", "otros", "total", "registros", "minusculas", "patron")


def merge_counts(parts) -> dict:
    out = {k: 0 for k in SUM_KEYS}
    det: Counter = Counter()
    pats: Counter = Counter()
    for p in parts:
        for k in SUM_KEYS:
            out[k] += p.get(k, 0)
        det.update(p.get("detalle_otros", {}))
        pats.update(p.get("patrones", {}))
    out["detalle_otros"] = dict(det)
    out["patrones"] = dict(pats)
    return out


def _warmup(_):
    time.sleep(0.2)
    return os.getpid()


# =============================================================================
# Estado del nodo y monitoreo de recursos (/proc, sin dependencias)
# =============================================================================
POOL: ProcessPoolExecutor | None = None
LOCK = threading.Lock()
WORK = {"activos": 0, "pedazos": 0, "bytes": 0, "seg_calculo": 0.0, "errores": 0}
STATS: dict = {}
STARTED = time.time()
OFFLINE = False          # "Apagar nube" (simulado): el nodo rechaza trabajo
CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def split_parts(n_bytes: int) -> list[tuple[int, int]]:
    """Divide [0, n) en tantos trozos como núcleos (si vale la pena)."""
    k = max(1, min(CPUS, n_bytes // MIN_PART))
    step = -(-n_bytes // k)
    return [(i, min(i + step, n_bytes)) for i in range(0, n_bytes, step)] or [(0, 0)]


def parallel_count(data: bytes, overlap: int, pattern=b"") -> dict:
    """pattern puede ser un patrón (bytes) o una lista/tupla de patrones."""
    pats = tuple(pattern) if isinstance(pattern, (list, tuple)) else ((pattern,) if pattern else ())
    end = len(data) - overlap
    ctx = max((len(p) for p in pats), default=1) - 1
    parts = split_parts(end)
    if len(parts) == 1 or POOL is None:
        return count_region(data, overlap, patterns=pats)
    jobs = []
    for s, e in parts:
        stop = min(e + ctx, len(data))
        jobs.append(POOL.submit(count_region, data[s:stop], stop - e, b"", pats))
    return merge_counts(j.result() for j in jobs)


def parallel_compare(a: bytes, b: bytes) -> dict:
    n = min(len(a), len(b))
    parts = split_parts(n)
    if len(parts) == 1 or POOL is None:
        return compare_region(a, b)
    jobs = [POOL.submit(compare_region, a[s:e], b[s:e]) for s, e in parts]
    out = {"comparadas": 0, "iguales": 0, "diferentes": 0}
    for j in jobs:
        r = j.result()
        for k in out:
            out[k] += r[k]
    out["sobrantes"] = abs(len(a) - len(b))
    return out


def read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def cpu_times() -> dict[str, tuple[int, int]]:
    """{'cpu': (ocupado, total), 'cpu0': ...} desde /proc/stat."""
    out = {}
    for line in read_file("/proc/stat").splitlines():
        if not line.startswith("cpu"):
            break
        name, *vals = line.split()
        v = [int(x) for x in vals[:8]]
        total = sum(v)
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        out[name] = (total - idle, total)
    return out


def proc_times(pid: int) -> tuple[int, int, str] | None:
    """(utime+stime en ticks, núcleo donde corrió por última vez, estado)."""
    raw = read_file(f"/proc/{pid}/stat")
    if not raw:
        return None
    f = raw.rsplit(")", 1)[1].split()
    return int(f[11]) + int(f[12]), int(f[36]), f[0]


def net_bytes() -> tuple[int, int]:
    rx = tx = 0
    for line in read_file("/proc/net/dev").splitlines()[2:]:
        name, data = line.split(":", 1)
        if name.strip() == "lo":
            continue
        v = data.split()
        rx += int(v[0])
        tx += int(v[8])
    return rx, tx


def meminfo() -> tuple[float, float]:
    info = {}
    for line in read_file("/proc/meminfo").splitlines():
        k, v = line.split(":", 1)
        info[k] = int(v.split()[0]) * 1024
    total = info.get("MemTotal", 0)
    used = total - info.get("MemAvailable", info.get("MemFree", 0))
    return total, used


def cpu_identity() -> tuple[str, int]:
    model, phys = "desconocido", set()
    cur = {}
    for line in read_file("/proc/cpuinfo").splitlines() + [""]:
        if not line.strip():
            if "core id" in cur:
                phys.add((cur.get("physical id", "0"), cur["core id"]))
            cur = {}
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        cur[k] = v
        if k in ("model name", "cpu model") and model == "desconocido":
            model = v
    if model == "desconocido":
        model = platform.processor() or platform.machine()
    return model, len(phys) or CPUS


MODEL, PHYSICAL = cpu_identity()
EXTRA = {"potencia_gflops": None}


def measure_gflops(seconds: float = 0.6) -> float | None:
    """Potencia aproximada: multiplicación de matrices con numpy (GFLOPS)."""
    try:
        import numpy as np  # noqa: PLC0415
        n = 384
        a, b = np.random.rand(n, n), np.random.rand(n, n)
        reps, t0 = 0, time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            a @ b
            reps += 1
        return round(2 * n ** 3 * reps / (time.perf_counter() - t0) / 1e9, 1)
    except Exception:  # noqa: BLE001
        return None


def has_gpu() -> str:
    if os.path.exists("/dev/nvidia0") or os.path.exists("/proc/driver/nvidia"):
        return "NVIDIA"
    return "no tiene"


def sampler(interval: float = 1.0) -> None:
    """Hilo que mide cada segundo: CPU por núcleo, procesos del pool y red."""
    prev_cpu, prev_net, prev_t = cpu_times(), net_bytes(), time.time()
    prev_proc: dict[int, int] = {}
    while True:
        time.sleep(interval)
        now, cur_cpu, cur_net = time.time(), cpu_times(), net_bytes()
        dt = max(now - prev_t, 1e-6)

        def pct(name):
            b0, t0 = prev_cpu.get(name, (0, 0))
            b1, t1 = cur_cpu.get(name, (0, 0))
            return round(100 * (b1 - b0) / (t1 - t0), 1) if t1 > t0 else 0.0

        cores = [pct(f"cpu{i}") for i in range(CPUS) if f"cpu{i}" in cur_cpu]
        procs, cur_proc = [], {}
        pids = list(getattr(POOL, "_processes", {}) or {}) if POOL else []
        for pid in pids:
            info = proc_times(pid)
            if not info:
                continue
            ticks, core, state = info
            cur_proc[pid] = ticks
            used = (ticks - prev_proc.get(pid, ticks)) / CLK / dt * 100
            procs.append({"pid": pid, "nucleo": core, "cpu": round(used, 1), "estado": state})
        mem_total, mem_used = meminfo()
        load = read_file("/proc/loadavg").split()[:3]
        with LOCK:
            STATS.update({
                "cpu": pct("cpu"), "nucleos": cores, "procesos": procs,
                "mem_total": mem_total, "mem_usada": mem_used,
                "carga": [float(x) for x in load] if load else [],
                "rx_bps": round((cur_net[0] - prev_net[0]) / dt),
                "tx_bps": round((cur_net[1] - prev_net[1]) / dt),
            })
        prev_cpu, prev_net, prev_t, prev_proc = cur_cpu, cur_net, now, cur_proc


def node_info() -> dict:
    return {
        "node": NODE_NAME, "cpus": CPUS, "fisicos": PHYSICAL, "modelo": MODEL,
        "version": VERSION, "arquitectura": platform.machine(),
        "provider": os.getenv("CLOUD_PROVIDER", "desconocido"),
        "pais": os.getenv("CLOUD_ORIGIN", "desconocido"),
        "region": os.getenv("CLOUD_REGION", "desconocida"),
        "instancia": os.getenv("INSTANCE_TYPE", "desconocido"),
        "costo_hora": float(os.getenv("COST_HOUR", "0") or 0),
        "costo_mes": float(os.getenv("COST_MONTH", "0") or 0),
        "cobro": os.getenv("BILLING", ""),            # crédito / tarjeta / estimado
        "ip_publica": os.getenv("PUBLIC_IP", ""),
        "ip_privada": os.getenv("PRIVATE_IP", ""),
        "procesos": CPUS, "gpu": has_gpu(),
        "potencia_gflops": EXTRA.get("potencia_gflops"),
    }


# =============================================================================
# Archivos locales del nodo (datos replicados en cada nube)
# =============================================================================
import re  # noqa: E402

DATA_DIR = os.getenv("DATA_DIR", "/datos")
FILE_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.(fasta|fa|fna|fas|txt)$", re.IGNORECASE)
FILE_STATE: dict[str, dict] = {}       # preparando / descargando / error


def parse_patterns(value) -> tuple:
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    pats = []
    for v in value or []:
        v = str(v).strip().upper()
        if not v:
            continue
        if not re.fullmatch(r"[ACGTN]{1,64}", v):
            raise ValueError(f"patrón inválido: {v}")
        if v.encode() not in pats:
            pats.append(v.encode())
    return tuple(pats[:10])


def data_path(name: str) -> str:
    if not FILE_RE.match(name or ""):
        raise ValueError(f"nombre de archivo inválido: {name!r}")
    fp = os.path.join(DATA_DIR, name)
    if not os.path.isfile(fp):
        raise ValueError(f"{name} no existe en {NODE_NAME}")
    return fp


def ready_meta(name: str, expected_sha: str | None = None) -> dict:
    import seqcache  # noqa: PLC0415
    meta = seqcache.cached_meta(data_path(name))
    if not meta:
        raise ValueError(f"{name} no está listo en {NODE_NAME} (falta preparar la caché)")
    if expected_sha and meta.get("seq_sha256") != expected_sha:
        raise ValueError(f"{name} en {NODE_NAME} es distinto (SHA-256 no coincide)")
    return meta


def prepare_file(fp: str) -> None:
    import seqcache  # noqa: PLC0415
    name = os.path.basename(fp)
    FILE_STATE[name] = {"estado": "preparando"}
    try:
        seqcache.seq_cache(fp, log=lambda *_: None)
        FILE_STATE.pop(name, None)
    except Exception as exc:  # noqa: BLE001
        FILE_STATE[name] = {"estado": "error", "error": str(exc)}


def download_file(url: str, name: str, headers: dict | None = None) -> None:
    """Descarga a /datos (desde Dropbox/OneDrive o desde OTRA nube por WireGuard)."""
    import fetch_dna  # noqa: PLC0415
    FILE_STATE[name] = {"estado": "descargando"}
    t0 = time.time()

    def progress(got, total):
        FILE_STATE[name] = {"estado": "descargando", "recibido": got, "total": total,
                            "mb_s": round(got / MB / max(time.time() - t0, 1e-3), 1)}
    try:
        fetch_dna.download(fetch_dna.direct_link(url), os.path.join(DATA_DIR, name), 0,
                           headers=headers, progress=progress)
        prepare_file(os.path.join(DATA_DIR, name))
    except Exception as exc:  # noqa: BLE001
        FILE_STATE[name] = {"estado": "error", "error": str(exc)[:300]}
        try:
            os.remove(os.path.join(DATA_DIR, name) + ".part")
        except OSError:
            pass


def list_data_files() -> list[dict]:
    import seqcache  # noqa: PLC0415
    out = []
    names = set(FILE_STATE)
    if os.path.isdir(DATA_DIR):
        names |= {n for n in os.listdir(DATA_DIR) if FILE_RE.match(n)}
    for name in sorted(names):
        fp = os.path.join(DATA_DIR, name)
        meta = seqcache.cached_meta(fp) if os.path.isfile(fp) else None
        row = {"nombre": name, "bytes": os.path.getsize(fp) if os.path.isfile(fp) else None,
               "listo": bool(meta), **FILE_STATE.get(name, {})}
        if meta:
            row.update(seq_size=meta["seq_size"], seq_sha256=meta.get("seq_sha256"),
                       src_sha256=meta["src_sha256"], registros=meta["records"])
        out.append(row)
    return out


# =============================================================================
# HTTP
# =============================================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # conexiones persistentes (menos latencia)
    server_version = "adn-worker/" + VERSION

    def setup(self):
        super().setup()
        # Sin Nagle: respuestas pequeñas salen de inmediato (si no, el ACK
        # retardado de TCP agrega ~40 ms y falsea la medición de latencia).
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def reply(self, code: int, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self) -> bool:
        given = self.headers.get("X-Token", "")
        if TOKEN and hmac.compare_digest(given.encode(), TOKEN.encode()):
            return True
        self.reply(401, {"error": "token inválido o ausente (cabecera X-Token)"})
        return False

    def send_data_file(self, name: str, offset: int = 0, length: int = -1) -> None:
        try:
            fp = data_path(name)
            total = os.path.getsize(fp)
        except (ValueError, OSError):
            self.reply(404, {"error": f"{name} no existe en {NODE_NAME}"})
            return
        offset = max(0, min(offset, total))
        size = total - offset if length < 0 else max(0, min(length, total - offset))
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(fp, "rb") as fh:
            try:
                self.wfile.flush()
                sent = 0
                while sent < size:  # sendfile puede enviar menos de lo pedido
                    n = os.sendfile(self.connection.fileno(), fh.fileno(), offset + sent, min(size - sent, 64 * MB))
                    if n == 0:
                        break
                    sent += n
            except (BrokenPipeError, ConnectionResetError):
                pass

    def read_body(self) -> bytes | None:
        try:
            n = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.reply(413 if n > MAX_BODY else 411,
                       {"error": f"Content-Length requerido y <= {MAX_BODY // MB} MB"})
            return None
        buf = bytearray()
        while len(buf) < n:
            chunk = self.rfile.read(min(4 * MB, n - len(buf)))
            if not chunk:
                break
            buf += chunk
        return bytes(buf)

    def read_json(self) -> dict | None:
        body = self.read_body()
        if body is None:
            return None
        try:
            return json.loads(body or b"{}")
        except ValueError:
            self.reply(400, {"error": "JSON inválido"})
            return None

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/health":
            self.reply(200, node_info())
        elif url.path == "/archivos":
            if self.authorized():
                self.reply(200, {"node": NODE_NAME, "archivos": list_data_files()})
        elif url.path == "/stats":
            if not self.authorized():
                return
            with LOCK:
                data = dict(STATS, **WORK)
            data.update(node_info(), uptime=round(time.time() - STARTED),
                        seg_calculo=round(data["seg_calculo"], 3))
            self.reply(200, data)
        elif url.path == "/archivo":
            # entrega un FASTA de /datos a otra nube del clúster (replicación por WireGuard);
            # con offset y longitud entrega solo un bloque (recuperación de una réplica, pregunta 6)
            if self.authorized():
                q = parse_qs(url.query)
                try:
                    off = int((q.get("offset") or ["0"])[0])
                    n = int((q.get("longitud") or ["-1"])[0])
                except ValueError:
                    self.reply(400, {"error": "offset y longitud deben ser enteros"})
                    return
                self.send_data_file((q.get("nombre") or [""])[0], off, n)
        elif url.path == "/source":
            if not self.authorized():
                return
            mb = min(max(int((parse_qs(url.query).get("mb") or ["8"])[0] or 8), 1), 64)
            self.reply(200, b"\0" * (mb * MB), "application/octet-stream")
        else:
            self.reply(404, {"error": "no encontrado"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if OFFLINE and path != "/sink":
            self.reply(503, {"error": f"{NODE_NAME} está apagada (simulado)", "node": NODE_NAME})
            return
        if path.startswith("/eval/"):
            # mediciones de la Evaluación S11 (evaluacion.py): las pide el dashboard por WireGuard
            if self.authorized():
                params = self.read_json()
                if params is not None:
                    import evaluacion  # noqa: PLC0415
                    try:
                        self.reply(200, evaluacion.local(path[len("/eval/"):], params,
                                                         {"nodo": NODE_NAME, "token": TOKEN}))
                    except Exception as exc:  # noqa: BLE001
                        self.reply(400, {"error": str(exc)[:300], "node": NODE_NAME})
            return
        if path in ("/count_ref", "/compare_ref", "/preparar", "/descargar"):
            if self.authorized():
                params = self.read_json()
                if params is not None:
                    self.handle_ref(path, params)
            return
        if path not in ("/count", "/pattern", "/compare", "/sink"):
            self.reply(404, {"error": "no encontrado"})
            return
        if not self.authorized():
            return
        t_read = time.perf_counter()
        body = self.read_body()
        if body is None:
            return
        t0 = time.perf_counter()
        if path == "/sink":
            self.reply(200, {"node": NODE_NAME, "bytes": len(body),
                             "segundos_lectura": round(t0 - t_read, 6)})
            return
        with LOCK:
            WORK["activos"] += 1
        try:
            if path == "/compare":
                la = int(self.headers.get("X-Len-A", "-1"))
                if not 0 <= la <= len(body):
                    raise ValueError("X-Len-A inválido")
                result = parallel_compare(body[:la], body[la:])
            else:
                overlap = int(self.headers.get("X-Overlap", "0") or 0)
                pats = parse_patterns(self.headers.get("X-Pattern", ""))
                if not 0 <= overlap <= len(body):
                    raise ValueError("X-Overlap inválido")
                result = parallel_count(body, overlap, pats)
                if path == "/pattern":
                    result = {"patron": result["patron"], "total": result["total"]}
            secs = time.perf_counter() - t0
            result.update(node=NODE_NAME, segundos=round(secs, 6))
            with LOCK:
                WORK["pedazos"] += 1
                WORK["bytes"] += len(body)
                WORK["seg_calculo"] += secs
            self.reply(200, result)
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                WORK["errores"] += 1
            self.reply(400, {"error": str(exc), "node": NODE_NAME})
        finally:
            with LOCK:
                WORK["activos"] -= 1

    def handle_ref(self, path: str, p: dict) -> None:
        """Fragmentos POR REFERENCIA: el nodo lee su propia copia del genoma
        (misma caché .seq en todas las nubes), así por internet solo viaja
        {archivo, offset, longitud} y no los megabytes del fragmento."""
        if path == "/preparar":
            name = p.get("archivo", "")
            try:
                fp = data_path(name)
            except ValueError as exc:
                self.reply(400, {"error": str(exc)})
                return
            threading.Thread(target=prepare_file, args=(fp,), daemon=True).start()
            self.reply(202, {"node": NODE_NAME, "archivo": name, "estado": "preparando"})
            return
        if path == "/descargar":
            url, name = str(p.get("url", "")), str(p.get("archivo", ""))
            if not url.startswith(("https://", "http://")) or not FILE_RE.match(name):
                self.reply(400, {"error": "url o nombre inválido"})
                return
            threading.Thread(target=download_file, args=(url, name), daemon=True).start()
            self.reply(202, {"node": NODE_NAME, "archivo": name, "estado": "descargando"})
            return
        with LOCK:
            WORK["activos"] += 1
        t0 = time.perf_counter()
        try:
            if path == "/count_ref":
                meta = ready_meta(p.get("archivo", ""), p.get("seq_sha256"))
                off, n, ov = int(p["offset"]), int(p["longitud"]), int(p.get("solape", 0))
                with open(meta["seq_path"], "rb") as fh:
                    data = os.pread(fh.fileno(), n + ov, off)
                result = parallel_count(data, min(ov, max(len(data) - n, 0)), parse_patterns(p.get("patrones", [])))
                nbytes = len(data)
            else:
                ma = ready_meta(p.get("archivo_a", ""), p.get("seq_sha256_a"))
                mb = ready_meta(p.get("archivo_b", ""), p.get("seq_sha256_b"))
                off, n = int(p["offset"]), int(p["longitud"])
                with open(ma["seq_path"], "rb") as fa, open(mb["seq_path"], "rb") as fb:
                    a, b = os.pread(fa.fileno(), n, off), os.pread(fb.fileno(), n, off)
                result = parallel_compare(a, b)
                nbytes = len(a) + len(b)
            secs = time.perf_counter() - t0
            result.update(node=NODE_NAME, segundos=round(secs, 6), bytes_leidos=nbytes)
            with LOCK:
                WORK["pedazos"] += 1
                WORK["bytes"] += nbytes
                WORK["seg_calculo"] += secs
            self.reply(200, result)
        except (KeyError, ValueError, OSError) as exc:
            with LOCK:
                WORK["errores"] += 1
            self.reply(409 if "no está listo" in str(exc) else 400, {"error": str(exc), "node": NODE_NAME})
        finally:
            with LOCK:
                WORK["activos"] -= 1

    def log_message(self, fmt, *args):
        if os.getenv("WORKER_LOG") == "1":
            sys.stderr.write(f"[{NODE_NAME}] " + fmt % args + "\n")


def start_pool() -> None:
    """Crea el pool ANTES de cualquier hilo (fork seguro) y lo calienta para
    que todos sus procesos existan y aparezcan en /stats."""
    global POOL
    if POOL is None:
        POOL = ProcessPoolExecutor(max_workers=CPUS)
        list(POOL.map(_warmup, range(CPUS)))


def start_background() -> None:
    threading.Thread(target=sampler, daemon=True).start()
    threading.Thread(target=lambda: EXTRA.update(potencia_gflops=measure_gflops()), daemon=True).start()
    # prepara en segundo plano la caché de los FASTA que ya estén en /datos
    def warm():
        for f in list_data_files():
            if not f["listo"] and f.get("bytes"):
                prepare_file(os.path.join(DATA_DIR, f["nombre"]))
    threading.Thread(target=warm, daemon=True).start()


def make_server(port: int = PORT) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    return srv


def main() -> int:
    if not TOKEN:
        print("ERROR: falta CLUSTER_TOKEN (la clave compartida del clúster).", file=sys.stderr)
        return 1
    start_pool()
    start_background()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    print(f"adn-worker '{NODE_NAME}' escuchando en :{PORT} | {CPUS} núcleos | "
          f"{os.getenv('CLOUD_PROVIDER', '?')} ({os.getenv('CLOUD_ORIGIN', '?')})", flush=True)
    try:
        srv.serve_forever()
    finally:
        POOL.shutdown(cancel_futures=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
