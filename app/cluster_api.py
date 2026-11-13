"""
cluster_api.py - API del clúster para el dashboard (lee y escribe en etcd).

Funciona desde CUALQUIER nube del clúster (APP_MODE=nodo) o desde la PC con un
túnel SSH hacia etcd (ETCD_ENDPOINTS=http://localhost:2379). No importa en qué
nube esté el líder: el dashboard deja los comandos en etcd y el líder los toma.

  GET  /api/cluster/estado      nodos, líder del clúster, líder de etcd, trabajo,
                                fragmentos, red entre nubes, historial, eventos
  POST /api/cluster/ejecutar    {archivos:[...], patrones:[...], chunk_mb, max_hilos,
                                 nodos:[...], solo_pais, verificar, modo, lider_solo_reparte}
  POST /api/cluster/ceder       {destino: "europa"}   ("" = orden normal)
  POST /api/cluster/apagar      {nodo}     POST /api/cluster/encender {nodo}
  POST /api/cluster/red         mide RTT y MB/s entre todas las nubes
  POST /api/cluster/cancelar
  POST /api/cluster/descargar   {url, archivo}  -> cada nube descarga el FASTA
                                {origen, archivo} -> las demás lo copian desde esa nube
  POST /api/cluster/olvidar_descarga {archivo}
"""

from __future__ import annotations

import json
import os
import re
import time

from coordinador import (K_APAGADO, K_CANCEL, K_CEDER, K_CMD, K_DESCARGAS, K_EVT, K_FRAG, K_HIST,
                         K_LIDER, K_MEDIR, K_NODOS, K_RED, K_REGISTRO, K_TRABAJO)
from etcd_client import Etcd, EtcdError

ETCD: Etcd | None = None
COORD = None
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.(fasta|fa|fna|fas|txt)$", re.IGNORECASE)
NODE_RE = re.compile(r"^[a-z0-9-]{1,40}$")
ORDER = [x.strip() for x in os.getenv("ORDEN", "usa,europa,china,latam,ecuador").split(",") if x.strip()]


def init(etcd: Etcd | None = None, coord=None) -> None:
    global ETCD, COORD
    COORD = coord
    if etcd is not None:
        ETCD = etcd
    elif os.getenv("ETCD_ENDPOINTS"):
        ETCD = Etcd(os.getenv("ETCD_ENDPOINTS"))


def start() -> None:          # compatibilidad con versiones anteriores
    init()


def _strip(prefix: str, d: dict) -> dict:
    return {k[len(prefix):]: v for k, v in d.items()}


def estado() -> dict:
    if ETCD is None:
        return {"modo": "sin_etcd", "mensaje": "Este dashboard no está conectado a etcd. Abra el túnel SSH "
                "(ssh -L 2379:127.0.0.1:2379 usa) y defina ETCD_ENDPOINTS=http://localhost:2379, "
                "o abra el dashboard de una de las nubes."}
    try:
        live = _strip(K_NODOS, ETCD.get_prefix(K_NODOS))
        reg = _strip(K_REGISTRO, ETCD.get_prefix(K_REGISTRO))
        off = set(_strip(K_APAGADO, ETCD.get_prefix(K_APAGADO, keys_only=True)))
        lider = ETCD.get(K_LIDER, as_json=False)
        ceder = ETCD.get(K_CEDER, as_json=False)
        try:
            etcd_lider = ETCD.leader_name()
            members = ETCD.members()
        except EtcdError:
            etcd_lider, members = None, []
        job = ETCD.get(K_TRABAJO)
        frags = []
        if isinstance(job, dict):
            for rec in ETCD.get_prefix(f"{K_FRAG}{job['id']}/").values():
                if isinstance(rec, dict):
                    frags.append([rec["i"], rec["nodo"], rec["t0"], rec["t1"], rec.get("modo"), rec.get("bytes", 0)])
        hist = ETCD.get_prefix(K_HIST)
        evts = ETCD.get_prefix(K_EVT)
        red = _strip(K_RED, ETCD.get_prefix(K_RED))
        pend = len(ETCD.get_prefix(K_CMD, keys_only=True))
        descargas = _strip(K_DESCARGAS, ETCD.get_prefix(K_DESCARGAS, as_json=False))
    except EtcdError as exc:
        return {"modo": "etcd_error", "mensaje": f"etcd no responde: {exc}"}

    names = [n for n in ORDER if n in live or n in reg] + sorted((set(live) | set(reg)) - set(ORDER))
    nodes = []
    for n in names:
        if n in live:
            entry = dict(live[n])
        else:
            entry = dict(reg.get(n, {}), estado="caida")
        entry.update(nombre=n, es_lider=(n == lider), apagado_flag=n in off)
        nodes.append(entry)
    etcd_members = [{"nombre": m.get("name"), "urls": m.get("clientURLs", [])} for m in members]
    # limpieza: conservar solo los últimos MAX eventos
    keys = sorted(evts)
    if len(keys) > 400:
        try:
            for k in keys[:-300]:
                ETCD.delete(k)
        except EtcdError:
            pass
    return {
        "modo": "etcd", "conectado_via": os.getenv("NODE_NAME") or _via(), "lider": lider,
        "etcd_lider": etcd_lider, "etcd_miembros": etcd_members, "ceder": ceder,
        "nodos": nodes, "trabajo": job, "fragmentos": sorted(frags),
        "historial": [hist[k] for k in sorted(hist)][-30:], "eventos": [evts[k] for k in keys[-80:]],
        "red": red, "comandos_pendientes": pend, "descargas": descargas, "ahora": time.time(),
    }


def _via() -> str:
    e = ETCD.endpoints[ETCD._pref] if ETCD and ETCD.endpoints else ""
    return f"túnel {e}" if "localhost" in e or "127.0.0.1" in e else e


def _body(raw: bytes) -> dict:
    try:
        d = json.loads(raw or b"{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        raise ValueError("JSON inválido") from None


def handle_post(path: str, query: dict, raw: bytes) -> tuple[int, dict]:
    if ETCD is None:
        return 400, {"error": "El dashboard no está conectado a etcd"}
    try:
        p = _body(raw)
        action = path.rsplit("/", 1)[-1]
        if action == "ejecutar":
            return _ejecutar(p)
        if action == "ceder":
            dest = str(p.get("destino") or "")
            if not dest:
                ETCD.delete(K_CEDER)
                return 200, {"mensaje": "orden normal de liderazgo"}
            if not NODE_RE.match(dest):
                return 400, {"error": "nodo inválido"}
            ETCD.put(K_CEDER, dest, lease=ETCD.grant(20))
            return 200, {"mensaje": f"el líder cederá el mando a {dest}"}
        if action in ("apagar", "encender"):
            node = str(p.get("nodo", ""))
            if not NODE_RE.match(node):
                return 400, {"error": "nodo inválido"}
            if action == "apagar":
                ETCD.put(K_APAGADO + node, str(time.time()))
            else:
                ETCD.delete(K_APAGADO + node)
            return 200, {"mensaje": f"{node}: {action}"}
        if action == "red":
            ETCD.put(K_MEDIR, str(time.time()))
            return 202, {"mensaje": "todas las nubes miden la red"}
        if action == "cancelar":
            job = ETCD.get(K_TRABAJO)
            if not isinstance(job, dict) or job.get("estado") != "running":
                return 409, {"error": "no hay un trabajo en curso"}
            ETCD.put(K_CANCEL, job["id"], lease=ETCD.grant(60))
            return 200, {"mensaje": "cancelando"}
        if action == "descargar":
            url, name = str(p.get("url", "")).strip(), str(p.get("archivo", "")).strip()
            origin = str(p.get("origen", "")).strip()
            if not NAME_RE.match(name):
                return 400, {"error": "nombre de archivo inválido (.fna .fa .fasta .fas .txt, sin espacios)"}
            if origin:
                info = ETCD.get(K_NODOS + origin)
                files = {f.get("nombre"): f for f in (info or {}).get("archivos", [])} if isinstance(info, dict) else {}
                if not files.get(name, {}).get("listo"):
                    return 409, {"error": f"{origin.upper()} todavía no tiene {name} listo"}
                ETCD.put(K_DESCARGAS + name, f"nodo:{origin}")
                return 202, {"mensaje": f"las demás nubes copiarán {name} desde {origin.upper()} por WireGuard"}
            if not url.startswith(("https://", "http://")):
                return 400, {"error": "URL inválida (debe empezar con https://)"}
            ETCD.put(K_DESCARGAS + name, url)
            return 202, {"mensaje": f"las nubes descargarán {name}"}
        if action == "olvidar_descarga":
            name = str(p.get("archivo", "")).strip()
            if not NAME_RE.match(name):
                return 400, {"error": "nombre inválido"}
            ETCD.delete(K_DESCARGAS + name)
            return 200, {"mensaje": f"orden de descarga de {name} eliminada"}
        return 404, {"error": "no encontrado"}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except EtcdError as exc:
        return 503, {"error": f"etcd no responde: {exc}"}


def _ejecutar(p: dict) -> tuple[int, dict]:
    files = [str(x) for x in (p.get("archivos") or [])]
    modo = p.get("modo", "contar")
    if modo not in ("contar", "comparar"):
        return 400, {"error": "modo inválido"}
    if not files or not all(NAME_RE.match(f) for f in files):
        return 400, {"error": "elija uno o más archivos FASTA"}
    if modo == "comparar" and len(files) != 2:
        return 400, {"error": "para comparar elija exactamente 2 archivos"}
    pats = [str(x).strip().upper() for x in (p.get("patrones") or []) if str(x).strip()]
    if len(pats) > 10 or not all(re.fullmatch(r"[ACGTN]{1,64}", x) for x in pats):
        return 400, {"error": "patrones: hasta 10, solo A, C, G, T, N"}
    try:
        chunk = int(p.get("chunk_mb", 96))
        hilos = int(p.get("max_hilos", 0))
    except (TypeError, ValueError):
        return 400, {"error": "chunk_mb y max_hilos deben ser enteros"}
    if not 1 <= chunk <= 512 or not 0 <= hilos <= 64:
        return 400, {"error": "chunk_mb entre 1 y 512; max_hilos entre 0 y 64"}
    nodos = [n for n in (p.get("nodos") or []) if NODE_RE.match(str(n))]
    job = ETCD.get(K_TRABAJO)
    if isinstance(job, dict) and job.get("estado") == "running":
        return 409, {"error": "ya hay un trabajo en curso"}
    params = {"modo": modo, "archivos": files, "patrones": pats if modo == "contar" else [],
              "chunk_mb": chunk, "max_hilos": hilos, "nodos": nodos, "solo_pais": p.get("solo_pais") or None,
              "verificar": bool(p.get("verificar")), "lider_solo_reparte": bool(p.get("lider_solo_reparte"))}
    ETCD.put(f"{K_CMD}{time.time():017.6f}", {"tipo": "analizar", "params": params, "desde": os.getenv("NODE_NAME", "pc")})
    lider = ETCD.get(K_LIDER, as_json=False)
    return 202, {"mensaje": f"trabajo enviado al líder ({lider or 'eligiéndose…'})", "params": params}
