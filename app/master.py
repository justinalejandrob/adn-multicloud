#!/usr/bin/env python3
"""
master.py - Maestro del clúster ADN: reparte el trabajo entre las nubes.

El maestro corre en la PC local (no en la nube) y SOLO REPARTE:
  1. Limpia el FASTA una vez (quita encabezados y saltos de línea) y lo guarda
     en una caché <archivo>.seq. Los cromosomas quedan separados por 0x00 para
     que un patrón nunca "cruce" de un cromosoma a otro.
  2. Parte la secuencia en pedazos de --chunk-mb. Cada pedazo lleva
     len(patrón)-1 bytes extra al final (solape) para no perder coincidencias
     entre pedazos.
  3. Reparte los pedazos de forma DINÁMICA: cada nodo abre tantos pedidos
     simultáneos como núcleos tiene y toma el siguiente pedazo libre al
     terminar; los nodos rápidos hacen más trabajo.
  4. Si un nodo falla, su pedazo vuelve a la cola y lo toma otro nodo. Si
     TODAS las nubes fallan, el maestro termina el trabajo localmente
     (continuidad del negocio / nube híbrida).
  5. Suma los resultados parciales y, opcionalmente, los compara con la línea
     base local (1 núcleo): el resultado del clúster debe ser IDÉNTICO.

Además mide por separado LATENCIA (RTT) y VELOCIDAD DE TRANSFERENCIA (MB/s) de
cada nube, y estima el COSTO de cada ejecución.

Uso:
  export CLUSTER_TOKEN='la-clave'
  python master.py --nodes nodes.txt --input datos/genoma.fna
  python master.py --nodes nodes.txt --input datos/a.fa --input2 datos/b.fa   # comparar
  python master.py --nodes nodes.txt --medir-red
Opciones: --chunk-mb 32  --max-hilos 4  --patron GATTACA  --solo-local
          --maestro-calcula  --solo-pais Ecuador  --excluir nodo-china
          --salida resultado.json
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import queue
import socket
import statistics
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker as W  # noqa: E402  (mismas funciones puras que usan los nodos)
from seqcache import plan_pieces, seq_cache  # noqa: E402,F401  (caché .seq compartida)

MB = 1024 * 1024
CACHE_BLOCK = 64 * MB
MEM_FRACTION = 0.40          # tope de memoria para pedazos "en camino"
MAX_NODE_ERRORS = 3          # errores seguidos antes de dar por caído un nodo
SUM_KEYS = W.SUM_KEYS


# =============================================================================
# Nodos
# =============================================================================
def read_nodes(path: str) -> list[tuple[str, str]]:
    """nodes.txt: una línea 'nombre=http://IP:8000' por worker (# comenta)."""
    nodes = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                name, url = (x.strip() for x in line.split("=", 1))
                if name and url.startswith(("http://", "https://")):
                    nodes.append((name, url.rstrip("/")))
    return nodes


class RemoteNode:
    """Cliente HTTP de un worker. Una conexión persistente por hilo."""

    def __init__(self, name: str, url: str, token: str, timeout: float = 300):
        self.name, self.url, self.token, self.timeout = name, url, token, timeout
        u = urlparse(url)
        self.https = u.scheme == "https"
        self.host = u.hostname
        self.port = u.port or (443 if self.https else 80)
        self.base = u.path.rstrip("/")
        self.local = threading.local()
        self.info: dict = {}
        self.local_node = False

    def _conn(self, fresh=False, timeout=None):
        c = getattr(self.local, "conn", None)
        if c is None or fresh:
            if c is not None:
                c.close()
            cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
            c = cls(self.host, self.port, timeout=timeout or self.timeout)
            c.connect()
            c.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # sin Nagle
            self.local.conn = c
        return c

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict | None = None, timeout=None, auth=True) -> tuple[dict | bytes, float]:
        """Devuelve (respuesta, segundos de pared). Reintenta 1 vez si la
        conexión persistente se había cerrado."""
        hdrs = dict(headers or {})
        if auth:
            hdrs["X-Token"] = self.token
        if body is not None:
            hdrs["Content-Length"] = str(len(body))
        for attempt in (0, 1):
            conn = self._conn(fresh=attempt == 1, timeout=timeout)
            try:
                t0 = time.perf_counter()
                conn.request(method, self.base + path, body=body, headers=hdrs)
                resp = conn.getresponse()
                data = resp.read()
                wall = time.perf_counter() - t0
                break
            except (http.client.HTTPException, ConnectionError, OSError):
                conn.close()
                self.local.conn = None
                if attempt == 1:
                    raise
        if resp.status >= 400:
            try:
                msg = json.loads(data).get("error", "")
            except ValueError:
                msg = data[:200].decode(errors="replace")
            raise RuntimeError(f"{self.name}: HTTP {resp.status} {msg}")
        ctype = resp.getheader("Content-Type", "")
        return (json.loads(data) if "json" in ctype else data), wall

    def health(self, timeout=5) -> dict:
        self.info, _ = self.request("GET", "/health", timeout=timeout, auth=False)
        return self.info

    def stats(self, timeout=5) -> dict:
        return self.request("GET", "/stats", timeout=timeout)[0]

    # --- trabajo -----------------------------------------------------------
    def count(self, data: bytes, overlap: int, pattern: bytes) -> tuple[dict, float]:
        h = {"X-Overlap": str(overlap), "Content-Type": "application/octet-stream"}
        if pattern:
            h["X-Pattern"] = pattern.decode()
        return self.request("POST", "/count", data, h)

    def compare(self, a: bytes, b: bytes) -> tuple[dict, float]:
        return self.request("POST", "/compare", a + b,
                            {"X-Len-A": str(len(a)), "Content-Type": "application/octet-stream"})


class LocalNode:
    """El maestro calculando por sí mismo (--maestro-calcula o respaldo)."""

    local_node = True

    def __init__(self, name="maestro-local", workers: int | None = None):
        self.name, self.url = name, "local"
        self.cpus = workers or os.cpu_count() or 1
        self.info = {"node": name, "cpus": self.cpus, "pais": "Local",
                     "provider": "local", "costo_hora": 0.0}
        self._pool = None
        self._lock = threading.Lock()

    def _ensure_pool(self):
        with self._lock:
            if self._pool is None and self.cpus > 1:
                from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415
                self._pool = ProcessPoolExecutor(max_workers=self.cpus)
                W.POOL = self._pool
                W.CPUS = self.cpus

    def health(self, timeout=5):
        return self.info

    def count(self, data, overlap, pattern):
        self._ensure_pool()
        t0 = time.perf_counter()
        r = W.parallel_count(data, overlap, pattern) if self.cpus > 1 else W.count_region(data, overlap, pattern)
        secs = time.perf_counter() - t0
        r.update(node=self.name, segundos=secs)
        return r, secs

    def compare(self, a, b):
        self._ensure_pool()
        t0 = time.perf_counter()
        r = W.parallel_compare(a, b) if self.cpus > 1 else W.compare_region(a, b)
        secs = time.perf_counter() - t0
        r.update(node=self.name, segundos=secs)
        return r, secs

    def close(self):
        if self._pool:
            self._pool.shutdown()


# =============================================================================
# Caché .seq (FASTA limpio)
# =============================================================================
def mem_available() -> int:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 2 * 1024 * MB


class ByteBudget:
    """Semáforo por bytes: tope de memoria para pedazos en camino."""

    def __init__(self, limit: int):
        self.limit, self.used = max(limit, 1), 0
        self.cv = threading.Condition()

    def acquire(self, n: int, stop: threading.Event) -> bool:
        with self.cv:
            while self.used > 0 and self.used + n > self.limit:
                if stop.is_set():
                    return False
                self.cv.wait(0.2)
            self.used += n
            return True

    def release(self, n: int):
        with self.cv:
            self.used -= n
            self.cv.notify_all()


# =============================================================================
# Red: latencia vs. velocidad de transferencia
# =============================================================================
def measure_network(nodes, probe_mb: int = 8, pings: int = 7, log=print) -> list[dict]:
    """RTT (mediana de varios /health con conexión ya abierta) y MB/s de subida
    y bajada. Así se separa la LATENCIA de la VELOCIDAD DE TRANSFERENCIA."""
    out = []
    payload = os.urandom(probe_mb * MB)
    for n in nodes:
        row = {"node": n.name, "url": n.url}
        try:
            t0 = time.perf_counter()
            n.health(timeout=10)
            row["conexion_ms"] = round((time.perf_counter() - t0) * 1000, 2)  # incluye TCP/TLS
            rtts = []
            for _ in range(pings):
                t = time.perf_counter()
                n.request("GET", "/health", timeout=10, auth=False)
                rtts.append((time.perf_counter() - t) * 1000)
            rtt = statistics.median(rtts)
            row.update(rtt_ms=round(rtt, 2), rtt_min_ms=round(min(rtts), 2),
                       jitter_ms=round(statistics.pstdev(rtts), 2))
            # tiempo de transferencia = tiempo total - 1 RTT (la "ida y vuelta" fija)
            base = min(rtts) / 1000
            _, wall = n.request("POST", "/sink", payload, {"Content-Type": "application/octet-stream"}, timeout=120)
            row["subida_mb_s"] = round(probe_mb / max(wall - base, wall * 0.05), 2)
            _, wall = n.request("GET", f"/source?mb={probe_mb}", timeout=120)
            row["bajada_mb_s"] = round(probe_mb / max(wall - base, wall * 0.05), 2)
            # Tiempo teórico para mover 1 GB: lo domina el ancho de banda, no el RTT
            row["seg_por_gb"] = round(1024 / row["subida_mb_s"], 1)
            row.update({k: n.info.get(k) for k in ("pais", "provider", "region", "costo_hora")})
            row["ok"] = True
        except Exception as exc:  # noqa: BLE001
            row.update(ok=False, error=str(exc))
        log(f"  {n.name:<14} RTT {row.get('rtt_ms', '—')} ms | "
            f"subida {row.get('subida_mb_s', '—')} MB/s | bajada {row.get('bajada_mb_s', '—')} MB/s")
        out.append(row)
    return out


# =============================================================================
# Trabajo distribuido
# =============================================================================
class Job:
    """Un trabajo del clúster. `progress` recibe eventos para el dashboard."""

    def __init__(self, nodes, mode="contar", input_a=None, input_b=None, chunk_mb=32,
                 max_hilos=0, pattern="GATTACA", baseline=False, fallback_local=True,
                 cache_dir=None, progress=None, log=print):
        self.nodes, self.mode = list(nodes), mode
        self.input_a, self.input_b = input_a, input_b
        self.chunk = max(1, int(chunk_mb)) * MB
        self.max_hilos = int(max_hilos or 0)
        self.pattern = (pattern or "").strip().upper().encode() if mode == "contar" else b""
        self.baseline, self.fallback_local = baseline, fallback_local
        self.cache_dir = cache_dir
        self.progress = progress or (lambda ev: None)
        self.log = log
        self.stop = threading.Event()
        self.lock = threading.Lock()

    def cancel(self):
        self.stop.set()

    # ------------------------------------------------------------------
    def run(self) -> dict:
        t_start = time.perf_counter()
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.progress({"fase": "preparando"})
        meta_a = seq_cache(self.input_a, self.cache_dir, self.log)
        meta_b = seq_cache(self.input_b, self.cache_dir, self.log) if self.mode == "comparar" else None
        t_prep = time.perf_counter() - t_start

        size = meta_a["seq_size"] if self.mode == "contar" else min(meta_a["seq_size"], meta_b["seq_size"])
        overlap = max(len(self.pattern) - 1, 0)
        pieces = plan_pieces(size, self.chunk, overlap)

        # nodos vivos
        alive = []
        for n in self.nodes:
            try:
                n.health(timeout=8)
                alive.append(n)
            except Exception as exc:  # noqa: BLE001
                self.log(f"  {n.name}: no responde ({exc}); se excluye")
        if not alive and not self.fallback_local:
            raise RuntimeError("Ningún nodo responde")

        per_node = {n.name: {"node": n.name, "pais": n.info.get("pais"), "provider": n.info.get("provider"),
                             "region": n.info.get("region"), "cpus": n.info.get("cpus"),
                             "costo_hora": n.info.get("costo_hora", 0) or 0, "pedazos": 0, "bytes": 0,
                             "seg_pared": 0.0, "seg_calculo": 0.0, "errores": 0, "caido": False}
                    for n in alive}
        results: dict[int, dict] = {}
        todo: queue.Queue = queue.Queue()
        for i in range(len(pieces)):
            todo.put(i)
        budget = ByteBudget(int(mem_available() * MEM_FRACTION))
        fa = open(meta_a["seq_path"], "rb")
        fb = open(meta_b["seq_path"], "rb") if meta_b else None
        total_bytes = size
        done_bytes = [0]
        self.progress({"fase": "repartiendo", "pedazos_total": len(pieces), "bytes_total": total_bytes,
                       "nodos": [n.name for n in alive], "preparacion_s": round(t_prep, 2)})
        t_dist = time.perf_counter()

        def read(f, off, n):
            return os.pread(f.fileno(), n, off)

        def process(node, idx) -> bool:
            off, n, ov = pieces[idx]
            need = (n + ov) * (2 if fb else 1)
            if not budget.acquire(need, self.stop):
                return False
            try:
                if fb:
                    res, wall = node.compare(read(fa, off, n), read(fb, off, n))
                else:
                    res, wall = node.count(read(fa, off, n + ov), ov, self.pattern)
            finally:
                budget.release(need)
            with self.lock:
                results[idx] = res
                st = per_node[node.name]
                st["pedazos"] += 1
                st["bytes"] += need
                st["seg_pared"] += wall
                st["seg_calculo"] += float(res.get("segundos", 0))
                done_bytes[0] += n
                ev = {"fase": "repartiendo", "pedazos_hechos": len(results), "pedazos_total": len(pieces),
                      "bytes_hechos": done_bytes[0], "bytes_total": total_bytes,
                      "segundos": round(time.perf_counter() - t_dist, 2),
                      "por_nodo": {k: {"pedazos": v["pedazos"], "bytes": v["bytes"], "errores": v["errores"],
                                       "caido": v["caido"]} for k, v in per_node.items()}}
            self.progress(ev)
            return True

        def sender(node):
            consecutive = 0
            while not self.stop.is_set():
                if per_node[node.name]["caido"]:
                    return
                try:
                    idx = todo.get(timeout=0.2)
                except queue.Empty:
                    with self.lock:
                        if len(results) == len(pieces):
                            return
                    continue
                try:
                    if process(node, idx):
                        consecutive = 0
                    else:
                        todo.put(idx)
                except Exception as exc:  # noqa: BLE001
                    todo.put(idx)                       # otro nodo lo tomará
                    consecutive += 1
                    with self.lock:
                        per_node[node.name]["errores"] += 1
                        if consecutive >= MAX_NODE_ERRORS:
                            per_node[node.name]["caido"] = True
                    self.log(f"  {node.name}: error ({exc}); pedazo {idx} reasignado")
                    time.sleep(0.5)

        threads = []
        for n in alive:
            slots = self.max_hilos or int(n.info.get("cpus") or 1)
            for _ in range(max(1, slots)):
                t = threading.Thread(target=sender, args=(n,), daemon=True)
                t.start()
                threads.append(t)

        # vigilancia: si todas las nubes caen, el maestro termina localmente
        fallback_used = False
        while not self.stop.is_set():
            with self.lock:
                finished = len(results) == len(pieces)
                all_down = all(v["caido"] for v in per_node.values()) if per_node else True
            if finished:
                break
            if all_down and not any(t.is_alive() for t in threads):
                if not self.fallback_local:
                    raise RuntimeError("Todos los nodos fallaron")
                self.log("  Todas las nubes fallaron: el maestro continúa localmente (respaldo híbrido)")
                fallback_used = True
                local = LocalNode("maestro-respaldo")
                per_node[local.name] = {"node": local.name, "pais": "Local", "provider": "local",
                                        "region": "PC", "cpus": local.cpus, "costo_hora": 0, "pedazos": 0,
                                        "bytes": 0, "seg_pared": 0.0, "seg_calculo": 0.0, "errores": 0,
                                        "caido": False}
                t = threading.Thread(target=sender, args=(local,), daemon=True)
                t.start()
                threads = [t]
            time.sleep(0.1)
        for t in threads:
            t.join(timeout=1)
        fa.close()
        if fb:
            fb.close()
        if self.stop.is_set() and len(results) < len(pieces):
            raise RuntimeError("Trabajo cancelado")
        t_dist = time.perf_counter() - t_dist

        merged = self.merge([results[i] for i in range(len(pieces))], meta_a, meta_b)
        wall_total = time.perf_counter() - t_start
        hours = t_dist / 3600
        for st in per_node.values():
            st["seg_red"] = round(max(st["seg_pared"] - st["seg_calculo"], 0), 3)
            st["mb_s_efectivo"] = round(st["bytes"] / MB / st["seg_pared"], 2) if st["seg_pared"] else None
            st["costo_usd"] = round(st["costo_hora"] * hours, 6)
            st["seg_pared"] = round(st["seg_pared"], 3)
            st["seg_calculo"] = round(st["seg_calculo"], 3)

        out = {
            "tipo": "cluster", "modo": self.mode, "inicio_utc": started,
            "archivo_a": meta_a["file"], "archivo_b": meta_b["file"] if meta_b else None,
            "sha256_a": meta_a["src_sha256"], "sha256_b": meta_b["src_sha256"] if meta_b else None,
            "bytes_secuencia": size, "chunk_mb": self.chunk // MB, "pedazos": len(pieces),
            "patron": self.pattern.decode(), "max_hilos": self.max_hilos,
            "nodos": list(per_node.values()), "respaldo_local": fallback_used,
            "resultado": merged, "segundos_preparacion": round(t_prep, 3),
            "segundos_reparto": round(t_dist, 3), "segundos_total": round(wall_total, 3),
            "mb_s": round(size / MB / t_dist, 2) if t_dist else None,
            "costo_total_usd": round(sum(v["costo_usd"] for v in per_node.values()), 6),
        }
        if self.baseline:
            self.progress({"fase": "linea_base"})
            base = run_baseline(self.mode, meta_a, meta_b, self.pattern, self.chunk, self.log)
            out["linea_base"] = base
            out["identico_a_linea_base"] = same_result(merged, base["resultado"], self.mode)
            out["speedup_vs_1_nucleo"] = round(base["segundos"] / t_dist, 2) if t_dist else None
        self.progress({"fase": "terminado"})
        return out

    def merge(self, parts, meta_a, meta_b) -> dict:
        if self.mode == "comparar":
            r = {"comparadas": 0, "iguales": 0, "diferentes": 0}
            for p in parts:
                for k in r:
                    r[k] += p[k]
            r["sobrantes"] = abs(meta_a["seq_size"] - meta_b["seq_size"])
            r["similitud_pct"] = round(r["iguales"] / r["comparadas"] * 100, 6) if r["comparadas"] else 0
            return r
        r = W.merge_counts(parts)
        valid = r["A"] + r["C"] + r["G"] + r["T"]
        r["gc_pct"] = round((r["G"] + r["C"]) / valid * 100, 4) if valid else 0
        r["detalle_otros"] = dict(sorted(r["detalle_otros"].items(), key=lambda kv: -kv[1]))
        return r


def run_baseline(mode, meta_a, meta_b, pattern, chunk, log=print) -> dict:
    """Línea base: el MISMO cálculo en la PC con 1 solo núcleo."""
    log("Línea base local con 1 núcleo ...")
    t0 = time.perf_counter()
    if mode == "comparar":
        n = min(meta_a["seq_size"], meta_b["seq_size"])
        r = {"comparadas": 0, "iguales": 0, "diferentes": 0}
        with open(meta_a["seq_path"], "rb") as fa, open(meta_b["seq_path"], "rb") as fb:
            for off in range(0, n, chunk):
                k = min(chunk, n - off)
                p = W.compare_region(os.pread(fa.fileno(), k, off), os.pread(fb.fileno(), k, off))
                for key in r:
                    r[key] += p[key]
        r["sobrantes"] = abs(meta_a["seq_size"] - meta_b["seq_size"])
        r["similitud_pct"] = round(r["iguales"] / r["comparadas"] * 100, 6) if r["comparadas"] else 0
    else:
        ov = max(len(pattern) - 1, 0)
        parts = []
        with open(meta_a["seq_path"], "rb") as fa:
            for off, n, o in plan_pieces(meta_a["seq_size"], chunk, ov):
                parts.append(W.count_region(os.pread(fa.fileno(), n + o, off), o, pattern))
        r = W.merge_counts(parts)
        valid = r["A"] + r["C"] + r["G"] + r["T"]
        r["gc_pct"] = round((r["G"] + r["C"]) / valid * 100, 4) if valid else 0
    secs = time.perf_counter() - t0
    log(f"Línea base: {secs:.2f} s")
    return {"tipo": "linea_base", "nucleos": 1, "segundos": round(secs, 3), "resultado": r}


def same_result(a: dict, b: dict, mode: str) -> bool:
    keys = ("comparadas", "iguales", "diferentes", "sobrantes") if mode == "comparar" else SUM_KEYS
    return all(a.get(k) == b.get(k) for k in keys) and (
        mode == "comparar" or Counter(a.get("detalle_otros", {})) == Counter(b.get("detalle_otros", {})))


# =============================================================================
# CLI
# =============================================================================
def build_nodes(args, token) -> list:
    nodes = []
    if args.nodes and not args.solo_local:
        for name, url in read_nodes(args.nodes):
            if name in (args.excluir or []):
                continue
            nodes.append(RemoteNode(name, url, token))
    if args.solo_pais:
        keep = []
        for n in nodes:
            try:
                if str(n.health().get("pais", "")).lower() == args.solo_pais.lower():
                    keep.append(n)
            except Exception:  # noqa: BLE001
                pass
        nodes = keep
    if args.maestro_calcula or args.solo_local:
        nodes.append(LocalNode())
    return nodes


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Maestro del clúster ADN multinube")
    p.add_argument("--nodes", default=os.getenv("NODES_FILE", "nodes.txt"))
    p.add_argument("--input", "-i", help="FASTA a procesar")
    p.add_argument("--input2", help="Segundo FASTA (modo comparar)")
    p.add_argument("--chunk-mb", type=int, default=32)
    p.add_argument("--max-hilos", type=int, default=0, help="Pedidos simultáneos por nodo (0 = uno por núcleo)")
    p.add_argument("--patron", default="GATTACA")
    p.add_argument("--solo-local", action="store_true", help="Sin nubes: todo en la PC")
    p.add_argument("--maestro-calcula", action="store_true", help="El maestro también recibe pedazos")
    p.add_argument("--solo-pais", help="Soberanía: usar solo nodos de este país (ej. Ecuador)")
    p.add_argument("--excluir", nargs="*", help="Nodos a excluir")
    p.add_argument("--sin-linea-base", action="store_true", help="No verificar contra 1 núcleo")
    p.add_argument("--medir-red", action="store_true", help="Solo medir latencia y transferencia")
    p.add_argument("--salida", help="Guardar el resultado en JSON")
    args = p.parse_args(argv)

    token = os.getenv("CLUSTER_TOKEN", "")
    if not token and not args.solo_local:
        print("ERROR: defina CLUSTER_TOKEN con la clave del clúster", file=sys.stderr)
        return 1
    nodes = build_nodes(args, token)
    if not nodes:
        print("ERROR: no hay nodos disponibles", file=sys.stderr)
        return 1

    if args.medir_red:
        res = {"tipo": "red", "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "nodos": measure_network([n for n in nodes if not n.local_node])}
    else:
        if not args.input:
            p.error("--input es obligatorio")
        mode = "comparar" if args.input2 else "contar"
        job = Job(nodes, mode, args.input, args.input2, args.chunk_mb, args.max_hilos,
                  args.patron, baseline=not args.sin_linea_base)
        res = job.run()
        r = res["resultado"]
        print("=" * 66)
        print(f" Clúster: {len(res['nodos'])} nodos | {res['pedazos']} pedazos de {res['chunk_mb']} MB | "
              f"{res['segundos_reparto']} s | {res['mb_s']} MB/s")
        for st in res["nodos"]:
            print(f"   {st['node']:<16} {st['pais'] or '':<10} pedazos {st['pedazos']:>4} | cálculo "
                  f"{st['seg_calculo']:>7} s | red {st['seg_red']:>7} s | errores {st['errores']}")
        if mode == "contar":
            print(f" A {r['A']:,}  C {r['C']:,}  G {r['G']:,}  T {r['T']:,}  N {r['N']:,}  otros {r['otros']:,}")
            print(f" GC {r['gc_pct']} %  |  patrón {res['patron']}: {r['patron']:,}  |  secuencias {r['registros']}")
        else:
            print(f" Comparadas {r['comparadas']:,} | iguales {r['iguales']:,} | similitud {r['similitud_pct']} %")
        if "identico_a_linea_base" in res:
            print(f" Idéntico a la línea base (1 núcleo): {'SÍ' if res['identico_a_linea_base'] else 'NO'} | "
                  f"speedup {res['speedup_vs_1_nucleo']}x")
        print(f" Costo estimado: US$ {res['costo_total_usd']:.6f}")
        print("=" * 66)
    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, ensure_ascii=False)
        print(f"Guardado en {args.salida}")
    for n in nodes:
        if isinstance(n, LocalNode):
            n.close()
    return 0 if res.get("identico_a_linea_base", True) else 2


if __name__ == "__main__":
    sys.exit(main())
