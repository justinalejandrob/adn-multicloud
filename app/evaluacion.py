"""
evaluacion.py - La Evaluación S11 resuelta EN LA PRÁCTICA con las 5 nubes del clúster.

Cada pregunta de la evaluación se convierte en un experimento que corre en las
nubes reales. Los proveedores que nombra la pregunta se reemplazan por su
equivalente en el clúster:

    CNT EP / Telconet / DC local TIER III  ->  Telecu Cloud (Guayaquil, Ecuador)
    AWS / Azure (hiperescalar de EE. UU.)  ->  AWS (Ohio, EE. UU.)
    OVHcloud (soberano europeo)            ->  OVHcloud (Fráncfort, Alemania)
    Alibaba / Tencent / Huawei / KT Cloud  ->  Huawei Cloud (Hong Kong)
    Sonda / Movistar / Internexa / Claro   ->  DonWeb (Rosario, Argentina): nube regional
    Netlife / Telconet (VPS tarifa fija)   ->  Telecu y DonWeb (cobro mensual fijo)

Dos partes:
  1. MEDICIONES LOCALES (local()): las ejecuta el worker de UNA nube cuando
     recibe POST /eval/<nombre> por WireGuard. Ej.: Ecuador mide su latencia
     hacia las otras 4 nubes.
  2. ORQUESTACIÓN (lanzar()): corre en el nodo del dashboard, pide las
     mediciones a las nubes que correspondan, arma el resultado y lo guarda en
     etcd (/adn/eval/<pregunta>) para que cualquier dashboard lo vea.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import statistics
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

K_EVAL = "/adn/eval/"
MB = 1024 * 1024
CLIENTE = "ecuador"     # el banco / la institución / la startup / los sensores están en Ecuador

# Ubicación aproximada de cada centro de datos (para la distancia y el mínimo físico)
COORDS = {
    "usa": (39.96, -82.99, "Columbus, Ohio"),
    "europa": (50.11, 8.68, "Fráncfort"),
    "china": (22.32, 114.17, "Hong Kong"),
    "latam": (-32.95, -60.64, "Rosario"),
    "ecuador": (-2.17, -79.92, "Guayaquil"),
}
PAIS_ISO = {"ecuador": "EC", "ee.uu.": "US", "alemania": "DE", "hong kong (china)": "HK",
            "argentina": "AR", "china": "CN", "francia": "FR", "canadá": "CA", "brasil": "BR"}

ROL = {
    "p1": {"ecuador": "DC local TIER III (CNT/Telconet → Telecu)", "usa": "Hiperescalar de EE. UU. (AWS/Azure → AWS)"},
    "p2": {"ecuador": "a) Nube nacional (CNT EP → Telecu)", "europa": "b) Soberano europeo (OVHcloud)",
           "usa": "c) Hiperescalar de EE. UU. (CLOUD Act → AWS)"},
    "p3": {"usa": "Pago por uso EE. UU. (AWS/Azure → AWS)", "china": "Asiático bajo costo (Alibaba/Tencent → Huawei)",
           "europa": "Pago por uso con tráfico incluido (OVHcloud)",
           "ecuador": "VPS local tarifa fija (Telconet/Netlife → Telecu)", "latam": "VPS regional tarifa fija (DonWeb)"},
    "p4": {"usa": "Proveedor de EE. UU. (Vertex AI/SageMaker → AWS)",
           "china": "Proveedor asiático (ModelArts/ApsaraDB → Huawei)"},
    "p5": {"usa": "Multinacional (Azure/IBM → AWS)", "europa": "Multinacional (OVHcloud)",
           "china": "Multinacional (Huawei)", "latam": "Integrador regional (Sonda/Movistar → DonWeb)",
           "ecuador": "Integrador local (Telecu)"},
    "p6": {"ecuador": "Almacenamiento privado local (Internexa/Telconet → Telecu)",
           "usa": "STaaS global (S3/GCS: réplica en EE. UU.)", "europa": "STaaS global (réplica en Europa)",
           "china": "STaaS global (réplica en Asia)", "latam": "STaaS global (réplica en Sudamérica)"},
    "p7": {"ecuador": "Borde local 5G/MEC (Claro/CNT → Telecu)", "latam": "Transporte regional (Internexa/Claro → DonWeb)",
           "china": "Borde asiático (KT Cloud/Huawei IEF → Huawei)", "usa": "Nube central (hiperescalar)"},
}


# =============================================================================
# Utilidades
# =============================================================================
def dist_km(a: str, b: str) -> float | None:
    if a not in COORDS or b not in COORDS:
        return None
    la1, lo1, _ = COORDS[a]
    la2, lo2, _ = COORDS[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)))


def es(x, d: int = 1) -> str:
    """Número con formato de Ecuador: 1.234,5"""
    if x is None:
        return "—"
    txt = f"{float(x):,.{d}f}"
    return txt.replace(",", "§").replace(".", ",").replace("§", ".")


CONTINENTE = {"usa": "América del Norte", "europa": "Europa", "china": "Asia", "latam": "América del Sur",
              "ecuador": "América del Sur"}


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def stats_ms(ms: list[float]) -> dict:
    return {"muestras": len(ms), "min": round(min(ms), 3) if ms else None, "p50": pct(ms, 0.5),
            "p95": pct(ms, 0.95), "p99": pct(ms, 0.99), "max": round(max(ms), 3) if ms else None,
            "jitter": round(statistics.pstdev(ms), 3) if len(ms) > 1 else 0.0,
            "bajo_15": round(sum(1 for x in ms if x < 15) / len(ms) * 100, 1) if ms else 0.0}


def _client(target: dict, token: str, timeout: float = 30):
    import master as M  # noqa: PLC0415
    return M.RemoteNode(target["nombre"], target["url"], token, timeout=timeout)


def _post(cli, path: str, body: dict, timeout: float | None = None):
    return cli.request("POST", path, json.dumps(body).encode(), {"Content-Type": "application/json"},
                       timeout=timeout)


# =============================================================================
# 1. MEDICIONES LOCALES (las corre el worker que recibe POST /eval/<nombre>)
# =============================================================================
def local(name: str, p: dict, ctx: dict) -> dict:
    fn = {"autorizar": m_autorizar, "rtt": m_rtt, "leer": m_leer, "bajada": m_bajada,
          "iot_decidir": m_iot_decidir, "iot": m_iot, "bench": m_bench, "entorno": m_entorno}.get(name)
    if not fn:
        raise ValueError(f"medición desconocida: {name}")
    return fn(p, ctx)


def m_autorizar(p: dict, ctx: dict) -> dict:
    """Microservicio de autorización (pregunta 1): aprueba si el monto <= límite."""
    monto = float(p.get("monto", 0))
    return {"nodo": ctx["nodo"], "aprobada": monto <= float(p.get("limite", 1500)),
            "codigo": hashlib.sha256(f"{p.get('tx')}{monto}".encode()).hexdigest()[:12]}


def m_rtt(p: dict, ctx: dict) -> dict:
    """Desde ESTA nube: N autorizaciones contra cada destino (o durante S segundos)."""
    n = max(5, min(int(p.get("n", 60)), 400))
    segundos = float(p.get("segundos", 0) or 0)
    out = []
    for t in p.get("targets", [])[:8]:
        cli = _client(t, ctx["token"], timeout=5)
        ms, errores, i = [], 0, 0
        for _ in range(3):        # calentar la conexión persistente
            try:
                _post(cli, "/eval/autorizar", {"tx": "warm", "monto": 1})
            except Exception:  # noqa: BLE001
                pass
        t_end = time.time() + segundos
        while (i < n) if not segundos else (time.time() < t_end):
            i += 1
            body = {"tx": f"{ctx['nodo']}-{i}", "monto": round(random.uniform(5, 3000), 2), "limite": 1500}
            t0 = time.perf_counter()
            try:
                _post(cli, "/eval/autorizar", body)
                ms.append((time.perf_counter() - t0) * 1000)
            except Exception:  # noqa: BLE001
                errores += 1
            if segundos:
                time.sleep(0.05)
        row = {"nombre": t["nombre"], **stats_ms(ms), "errores": errores, "intentos": len(ms) + errores}
        row["disponibilidad"] = round(len(ms) / row["intentos"] * 100, 1) if row["intentos"] else 0.0
        out.append(row)
    return {"desde": ctx["nodo"], "destinos": out}


def m_leer(p: dict, ctx: dict) -> dict:
    """Recupera el mismo bloque del genoma desde la copia local y desde cada réplica remota."""
    import worker as W  # noqa: PLC0415
    name, off = p["archivo"], int(p.get("offset", 0))
    n = max(1 * MB, min(int(p.get("longitud", 64 * MB)), 256 * MB))
    fp = W.data_path(name)
    out = []
    with open(fp, "rb") as fh:
        try:   # se pide al sistema olvidar el bloque para medir el disco y no la RAM
            os.posix_fadvise(fh.fileno(), off, n, os.POSIX_FADV_DONTNEED)
        except (AttributeError, OSError):
            pass
        t0 = time.perf_counter()
        data = os.pread(fh.fileno(), n, off)
        secs = time.perf_counter() - t0
    ref = hashlib.sha256(data).hexdigest()
    out.append({"nombre": ctx["nodo"], "local": True, "segundos": round(secs, 4),
                "mb_s": round(len(data) / MB / max(secs, 1e-6), 1), "sha256": ref, "identico": True})
    for t in p.get("targets", [])[:8]:
        cli = _client(t, ctx["token"], timeout=180)
        try:
            body, wall = cli.request("GET", f"/archivo?nombre={name}&offset={off}&longitud={n}", timeout=180)
            sha = hashlib.sha256(body).hexdigest()
            out.append({"nombre": t["nombre"], "local": False, "segundos": round(wall, 3),
                        "mb_s": round(len(body) / MB / max(wall, 1e-6), 2), "sha256": sha, "identico": sha == ref})
        except Exception as exc:  # noqa: BLE001
            out.append({"nombre": t["nombre"], "local": False, "error": str(exc)[:160]})
    return {"desde": ctx["nodo"], "bytes": len(data), "lecturas": out}


def m_bajada(p: dict, ctx: dict) -> dict:
    """Capacidad de salida (egress) de cada nube hacia ESTA nube: descarga N MB."""
    mb = max(4, min(int(p.get("mb", 32)), 64))
    out = []
    for t in p.get("targets", [])[:8]:
        cli = _client(t, ctx["token"], timeout=180)
        try:
            cli.request("GET", "/health", timeout=10, auth=False)
            best = None
            for _ in range(2):      # 2 intentos: se queda con el mejor (la red varía)
                body, wall = cli.request("GET", f"/source?mb={mb}", timeout=180)
                v = len(body) / MB / max(wall, 1e-6)
                best = v if best is None else max(best, v)
            out.append({"nombre": t["nombre"], "mb": mb, "mb_s": round(best, 2), "mbps": round(best * 8 * 1.048576, 1)})
        except Exception as exc:  # noqa: BLE001
            out.append({"nombre": t["nombre"], "error": str(exc)[:160]})
    return {"desde": ctx["nodo"], "destinos": out}


UMBRAL_IOT = 85.0


def m_iot_decidir(p: dict, ctx: dict) -> dict:
    """Lógica de borde (pregunta 7): detecta alarmas y resume el lote de sensores."""
    lect = p.get("lecturas") or []
    vals = [float(v) for _, v in lect]
    alarmas = sorted({int(s) for s, v in lect if float(v) > UMBRAL_IOT})
    return {"nodo": ctx["nodo"], "alarmas": alarmas, "n": len(vals),
            "media": round(sum(vals) / len(vals), 3) if vals else None, "max": max(vals) if vals else None}


def m_iot(p: dict, ctx: dict) -> dict:
    """Simula sensores en ESTA nube y compara decidir aquí (borde) contra enviar a cada nube."""
    lotes = max(10, min(int(p.get("lotes", 40)), 200))
    sensores = max(10, min(int(p.get("sensores", 200)), 2000))
    rng = random.Random(2026)
    batches = []
    for b in range(lotes):
        lect = [[s, round(rng.gauss(60, 8) + (30 if rng.random() < 0.002 else 0), 2)] for s in range(sensores)]
        batches.append(lect)
    crudo = sum(len(json.dumps({"lecturas": x}).encode()) for x in batches)
    out = []
    for t in p.get("targets", [])[:8]:
        cli = _client(t, ctx["token"], timeout=20)
        ms, alarmas, resumen_bytes, err = [], 0, 0, 0
        try:
            _post(cli, "/eval/iot_decidir", {"lecturas": batches[0][:5]})   # calentar
        except Exception:  # noqa: BLE001
            pass
        for lect in batches:
            t0 = time.perf_counter()
            try:
                r, _ = _post(cli, "/eval/iot_decidir", {"lecturas": lect})
                ms.append((time.perf_counter() - t0) * 1000)
                alarmas += len(r.get("alarmas", []))
                resumen_bytes += len(json.dumps({"media": r.get("media"), "max": r.get("max"),
                                                 "alarmas": r.get("alarmas")}).encode())
            except Exception:  # noqa: BLE001
                err += 1
        out.append({"nombre": t["nombre"], **stats_ms(ms), "alarmas": alarmas, "errores": err,
                    "bytes_crudos": crudo, "bytes_resumen": resumen_bytes})
    return {"desde": ctx["nodo"], "lotes": lotes, "sensores": sensores, "lecturas": lotes * sensores,
            "destinos": out}


def m_bench(p: dict, ctx: dict) -> dict:
    """Cómputo para IA (pregunta 4): GFLOPS + entrenamiento de una red neuronal pequeña."""
    import numpy as np  # noqa: PLC0415
    import worker as W  # noqa: PLC0415
    n, reps = 1024, 0
    a = np.random.default_rng(1).random((n, n))
    b = np.random.default_rng(2).random((n, n))
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.5:
        a @ b
        reps += 1
    gflops = 2 * n ** 3 * reps / (time.perf_counter() - t0) / 1e9
    # red neuronal 64 -> 128 -> 1 con descenso de gradiente (datos sintéticos, misma semilla en todas)
    rng = np.random.default_rng(42)
    X = rng.standard_normal((60000, 64)).astype(np.float32)
    w_true = rng.standard_normal(64).astype(np.float32)
    y = (X @ w_true + 0.5 * np.sin(X[:, 0] * 3) > 0).astype(np.float32)
    W1 = (rng.standard_normal((64, 128)) * 0.1).astype(np.float32)
    W2 = (rng.standard_normal((128, 1)) * 0.1).astype(np.float32)
    lr, epocas, lote = 0.05, 6, 256
    t0 = time.perf_counter()
    for _ in range(epocas):
        for i in range(0, len(X), lote):
            xb, yb = X[i:i + lote], y[i:i + lote, None]
            hdn = np.maximum(xb @ W1, 0)
            out = 1 / (1 + np.exp(-(hdn @ W2)))
            g = (out - yb) / len(xb)
            gW2 = hdn.T @ g
            gh = (g @ W2.T) * (hdn > 0)
            W1 -= lr * 10 * (xb.T @ gh)
            W2 -= lr * 10 * gW2
    secs = time.perf_counter() - t0
    pred = (1 / (1 + np.exp(-(np.maximum(X @ W1, 0) @ W2))))[:, 0] > 0.5
    acc = float((pred == y.astype(bool)).mean())
    acel = "ninguno"
    if os.path.exists("/dev/nvidia0") or os.path.exists("/proc/driver/nvidia"):
        acel = "GPU NVIDIA"
    elif any(os.path.exists(f"/dev/davinci{i}") for i in range(8)):
        acel = "NPU Huawei Ascend"
    elif os.path.exists("/dev/neuron0"):
        acel = "AWS Trainium/Inferentia"
    return {"nodo": ctx["nodo"], "gflops": round(gflops, 1), "muestras_s": round(epocas * len(X) / secs),
            "segundos_entreno": round(secs, 3), "precision": round(acc * 100, 2), "acelerador": acel,
            "cpus": W.CPUS, "modelo": W.MODEL, "numpy": np.__version__}


def _http_json(url: str, timeout: float = 5, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode(errors="replace")
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _metadata_api() -> str:
    """API de metadatos de la nube (169.254.169.254): cada proveedor expone la suya."""
    base = "http://169.254.169.254"
    try:
        tok = _http_json(f"{base}/latest/api/token", 1.5, "PUT", {"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        if isinstance(tok, str) and tok:
            return "AWS IMDSv2 (propietaria)"
    except Exception:  # noqa: BLE001
        pass
    try:
        if isinstance(_http_json(f"{base}/openstack/latest/meta_data.json", 1.5), dict):
            return "OpenStack (estándar abierto)"
    except Exception:  # noqa: BLE001
        pass
    try:
        _http_json(f"{base}/latest/meta-data/", 1.5)
        return "Compatible EC2"
    except Exception:  # noqa: BLE001
        return "no expone"


def m_entorno(p: dict, ctx: dict) -> dict:
    """Dónde está REALMENTE esta nube y con qué se ejecuta (preguntas 2 y 5)."""
    geo = {}
    try:
        d = _http_json("https://ipinfo.io/json", 6)
        if isinstance(d, dict):
            geo = {k: d.get(k) for k in ("ip", "city", "region", "country", "org", "timezone")}
    except Exception as exc:  # noqa: BLE001
        geo = {"error": str(exc)[:100]}
    osr = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                k, _, v = line.strip().partition("=")
                osr[k] = v.strip('"')
    except OSError:
        pass
    return {"nodo": ctx["nodo"], "geo": geo, "metadatos": _metadata_api(),
            "imagen": (os.getenv("IMAGE_ID") or "")[7:19] or None, "arquitectura": platform.machine(),
            "kernel": platform.release(), "so_contenedor": osr.get("PRETTY_NAME"),
            "python": platform.python_version()}


# =============================================================================
# 2. ORQUESTACIÓN (corre en el nodo del dashboard; guarda en etcd)
# =============================================================================
class Ctx:
    def __init__(self, etcd, coord):
        self.etcd, self.coord = etcd, coord
        self.token = coord.token if coord else os.getenv("CLUSTER_TOKEN", "")

    def nodos(self) -> dict:
        from coordinador import K_NODOS  # noqa: PLC0415
        out = {}
        for k, v in self.etcd.get_prefix(K_NODOS, serial=True).items():
            if isinstance(v, dict) and v.get("url") and time.time() - float(v.get("visto") or 0) < 20:
                out[k[len(K_NODOS):]] = v
        order = ["usa", "europa", "china", "latam", "ecuador"]
        return dict(sorted(out.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 9))

    def target(self, name: str, nodes: dict | None = None) -> dict:
        nodes = nodes or self.nodos()
        if name not in nodes:
            raise RuntimeError(f"la nube {name} no está viva")
        return {"nombre": name, "url": nodes[name]["url"]}

    def call(self, name: str, path: str, body: dict, timeout: float = 300, nodes=None) -> dict:
        cli = _client(self.target(name, nodes), self.token, timeout=timeout)
        r, _ = _post(cli, path, body, timeout=timeout)
        return r

    def call_all(self, path: str, body: dict, timeout: float = 120) -> dict:
        nodes = self.nodos()
        with ThreadPoolExecutor(max_workers=len(nodes) or 1) as ex:
            futs = {n: ex.submit(self.call, n, path, body, timeout, nodes) for n in nodes}
        out = {}
        for n, f in futs.items():
            try:
                out[n] = f.result()
            except Exception as exc:  # noqa: BLE001
                out[n] = {"error": str(exc)[:160]}
        return out

    def genoma(self) -> tuple[str | None, list[str]]:
        """El FASTA listo en más nubes (y en cuáles, con el mismo SHA-256)."""
        cnt: dict[tuple, list] = {}
        for n, info in self.nodos().items():
            for f in info.get("archivos", []):
                if f.get("listo"):
                    cnt.setdefault((f["nombre"], f.get("seq_sha256")), []).append(n)
        if not cnt:
            return None, []
        (name, _), where = max(cnt.items(), key=lambda kv: (len(kv[1]), kv[0][0]))
        return name, where

    def historial(self) -> list[dict]:
        from coordinador import K_HIST  # noqa: PLC0415
        h = self.etcd.get_prefix(K_HIST, serial=True)
        return [h[k] for k in sorted(h) if isinstance(h[k], dict)]

    def trabajo_libre(self):
        from coordinador import K_TRABAJO  # noqa: PLC0415
        job = self.etcd.get(K_TRABAJO)
        if isinstance(job, dict) and job.get("estado") == "running":
            raise RuntimeError("hay un análisis en curso; espere a que termine")

    def lider(self) -> str | None:
        from coordinador import K_LIDER  # noqa: PLC0415
        return self.etcd.get(K_LIDER, as_json=False)

    def esperar(self, cond, timeout: float, paso: float = 0.1) -> float | None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if cond():
                return round(time.time() - t0, 2)
            time.sleep(paso)
        return None

    def analizar(self, params: dict, timeout: float = 900) -> dict:
        """Envía un análisis al líder y espera su resumen (para P2 y escalabilidad)."""
        import cluster_api  # noqa: PLC0415
        from coordinador import K_TRABAJO  # noqa: PLC0415
        self.trabajo_libre()
        prev = (self.etcd.get(K_TRABAJO) or {}).get("id")
        code, body = cluster_api._ejecutar(params)
        if code != 202:
            raise RuntimeError(body.get("error", "no se pudo enviar el análisis"))
        t0 = time.time()
        while time.time() - t0 < timeout:
            job = self.etcd.get(K_TRABAJO) or {}
            if job.get("id") and job.get("id") != prev and job.get("estado") in ("done", "error", "cancelado"):
                if job["estado"] != "done":
                    raise RuntimeError(f"el análisis terminó en estado {job['estado']}: {job.get('error', '')}")
                return job["resultado"]
            time.sleep(1)
        raise RuntimeError("el análisis no terminó a tiempo")


def _info_row(name: str, info: dict) -> dict:
    from coordinador import node_cost_hour  # noqa: PLC0415
    ch = node_cost_hour(info)
    return {"nombre": name, "proveedor": info.get("provider"), "pais": info.get("pais"),
            "region": info.get("region"), "cpus": info.get("cpus"), "modelo": info.get("modelo"),
            "costo_hora": round(ch, 5), "costo_mes": round(ch * 730, 2), "cobro_fijo": not float(info.get("costo_hora") or 0)}


# ------------------------------------------------------------------ P1
def p1(c: Ctx) -> dict:
    nodes = c.nodos()
    targets = [c.target(n, nodes) for n in nodes]
    r = c.call(CLIENTE, "/eval/rtt", {"targets": targets, "n": 60}, timeout=400, nodes=nodes)
    filas = []
    for d in r["destinos"]:
        km = dist_km(CLIENTE, d["nombre"])
        filas.append({**d, **_info_row(d["nombre"], nodes[d["nombre"]]), "km": km,
                      "minimo_fisico_ms": round(km / 100, 1) if km else 0.0,
                      "rol": ROL["p1"].get(d["nombre"], "Otra región"), "cumple": (d.get("p99") or 1e9) < 15})
    loc = next((f for f in filas if f["nombre"] == CLIENTE), None)
    us = next((f for f in filas if f["nombre"] == "usa"), None)
    cumplen = [f["nombre"] for f in filas if f["cumple"]]
    verbo = "respondió" if len(cumplen) == 1 else "respondieron"
    concl = (f"El cliente (el banco) está en Guayaquil. Solo {', '.join(x.upper() for x in cumplen) or 'ninguna nube'} "
             f"{verbo} el 99 % de las autorizaciones en menos de 15 ms")
    if loc:
        concl += f" (DC local: p99 = {es(loc['p99'], 2)} ms)"
    if us:
        concl += (f". AWS en Ohio tardó p50 = {es(us['p50'])} ms y p99 = {es(us['p99'])} ms, con {es(us['bajo_15'], 0)} % "
                  f"bajo 15 ms; a {es(us['km'], 0)} km, el mínimo físico ya es ≈ {es(us['minimo_fisico_ms'], 0)} ms. "
                  "Ningún SLA de disponibilidad compensa la distancia: el microservicio va en el DC local.")
    return {"cliente": CLIENTE, "umbral_ms": 15, "filas": filas, "conclusion": concl}


# ------------------------------------------------------------------ P2
JURIS = {
    "EC": ("LOPDP (Ecuador)", False, "No hay transferencia internacional"),
    "DE": ("GDPR (Unión Europea)", True, "Transferencia internacional; proveedor europeo, fuera del CLOUD Act"),
    "US": ("Leyes de EE. UU.", True, "Transferencia internacional + CLOUD Act (acceso extraterritorial)"),
    "HK": ("PDPO (Hong Kong) y leyes de China", True, "Transferencia internacional; proveedor chino"),
    "AR": ("Ley 25.326 (Argentina)", True, "Transferencia internacional"),
}


def p2(c: Ctx) -> dict:
    nodes = c.nodos()
    env = c.call_all("/eval/entorno", {}, timeout=40)
    filas = []
    for n, info in nodes.items():
        e = env.get(n, {})
        geo = e.get("geo") or {}
        esperado = PAIS_ISO.get(str(info.get("pais", "")).lower())
        real = geo.get("country")
        ley, transf, nota = JURIS.get(real or "", ("—", True, "—"))
        if n == "usa" or info.get("provider") == "aws":
            nota = "Transferencia internacional + CLOUD Act (acceso extraterritorial)"
        filas.append({**_info_row(n, info), "ip": geo.get("ip"), "ciudad": geo.get("city"), "pais_real": real,
                      "pais_esperado": esperado, "org": geo.get("org"), "coincide": (real == esperado) if real else None,
                      "ley": ley, "transferencia": transf, "nota": nota, "rol": ROL["p2"].get(n, "")})
    # análisis soberano: el último trabajo hecho SOLO con servidores en Ecuador
    sob = None
    for h in reversed(c.historial()):
        hechos = [x for x in h.get("nodos", []) if x.get("fragmentos")]
        if hechos and all(str(x.get("pais", "")).lower() == "ecuador" for x in hechos) and h.get("modo") == "contar":
            sob = h
            break
    if sob is None:
        name, _ = c.genoma()
        if name:
            sob = c.analizar({"archivos": [name], "patrones": ["TATAAA", "GAATTC"], "chunk_mb": 96,
                              "solo_pais": "Ecuador"})
    soberano = None
    if sob:
        soberano = {"id": sob["id"], "segundos": sob["segundos"], "gb": round(sob["bytes"] / 1e9, 2),
                    "nubes": [x["nodo"] for x in sob["nodos"] if x.get("fragmentos")],
                    "bytes_red": sum(x.get("bytes_red", 0) for x in sob["nodos"]),
                    "gc": (sob.get("resultado") or {}).get("gc_pct")}
    falsos = [f["nombre"] for f in filas if f["coincide"] is False]
    sin_dato = [f["nombre"] for f in filas if f["coincide"] is None]
    if falsos:
        concl = f"Atención: la ubicación real de {', '.join(x.upper() for x in falsos)} no coincide con la declarada. "
    elif sin_dato:
        concl = f"No se pudo geolocalizar la IP de {', '.join(x.upper() for x in sin_dato)}. "
    else:
        concl = f"La ubicación declarada de las {len(filas)} nubes coincide con la de su IP pública real. "
    concl += ("Solo Telecu (equivalente a CNT EP) deja los datos en Ecuador, sin transferencia internacional. "
              "OVHcloud exige cláusulas y registro ante la SPDP, pero no está sujeto al CLOUD Act; "
              "AWS suma el riesgo del CLOUD Act. ")
    if soberano:
        concl += (f"Prueba: el genoma ({es(soberano['gb'], 2)} GB) se procesó solo en "
                  f"{', '.join(soberano['nubes']).upper()} en {es(soberano['segundos'])} s, con "
                  f"{es(soberano['bytes_red'], 0)} bytes de datos enviados fuera del país.")
    return {"filas": filas, "soberano": soberano, "conclusion": concl}


# ------------------------------------------------------------------ P3
def _aws_egress(gb: float) -> float:
    tiers = [(100, 0.0), (10 * 1024, 0.09), (40 * 1024, 0.085), (100 * 1024, 0.07), (float("inf"), 0.05)]
    cost, rest = 0.0, gb
    for size, price in tiers:
        take = min(rest, size)
        cost += take * price
        rest -= take
        if rest <= 0:
            break
    return cost


PRECIOS_EGRESS = {
    "aws": ("Por GB: 100 GB gratis, luego USD 0,09/GB (escalonado)", _aws_egress, None),
    "ovhcloud": ("Incluido y sin límite (sin cargo de egreso)", lambda gb: 0.0, None),
    "huawei": ("Por GB ≈ USD 0,081 (EIP por tráfico, máx. 300 Mbit/s)", lambda gb: gb * 0.081, 300),
    "donweb": ("Incluido en la mensualidad (tarifa fija)", lambda gb: 0.0, "medido"),
    "telecu": ("Incluido en la mensualidad (tarifa fija)", lambda gb: 0.0, "medido"),
}


def p3(c: Ctx) -> dict:
    nodes = c.nodos()
    otros = [c.target(n, nodes) for n in nodes if n != CLIENTE]
    r1 = c.call(CLIENTE, "/eval/bajada", {"targets": otros, "mb": 32}, timeout=600, nodes=nodes)
    medido = {d["nombre"]: d for d in r1["destinos"]}
    if "usa" in nodes and CLIENTE in nodes:
        r2 = c.call("usa", "/eval/bajada", {"targets": [c.target(CLIENTE, nodes)], "mb": 32}, timeout=300, nodes=nodes)
        medido[CLIENTE] = r2["destinos"][0]
    escenarios = [1, 10, 50]
    filas = []
    for n, info in nodes.items():
        prov = info.get("provider", "")
        desc, fn, cap = PRECIOS_EGRESS.get(prov, ("—", lambda gb: 0.0, None))
        m = medido.get(n, {})
        cap_mbps = m.get("mbps") if cap == "medido" else cap
        base = _info_row(n, info)
        esc = []
        for tb in escenarios:
            gb = tb * 1024
            prom = tb * 1e12 * 8 / (30 * 86400) / 1e6
            pico = prom * 3
            eg = fn(gb)
            satura = bool(cap_mbps) and pico > cap_mbps
            esc.append({"tb": tb, "mbps_promedio": round(prom, 1), "mbps_pico": round(pico, 1),
                        "egress_usd": round(eg, 2), "total_usd": round(base["costo_mes"] + eg, 2), "satura": satura})
        filas.append({**base, "rol": ROL["p3"].get(n, ""), "egress": desc, "mbps_medido": m.get("mbps"),
                      "mb_s_medido": m.get("mb_s"), "limite_mbps": cap_mbps, "escenarios": esc})
    hist = c.historial()
    ult = hist[-1] if hist else None
    red_analisis = sum(x.get("bytes_red", 0) for x in ult["nodos"]) if ult else None
    aws = next((f for f in filas if f["proveedor"] == "aws"), None)
    tel = next((f for f in filas if f["proveedor"] == "telecu"), None)
    concl = ""
    if aws:
        e50 = aws["escenarios"][-1]
        concl += (f"Con 50 TB/mes de video, AWS cobraría USD {es(e50['egress_usd'], 0)} solo de egreso "
                  f"(USD {es(e50['total_usd'], 0)} en total): el costo crece con el éxito. ")
    concl += "OVHcloud no cobra egreso; Huawei cobra menos por GB, pero limita la EIP a 300 Mbit/s. "
    if tel and tel.get("mbps_medido"):
        e = tel["escenarios"][-1]
        concl += (f"El VPS local de tarifa fija (Telecu) cuesta USD {es(tel['costo_mes'], 2)} con cualquier tráfico, "
                  f"pero entregó {es(tel['mbps_medido'])} Mbit/s medidos: un pico de {es(e['mbps_pico'], 0)} Mbit/s "
                  f"{'lo satura' if e['satura'] else 'todavía cabe'}. ")
    if red_analisis is not None:
        concl += f"El clúster evita el egreso: el último análisis envió {es(red_analisis, 0)} bytes de datos por la red."
    return {"cliente": CLIENTE, "filas": filas, "escenarios_tb": escenarios, "conclusion": concl,
            "nota": "Precio de Huawei: valor de ejemplo de su documentación; el real depende de la región."}


# ------------------------------------------------------------------ P4
def p4(c: Ctx) -> dict:
    nodes = c.nodos()
    res = c.call_all("/eval/bench", {}, timeout=180)
    filas = []
    for n, info in nodes.items():
        b = res.get(n, {})
        base = _info_row(n, info)
        ch = base["costo_hora"] or None
        filas.append({**base, **{k: b.get(k) for k in ("gflops", "muestras_s", "segundos_entreno", "precision",
                                                         "acelerador", "error")},
                      "gflops_usd": round(b["gflops"] / ch, 0) if ch and b.get("gflops") else None,
                      "rol": ROL["p4"].get(n, "")})
    ok = [f for f in filas if f.get("gflops")]
    best = max(ok, key=lambda f: f["gflops"]) if ok else None
    precs = {f["precision"] for f in ok}
    us = next((f for f in ok if f["nombre"] == "usa"), None)
    cn = next((f for f in ok if f["nombre"] == "china"), None)
    concl = ""
    if best:
        concl += f"La nube más potente para cómputo fue {best['nombre'].upper()} ({es(best['gflops'])} GFLOPS). "
    if us and cn:
        concl += (f"Entrenando la misma red neuronal, AWS procesó {es(us['muestras_s'], 0)} muestras/s y Huawei "
                  f"{es(cn['muestras_s'], 0)} muestras/s. ")
    sin_acel = all(f.get("acelerador") == "ninguno" for f in ok)
    if sin_acel:
        concl += (f"Ninguna de las {len(ok)} máquinas tiene GPU ni NPU: para deep learning real habría que contratar "
                  "aceleradores (NVIDIA, TPU o Trainium en EE. UU.; Ascend en Huawei), y ahí se pierde la portabilidad. ")
    if len(precs) == 1 and ok:
        concl += (f"Las {len(ok)} nubes llegaron a la misma precisión ({es(precs.pop(), 2)} %): con CPU, el mismo "
                  "contenedor entrena el mismo modelo.")
    return {"filas": filas, "conclusion": concl}


# ------------------------------------------------------------------ P5
def p5(c: Ctx) -> dict:
    from coordinador import K_CEDER  # noqa: PLC0415
    nodes = c.nodos()
    env = c.call_all("/eval/entorno", {}, timeout=40)
    filas = []
    for n, info in nodes.items():
        e = env.get(n, {})
        filas.append({**_info_row(n, info), "imagen": e.get("imagen"), "arquitectura": e.get("arquitectura"),
                      "kernel": e.get("kernel"), "so": e.get("so_contenedor"), "metadatos": e.get("metadatos"),
                      "rol": ROL["p5"].get(n, "")})
    imagenes = {f["imagen"] for f in filas if f.get("imagen")}
    # rotación del mando por los 5 proveedores (interoperabilidad real)
    c.trabajo_libre()
    original = c.lider()
    orden = [n for n in ["europa", "china", "latam", "ecuador", "usa"] if n in nodes]
    if original in orden:
        orden.remove(original)
        orden.append(original)
    traspasos = []
    actual = original
    for dest in orden:
        if dest == actual:
            continue
        c.etcd.put(K_CEDER, dest, lease=c.etcd.grant(25))
        secs = c.esperar(lambda d=dest: c.lider() == d, 30)
        traspasos.append({"de": actual, "a": dest, "segundos": secs,
                          "de_prov": nodes.get(actual, {}).get("provider"), "a_prov": nodes[dest].get("provider")})
        if secs is None:
            break
        actual = dest
        time.sleep(1.5)
    total_mes = sum(f["costo_mes"] for f in filas)
    barata = min(filas, key=lambda f: f["costo_mes"]) if filas else None
    ok = [t for t in traspasos if t["segundos"] is not None]
    concl = (f"La misma imagen ({', '.join(sorted(imagenes)) or 'sin dato'}) corre en {len(filas)} proveedores sin "
             "cambiar código. " if len(imagenes) <= 1 else
             f"Atención: hay {len(imagenes)} versiones de la imagen; actualice el clúster. ")
    if ok:
        concl += (f"El mando del clúster pasó por {len(ok)} proveedores distintos, en {es(min(t['segundos'] for t in ok))} a "
                  f"{es(max(t['segundos'] for t in ok))} s cada vez, gracias a la capa común (etcd + WireGuard). ")
    apis = sorted({f["metadatos"] for f in filas if f.get("metadatos")})
    concl += (f"La complejidad está en lo propio de cada nube: su API de metadatos ({'; '.join(apis)}), su firewall "
              "y su facturación. ")
    if barata:
        concl += (f"Duplicación de costos: las {len(filas)} nubes cuestan USD {es(total_mes, 2)} al mes, frente a "
                  f"USD {es(barata['costo_mes'], 2)} de la más barata sola ({barata['proveedor']}).")
    return {"filas": filas, "traspasos": traspasos, "lider_original": original, "costo_mes_total": round(total_mes, 2),
            "conclusion": concl}


# ------------------------------------------------------------------ P6
def p6(c: Ctx) -> dict:
    nodes = c.nodos()
    name, replicas = c.genoma()
    if not name:
        raise RuntimeError("no hay un genoma listo en las nubes")
    size = None
    for f in nodes.get(CLIENTE, {}).get("archivos", []):
        if f["nombre"] == name:
            size = f.get("bytes")
    off = int(min(1 << 30, max((size or 0) // 3, 0)))
    otros = [c.target(n, nodes) for n in nodes if n != CLIENTE and n in replicas]
    r = c.call(CLIENTE, "/eval/leer", {"archivo": name, "offset": off, "longitud": 64 * MB, "targets": otros},
               timeout=900, nodes=nodes)
    lect = []
    for x in r["lecturas"]:
        km = dist_km(CLIENTE, x["nombre"]) or 0
        lect.append({**x, "km": km, "rol": ROL["p6"].get(x["nombre"], ""), "proveedor": nodes.get(x["nombre"], {}).get("provider")})
    p_sitio = 0.01
    durab = [{"replicas": k, "perdida": p_sitio ** k, "nueves": 2 * k,
              "durabilidad": f"{es((1 - p_sitio ** k) * 100, max(2 * k - 2, 0))} %"} for k in range(1, 6)]
    loc = next((x for x in lect if x.get("local")), None)
    rem = [x for x in lect if not x.get("local") and x.get("segundos")]
    iguales = all(x.get("identico") for x in lect if "error" not in x)
    conts = len({CONTINENTE.get(n, n) for n in replicas})
    concl = (f"El genoma tiene {len(replicas)} réplicas idénticas (mismo SHA-256) en {len(replicas)} nubes de "
             f"{conts} continente{'s' if conts != 1 else ''}. ")
    if loc and rem:
        lento = max(rem, key=lambda x: x["segundos"])
        rapido = min(rem, key=lambda x: x["segundos"])
        concl += (f"Recuperar 64 MB desde la copia local de Ecuador tomó {es(loc['segundos'], 2)} s; desde la réplica "
                  f"remota más rápida ({rapido['nombre'].upper()}), {es(rapido['segundos'], 2)} s, y desde la más lenta "
                  f"({lento['nombre'].upper()}), {es(lento['segundos'], 2)} s. ")
    concl += ("Más réplicas lejanas suben la durabilidad (con 1 % de pérdida anual por sitio: 1 réplica = 2 nueves, "
              "5 réplicas = 10 nueves), pero la recuperación lejana es más lenta: lo caliente va cerca y la copia "
              "maestra, distribuida. ")
    concl += "Los bloques recuperados son idénticos en todas las réplicas." if iguales else "¡Una réplica devolvió datos distintos!"
    return {"archivo": name, "offset": off, "bytes": r["bytes"], "replicas": replicas, "lecturas": lect,
            "durabilidad": durab, "p_sitio": p_sitio, "conclusion": concl}


# ------------------------------------------------------------------ P7
def p7(c: Ctx) -> dict:
    nodes = c.nodos()
    names = [n for n in [CLIENTE, "latam", "usa", "china", "europa"] if n in nodes]
    r = c.call(CLIENTE, "/eval/iot", {"targets": [c.target(n, nodes) for n in names], "lotes": 40,
                                      "sensores": 200}, timeout=600, nodes=nodes)
    filas = []
    for d in r["destinos"]:
        filas.append({**d, "rol": ROL["p7"].get(d["nombre"], "Nube central"), "km": dist_km(CLIENTE, d["nombre"]),
                      "proveedor": nodes[d["nombre"]].get("provider"),
                      "reduccion_pct": round((1 - d["bytes_resumen"] / d["bytes_crudos"]) * 100, 1) if d["bytes_crudos"] else None})
    borde = next((f for f in filas if f["nombre"] == CLIENTE), None)
    hw = next((f for f in filas if f["nombre"] == "china"), None)
    concl = f"Se simularon {r['sensores']} sensores en Ecuador ({es(r['lecturas'], 0)} lecturas). "
    if borde:
        concl += f"Decidiendo en el borde local (Telecu), la reacción fue p95 = {es(borde['p95'])} ms"
    if hw:
        concl += f"; enviando cada lote a Huawei en Hong Kong, p95 = {es(hw['p95'])} ms"
    concl += ". "
    if borde and borde.get("reduccion_pct") is not None:
        concl += (f"Además, el borde solo sube un resumen: {es(borde['reduccion_pct'])} % menos datos hacia la nube "
                  "central. "
                  "Huawei tiene la plataforma de borde más madura (IEF), pero sin infraestructura en Ecuador; "
                  "la cercanía física manda.")
    return {"cliente": CLIENTE, "sensores": r["sensores"], "lecturas": r["lecturas"], "filas": filas, "conclusion": concl}


# ------------------------------------------------------------------ P8
def p8(c: Ctx) -> dict:
    from coordinador import K_APAGADO, K_CEDER  # noqa: PLC0415
    nodes = c.nodos()
    c.trabajo_libre()
    lider0 = c.lider()
    internac = [n for n, i in nodes.items() if str(i.get("pais", "")).lower() != "ecuador"]
    nacionales = [n for n in nodes if n not in internac]
    if not nacionales:
        raise RuntimeError("no hay una nube en Ecuador viva")
    pasos = []
    t0 = time.time()
    for n in internac:
        c.etcd.put(K_APAGADO + n, str(time.time()))
    pasos.append({"t": 0.0, "evento": f"Corte simulado: se aíslan {', '.join(x.upper() for x in internac)} (fuera de Ecuador)"})
    try:
        secs = c.esperar(lambda: c.lider() in nacionales, 60, 0.2)
        pasos.append({"t": round(time.time() - t0, 1),
                      "evento": f"{(c.lider() or '?').upper()} queda como líder del clúster"
                      + (f" ({es(secs, 2)} s)" if secs is not None else " (no hubo traspaso a tiempo)")})
        r = c.call(CLIENTE, "/eval/rtt", {"targets": [c.target(n, nodes) for n in nodes], "segundos": 6},
                   timeout=180, nodes=nodes)
        disp = r["destinos"]
        pasos.append({"t": round(time.time() - t0, 1), "evento": "Se mide el servicio de autorizaciones durante el corte (6 s)"})
    finally:
        for n in internac:
            c.etcd.delete(K_APAGADO + n)
    t_rest = time.time()
    rest = c.esperar(lambda: all(str((c.nodos().get(n) or {}).get("estado")) == "viva" for n in internac), 60, 0.5)
    pasos.append({"t": round(time.time() - t0, 1), "evento": f"Enlace restablecido: las {len(internac)} nubes vuelven"
                  + (f" en {es(rest, 2)} s" if rest is not None else "")})
    if lider0 and c.lider() != lider0:
        c.etcd.put(K_CEDER, lider0, lease=c.etcd.grant(25))
        back = c.esperar(lambda: c.lider() == lider0, 30)
        pasos.append({"t": round(time.time() - t0, 1), "evento": f"El mando vuelve a {lider0.upper()}"
                      + (f" ({es(back, 2)} s)" if back is not None else "")})
    try:
        miembros = [m.get("name") for m in c.etcd.members()]
    except Exception:  # noqa: BLE001
        miembros = list(nodes)
    locales = [m for m in miembros if m in nacionales]
    quorum = len(miembros) // 2 + 1
    filas = [{**d, "proveedor": nodes[d["nombre"]].get("provider"), "pais": nodes[d["nombre"]].get("pais"),
              "nacional": d["nombre"] in nacionales} for d in disp]
    loc = [f for f in filas if f["nacional"]]
    ext = [f for f in filas if not f["nacional"]]
    disp_loc = ", ".join(f"{es(x['disponibilidad'], 0)} %" for x in loc)
    concl = (f"Con el tráfico internacional cortado, el servicio crítico en el DC local siguió disponible "
             f"({disp_loc}) y respondió en p50 = {es(loc[0]['p50'] if loc else None, 2)} ms; los servicios en nubes "
             f"extranjeras quedaron al {es(max((f['disponibilidad'] for f in ext), default=0), 0)} %. ")
    miembro = "miembro" if len(locales) == 1 else "miembros"
    concl += (f"Lección de diseño: etcd necesita mayoría ({quorum} de {len(miembros)}) y en Ecuador hay "
              f"{len(locales)} {miembro}. En un corte real, la coordinación quedaría del lado con mayoría: una "
              "nube híbrida para continuidad debe tener la mayoría de su control (y 2 DC) dentro del país.")
    return {"pasos": pasos, "filas": filas, "quorum": quorum, "miembros": miembros, "miembros_locales": locales,
            "lider_original": lider0, "conclusion": concl}


# ------------------------------------------------------------------ escalabilidad (Rendimiento)
def escalabilidad(c: Ctx) -> dict:
    nodes = c.nodos()
    name, where = c.genoma()
    if not name:
        raise RuntimeError("no hay un genoma listo en las nubes")
    orden = [n for n in ["usa", "europa", "china", "latam", "ecuador"] if n in nodes and n in where]
    base1 = next((h.get("seg_1_nucleo") for h in reversed(c.historial()) if h.get("seg_1_nucleo")), None)
    puntos = []
    for k in range(1, len(orden) + 1):
        sel = orden[:k]
        r = c.analizar({"archivos": [name], "patrones": ["TATAAA", "GAATTC"], "chunk_mb": 96, "nodos": sel})
        procs = sum(int(nodes[n].get("cpus") or 1) for n in sel)
        puntos.append({"nubes": k, "seleccion": sel, "procesos": procs, "segundos": r["segundos"],
                       "gb_s": r["gb_s"], "id": r["id"]})
        _guardar(c, "escalabilidad", {"estado": "corriendo", "parcial": puntos, "inicio": time.time()})
    t1 = puntos[0]["segundos"] if puntos else None
    for p in puntos:
        p["speedup_vs_1nube"] = round(t1 / p["segundos"], 2) if t1 else None
        if base1:
            s = base1 / p["segundos"]
            p["speedup"] = round(s, 2)
            p["eficiencia"] = round(s / p["procesos"] * 100, 1)
            p["karp_flatt"] = round((1 / s - 1 / p["procesos"]) / (1 - 1 / p["procesos"]), 3) if p["procesos"] > 1 else None
    concl = ""
    if puntos:
        last = puntos[-1]
        concl = (f"Con 1 nube ({orden[0].upper()}) el genoma tardó {es(puntos[0]['segundos'])} s; con {last['nubes']} "
                 f"nubes, {es(last['segundos'])} s ({es(last['speedup_vs_1nube'], 2)}× más rápido). ")
        if base1:
            concl += (f"Frente a 1 núcleo ({es(base1)} s), el speedup llega a {es(last.get('speedup'), 2)}× con "
                      f"{last['procesos']} procesos: eficiencia {es(last.get('eficiencia'))} %. La curva se aplana porque "
                      "cada nube nueva aporta menos (CPU más lentas) y la coordinación intercontinental pesa más.")
    return {"base_1_nucleo": base1, "orden": orden, "puntos": puntos, "conclusion": concl}


FUNCS = {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5, "p6": p6, "p7": p7, "p8": p8,
         "escalabilidad": escalabilidad}
_LOCK = threading.Lock()
_RUNNING: set[str] = set()


def _guardar(c: Ctx, q: str, val: dict) -> None:
    c.etcd.put(K_EVAL + q, val)


def _correr(c: Ctx, qs: list[str]) -> None:
    for q in qs:
        prev = c.etcd.get(K_EVAL + q)
        t0 = time.time()
        _guardar(c, q, {"estado": "corriendo", "inicio": t0,
                        "anterior": prev.get("datos") if isinstance(prev, dict) else None,
                        "anterior_fin": prev.get("fin") if isinstance(prev, dict) else None})
        try:
            datos = FUNCS[q](c)
            _guardar(c, q, {"estado": "listo", "inicio": t0, "fin": time.time(),
                            "segundos": round(time.time() - t0, 1), "datos": datos})
        except Exception as exc:  # noqa: BLE001
            _guardar(c, q, {"estado": "error", "inicio": t0, "fin": time.time(), "error": str(exc)[:400],
                            "datos": prev.get("datos") if isinstance(prev, dict) else None})
        finally:
            with _LOCK:
                _RUNNING.discard(q)


def lanzar(etcd, coord, pregunta: str) -> tuple[int, dict]:
    qs = [f"p{i}" for i in range(1, 9)] if pregunta == "todas" else [pregunta]
    if any(q not in FUNCS for q in qs):
        return 400, {"error": "pregunta inválida"}
    with _LOCK:
        if _RUNNING:
            return 409, {"error": f"ya se está ejecutando {', '.join(sorted(_RUNNING))}"}
        for q in qs:
            v = etcd.get(K_EVAL + q)
            if isinstance(v, dict) and v.get("estado") == "corriendo" and time.time() - float(v.get("inicio", 0)) < 1200:
                return 409, {"error": f"{q} ya se está ejecutando en otro dashboard"}
        _RUNNING.update(qs)
    c = Ctx(etcd, coord)
    for q in qs:
        _guardar(c, q, {**(etcd.get(K_EVAL + q) or {}), "estado": "en cola", "inicio": time.time()})
    threading.Thread(target=_correr, args=(c, qs), daemon=True).start()
    return 202, {"mensaje": f"ejecutando {', '.join(qs)}"}


def estado(etcd) -> dict:
    raw = etcd.get_prefix(K_EVAL, serial=True)
    return {"resultados": {k[len(K_EVAL):]: v for k, v in raw.items()}, "local": sorted(_RUNNING),
            "ahora": time.time()}
