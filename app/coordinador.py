"""
coordinador.py - Coordinación del clúster con etcd (corre en CADA nube).

Cada nodo:
  1. Publica su LATIDO en etcd (/adn/nodos/<nombre>) con un lease de 10 s:
     recursos, CPU por núcleo, archivos listos, IP pública y privada (WireGuard),
     costo. Si la nube muere, la clave expira sola: el clúster lo detecta.
  2. Participa en la ELECCIÓN DE LÍDER: el primero que crea /adn/lider (con un
     lease de 6 s) manda. Si el líder cae, su lease expira y otra nube toma el
     mando en segundos. Orden de prioridad configurable (ORDEN) y "ceder mando".
  3. Si es el líder: atiende la cola de comandos del dashboard y reparte los
     fragmentos a las nubes. Cada fragmento terminado se guarda en etcd
     (/adn/frag/<trabajo>/<n>): si el líder cae a mitad del trabajo, el nuevo
     líder lo RETOMA desde donde quedó, sin repetir lo ya hecho.
  4. Mide la red hacia las demás nubes (RTT y MB/s por WireGuard).
"""

from __future__ import annotations

import json
import os
import queue
import statistics
import threading
import time
import uuid
from urllib.parse import quote

import master as M
import seqcache
import worker as W
from etcd_client import Etcd, EtcdError

P = "/adn/"
K_NODOS, K_REGISTRO, K_LIDER, K_CEDER = P + "nodos/", P + "registro/", P + "lider", P + "ceder"
K_APAGADO, K_CMD, K_TRABAJO, K_FRAG = P + "apagado/", P + "comandos/", P + "trabajo", P + "frag/"
K_HIST, K_EVT, K_RED, K_MEDIR = P + "historial/", P + "eventos/", P + "red/", P + "medir_red"
K_CANCEL, K_DESCARGAS = P + "cancelar", P + "descargas/"

NODE_TTL, LEADER_TTL = 20, 6
ALIVE_S = 15   # sin latido por más de esto = nube caída (red intercontinental: 100-350 ms por llamada)
MAX_EVENTS = 300


def now() -> float:
    return round(time.time(), 3)


def node_cost_hour(info: dict) -> float:
    """US$/hora; si el proveedor cobra por mes, se prorratea (730 h/mes)."""
    h = float(info.get("costo_hora") or 0)
    return h if h > 0 else float(info.get("costo_mes") or 0) / 730


def event(etcd: Etcd, node: str, tipo: str, msg: str) -> None:
    try:
        etcd.put(f"{K_EVT}{time.time():017.6f}-{node}", {"t": now(), "nodo": node, "tipo": tipo, "msg": msg})
    except EtcdError:
        pass


class Coordinator:
    def __init__(self, etcd: Etcd, name: str, private_url: str, token: str, order: list[str]):
        self.etcd, self.name, self.url, self.token = etcd, name, private_url.rstrip("/"), token
        self.order = order or [name]
        self.is_leader = False
        self.leader_lease = None
        self.node_lease = None
        self.apagado = False
        self.cooldown_until = 0.0
        self.vacancy_since = None
        self.last_measure_req = None
        self.leader_thread = None
        self.stop = threading.Event()

    # ================================================================ arranque
    def start(self):
        try:
            self.etcd.put(K_REGISTRO + self.name, {**W.node_info(), "url": self.url, "registrado": now()})
        except EtcdError:
            pass
        event(self.etcd, self.name, "nodo", f"{self.name} se une al clúster")
        for target in (self._heartbeat_loop, self._election_loop, self._network_loop):
            threading.Thread(target=target, daemon=True).start()

    # ================================================================ latido
    def _heartbeat_loop(self):
        while not self.stop.is_set():
            try:
                if not self.node_lease or not self.etcd.keepalive(self.node_lease):
                    self.node_lease = self.etcd.grant(NODE_TTL)
                was = self.apagado
                self.apagado = self.etcd.get(K_APAGADO + self.name, serial=True) is not None
                W.OFFLINE = self.apagado
                if self.apagado != was:
                    event(self.etcd, self.name, "apagado" if self.apagado else "encendido",
                          f"{self.name} {'se apaga (simulado)' if self.apagado else 'vuelve a encenderse'}")
                with W.LOCK:
                    stats = dict(W.STATS, **W.WORK)
                info = W.node_info()
                files = [{k: f.get(k) for k in ("nombre", "bytes", "listo", "estado", "seq_sha256", "registros",
                                                 "error", "recibido", "total", "mb_s") if k in f or k == "listo"}
                         for f in W.list_data_files()]
                self.etcd.put(K_NODOS + self.name, {
                    **info, "url": self.url, "estado": "apagada" if self.apagado else "viva",
                    "es_lider": self.is_leader, "visto": now(), "stats": stats, "archivos": files,
                    "uptime": round(time.time() - W.STARTED)}, lease=self.node_lease)
                self._handle_downloads(files)
                self._prepare_pending(files)
                req = self.etcd.get(K_MEDIR, serial=True)
                if req and req != self.last_measure_req:
                    self.last_measure_req = req
                    threading.Thread(target=self.measure_network, daemon=True).start()
            except EtcdError:
                self.node_lease = None
            except Exception as exc:  # noqa: BLE001
                print(f"[{self.name}] latido: {exc}", flush=True)
            self.stop.wait(2)

    def _prepare_pending(self, files):
        """Un FASTA nuevo (o modificado) en /datos se limpia solo en segundo plano."""
        for f in files:
            if not f.get("listo") and not f.get("estado") and f.get("bytes"):
                W.FILE_STATE[f["nombre"]] = {"estado": "preparando"}
                threading.Thread(target=W.prepare_file, args=(os.path.join(W.DATA_DIR, f["nombre"]),),
                                 daemon=True).start()

    def _handle_downloads(self, files):
        # se reintenta solo si falló antes Y la orden cambió (p. ej. de URL a «copiar desde una nube»)
        tried = self.__dict__.setdefault("_dl_src", {})
        have = {f["nombre"] for f in files
                if not (f.get("estado") == "error" and not f.get("bytes"))}
        for key, src in self.etcd.get_prefix(K_DESCARGAS, as_json=False, serial=True).items():
            name, src = key[len(K_DESCARGAS):], str(src)
            if name in have or not W.FILE_RE.match(name) or tried.get(name) == src:
                continue
            tried[name] = src
            headers, origin = None, None
            if src.startswith("nodo:"):
                # replicación: copiar el archivo desde otra nube por la red privada WireGuard
                origin = src[5:]
                info = self.etcd.get(K_NODOS + origin)
                if origin == self.name or not isinstance(info, dict) or not info.get("url"):
                    continue
                url = f"{info['url']}/archivo?nombre={quote(name)}"
                headers = {"X-Token": self.token}
            elif src.startswith(("http://", "https://")):
                url = src
            else:
                continue
            W.FILE_STATE[name] = {"estado": "descargando"}
            threading.Thread(target=W.download_file, args=(url, name, headers), daemon=True).start()
            event(self.etcd, self.name, "datos",
                  f"{self.name} copia {name} desde {origin.upper()} (WireGuard)" if origin
                  else f"{self.name} descarga {name} desde la URL")

    # ================================================================ red
    def _network_loop(self):
        self.stop.wait(8)
        while not self.stop.is_set():
            self.measure_network()
            self.stop.wait(120)

    def measure_network(self):
        """RTT (ms) y transferencia (MB/s) desde este nodo hacia cada nube."""
        try:
            nodes = self.etcd.get_prefix(K_NODOS)
        except EtcdError:
            return
        out = {}
        payload = os.urandom(2 * M.MB)
        for key, info in nodes.items():
            other = key[len(K_NODOS):]
            if other == self.name or not isinstance(info, dict) or not info.get("url"):
                continue
            cli = M.RemoteNode(other, info["url"], self.token, timeout=15)
            try:
                rtts = []
                cli.health(timeout=5)
                for _ in range(5):
                    t = time.perf_counter()
                    cli.request("GET", "/health", timeout=5, auth=False)
                    rtts.append((time.perf_counter() - t) * 1000)
                _, wall = cli.request("POST", "/sink", payload, {"Content-Type": "application/octet-stream"}, timeout=30)
                base = min(rtts) / 1000
                out[other] = {"rtt_ms": round(statistics.median(rtts), 2),
                              "mb_s": round(2 / max(wall - base, wall * 0.05), 2)}
            except Exception as exc:  # noqa: BLE001
                out[other] = {"error": str(exc)[:120]}
        try:
            self.etcd.put(K_RED + self.name, {"t": now(), "destinos": out})
        except EtcdError:
            pass

    # ================================================================ elección
    def _alive_nodes(self) -> dict:
        """Nodos con latido reciente (< ALIVE_S). Un nodo que murió de golpe deja de
        contar antes de que su lease de NODE_TTL s expire en etcd."""
        nodes = self.etcd.get_prefix(K_NODOS, serial=True)
        limit = time.time() - ALIVE_S
        return {k[len(K_NODOS):]: v for k, v in nodes.items()
                if isinstance(v, dict) and float(v.get("visto") or 0) >= limit}

    def resign(self, why: str):
        lease = self.leader_lease
        try:
            self.etcd.delete_if(K_LIDER, self.name)
        except EtcdError:
            pass
        if lease:
            self.etcd.revoke(lease)
        self.is_leader, self.leader_lease = False, None
        self.cooldown_until = time.time() + 4
        event(self.etcd, self.name, "lider", f"{self.name} deja el mando ({why})")

    def _election_loop(self):
        while not self.stop.is_set():
            try:
                self._election_tick()
            except EtcdError:
                if self.is_leader:          # sin etcd no se puede asegurar el mando
                    self.is_leader = False
            except Exception as exc:  # noqa: BLE001
                print(f"[{self.name}] elección: {exc}", flush=True)
            self.stop.wait(0.5 if not self.is_leader else 1)

    def _election_tick(self):
        if self.apagado:
            if self.is_leader:
                self.resign("nube apagada")
            return
        if self.is_leader:
            ok = self.etcd.keepalive(self.leader_lease) and self.etcd.get(K_LIDER, as_json=False) == self.name
            if not ok:
                self.is_leader, self.leader_lease = False, None
                event(self.etcd, self.name, "lider", f"{self.name} perdió el mando")
                return
            target = self.etcd.get(K_CEDER, as_json=False)
            if target and target != self.name:
                alive = self._alive_nodes()
                if target in alive and alive[target].get("estado") == "viva":
                    self.resign(f"cede el mando a {target}")
                else:
                    self.etcd.delete(K_CEDER)
            return
        if time.time() < self.cooldown_until:
            return
        current = self.etcd.get(K_LIDER, as_json=False, serial=True)  # la txn create decide
        if current:
            self.vacancy_since = None
            return
        if self.vacancy_since is None:
            self.vacancy_since = time.time()
        target = self.etcd.get(K_CEDER, as_json=False, serial=True)
        if target == self.name:
            delay = 0
        else:
            idx = self.order.index(self.name) if self.name in self.order else len(self.order)
            delay = 0.6 * idx + (3 if target else 0)
        if time.time() - self.vacancy_since < delay:
            return
        lease = self.etcd.grant(LEADER_TTL)
        won, _ = self.etcd.create(K_LIDER, self.name, lease)
        if not won:
            self.etcd.revoke(lease)
            return
        self.is_leader, self.leader_lease, self.vacancy_since = True, lease, None
        if target == self.name:
            self.etcd.delete(K_CEDER)
        event(self.etcd, self.name, "lider", f"{self.name} es el nuevo líder del clúster")
        self.leader_thread = threading.Thread(target=self._leader_loop, daemon=True)
        self.leader_thread.start()

    # ================================================================ líder
    def _leader_loop(self):
        while self.is_leader and not self.stop.is_set():
            try:
                job = self.etcd.get(K_TRABAJO)
                if isinstance(job, dict) and job.get("estado") == "running":
                    JobRunner(self, job).run()
                    continue
                cmds = self.etcd.get_prefix(K_CMD)
                for key in sorted(cmds):
                    cmd = cmds[key]
                    self.etcd.delete(key)
                    if isinstance(cmd, dict) and cmd.get("tipo") == "analizar":
                        job = {"id": time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4],
                               "estado": "running", "params": cmd.get("params", {}), "creado": now(),
                               "lideres": [], "progreso": {"fase": "en cola"}}
                        self.etcd.put(K_TRABAJO, job)
                        event(self.etcd, self.name, "trabajo", f"nuevo trabajo {job['id']}")
                        break
                    if isinstance(cmd, dict) and cmd.get("tipo") == "medir_red":
                        self.etcd.put(K_MEDIR, str(now()))
            except EtcdError:
                pass
            except Exception as exc:  # noqa: BLE001
                print(f"[{self.name}] líder: {exc}", flush=True)
                event(self.etcd, self.name, "error", f"error del líder: {exc}")
            time.sleep(0.5)


# =============================================================================
# Ejecución de un trabajo (solo el líder)
# =============================================================================
class LostLeadership(Exception):
    pass


class JobRunner:
    def __init__(self, coord: Coordinator, job: dict):
        self.c, self.etcd, self.job = coord, coord.etcd, job
        self.p = job.get("params", {})
        self.jid = job["id"]
        self.lock = threading.Lock()
        self.inflight: dict[int, str] = {}
        self.errors: dict[str, int] = {}
        self.failed: set[str] = set()
        self.stop = threading.Event()

    # ------------------------------------------------------------------
    def save(self, **fields):
        self.job.update(fields)
        if not self.c.is_leader:
            raise LostLeadership()
        self.etcd.put(K_TRABAJO, self.job)

    def run(self):
        try:
            self._run()
        except LostLeadership:
            pass                              # el nuevo líder lo retomará
        except Exception as exc:  # noqa: BLE001
            try:
                self.save(estado="error", error=str(exc), fin=now())
                event(self.etcd, self.c.name, "error", f"trabajo {self.jid}: {exc}")
            except (LostLeadership, EtcdError):
                pass

    def _plan(self):
        mode = self.p.get("modo", "contar")
        files = self.p.get("archivos") or []
        if not files:
            raise ValueError("no se eligió ningún archivo")
        pats = W.parse_patterns(self.p.get("patrones", []))
        overlap = max((len(x) for x in pats), default=1) - 1
        chunk = int(self.p.get("chunk_mb", 96)) * M.MB
        metas = []
        for name in files:
            fp = W.data_path(name)            # el líder debe tener una copia
            metas.append(seqcache.seq_cache(fp, log=lambda *_: None))
        frags = []
        if mode == "comparar":
            size = min(metas[0]["seq_size"], metas[1]["seq_size"])
            frags = [(0, off, n, 0) for off, n, _ in M.plan_pieces(size, chunk, 0)]
        else:
            for fi, meta in enumerate(metas):
                frags += [(fi, off, n, ov) for off, n, ov in M.plan_pieces(meta["seq_size"], chunk, overlap)]
        return mode, files, metas, pats, frags

    def _participants(self, metas, files) -> dict[str, dict]:
        alive = self.c._alive_nodes()
        wanted = set(self.p.get("nodos") or alive)
        pais = (self.p.get("solo_pais") or "").lower()
        out = {}
        for name, info in alive.items():
            if name not in wanted or info.get("estado") != "viva" or name in self.failed:
                continue
            if pais and str(info.get("pais", "")).lower() != pais:
                continue
            if self.p.get("lider_solo_reparte") and name == self.c.name:
                continue
            have = {f["nombre"]: f for f in info.get("archivos", []) if f.get("listo")}
            ref = all(files[i] in have and have[files[i]].get("seq_sha256") == m.get("seq_sha256")
                      for i, m in enumerate(metas))
            out[name] = {"info": info, "modo": "referencia" if ref else "envio",
                         "cli": M.RemoteNode(name, info["url"], self.c.token, timeout=600)}
        return out

    def _run(self):
        self.job.setdefault("lideres", [])
        if not self.job["lideres"] or self.job["lideres"][-1] != self.c.name:
            self.job["lideres"].append(self.c.name)
            if len(self.job["lideres"]) > 1:
                event(self.etcd, self.c.name, "lider", f"{self.c.name} retoma el trabajo {self.jid} desde donde quedó")
        self.save(progreso={**self.job.get("progreso", {}), "fase": "preparando"})
        mode, files, metas, pats, frags = self._plan()
        done = {int(k.rsplit("/", 1)[1]): v for k, v in self.etcd.get_prefix(f"{K_FRAG}{self.jid}/").items()}
        t_start = self.job.get("inicio_reparto") or now()
        self.save(inicio_reparto=t_start, fragmentos_total=len(frags),
                  bytes_total=sum(n for _, _, n, _ in frags), archivos_info=[
                      {"nombre": m["file"], "seq_size": m["seq_size"], "registros": m["records"],
                       "src_sha256": m["src_sha256"]} for m in metas],
                  progreso={"fase": "repartiendo", "hechos": len(done)})
        todo: queue.Queue = queue.Queue()
        for i in range(len(frags)):
            if i not in done:
                todo.put(i)

        participants = self._participants(metas, files)
        if not participants:
            raise RuntimeError("no hay nubes disponibles para calcular")
        self.save(participantes={k: v["modo"] for k, v in participants.items()})
        seq_files = [open(m["seq_path"], "rb") for m in metas]

        def compute(name, part, i):
            fi, off, n, ov = frags[i]
            body = {"archivo": files[fi], "seq_sha256": metas[fi].get("seq_sha256"), "offset": off,
                    "longitud": n, "solape": ov, "patrones": [x.decode() for x in pats]}
            cli = part["cli"]
            t0 = now()
            if mode == "comparar":
                if part["modo"] == "referencia":
                    res, wall = cli.request("POST", "/compare_ref", json.dumps({
                        "archivo_a": files[0], "archivo_b": files[1], "seq_sha256_a": metas[0].get("seq_sha256"),
                        "seq_sha256_b": metas[1].get("seq_sha256"), "offset": off, "longitud": n}).encode(),
                        {"Content-Type": "application/json"})
                    sent = 0
                else:
                    a = os.pread(seq_files[0].fileno(), n, off)
                    b = os.pread(seq_files[1].fileno(), n, off)
                    res, wall = cli.compare(a, b)
                    sent = len(a) + len(b)
            elif part["modo"] == "referencia":
                res, wall = cli.request("POST", "/count_ref", json.dumps(body).encode(), {"Content-Type": "application/json"})
                sent = 0
            else:
                data = os.pread(seq_files[fi].fileno(), n + ov, off)
                res, wall = cli.request("POST", "/count", data, {
                    "X-Overlap": str(min(ov, len(data) - n)), "X-Pattern": ",".join(x.decode() for x in pats),
                    "Content-Type": "application/octet-stream"})
                sent = len(data)
            keep = ("A", "C", "G", "T", "N", "otros", "total", "registros", "minusculas", "patron", "patrones",
                    "detalle_otros", "comparadas", "iguales", "diferentes")
            return {"i": i, "nodo": name, "t0": t0, "t1": now(), "seg": float(res.get("segundos", 0)),
                    "pared": round(wall, 4), "bytes": n + ov, "bytes_red": sent, "modo": part["modo"],
                    "archivo": files[fi], "res": {k: res[k] for k in keep if k in res}}

        def sender(name, part):
            consecutive = 0
            while not self.stop.is_set():
                if name in self.failed:
                    return
                try:
                    i = todo.get(timeout=0.25)
                except queue.Empty:
                    with self.lock:
                        if len(done) == len(frags):
                            return
                    continue
                with self.lock:
                    self.inflight[i] = name
                try:
                    rec = compute(name, part, i)
                    if not self.c.is_leader:
                        raise LostLeadership()
                    self.etcd.put(f"{K_FRAG}{self.jid}/{i:05d}", rec)
                    with self.lock:
                        done[i] = rec
                        self.inflight.pop(i, None)
                    consecutive = 0
                except LostLeadership:
                    self.stop.set()
                    return
                except Exception as exc:  # noqa: BLE001
                    with self.lock:
                        self.inflight.pop(i, None)
                        self.errors[name] = self.errors.get(name, 0) + 1
                    todo.put(i)
                    consecutive += 1
                    if consecutive >= 3 and name not in self.failed:
                        self.failed.add(name)
                        event(self.etcd, self.c.name, "fallo",
                              f"{name} falló ({str(exc)[:80]}); sus fragmentos se reasignan")
                        return
                    time.sleep(0.5)

        threads = []

        def launch(name, part):
            slots = int(self.p.get("max_hilos") or 0) or int(part["info"].get("cpus") or 1)
            for _ in range(max(1, slots)):
                t = threading.Thread(target=sender, args=(name, part), daemon=True)
                t.start()
                threads.append(t)

        for name, part in participants.items():
            launch(name, part)
        event(self.etcd, self.c.name, "trabajo",
              f"{self.c.name} reparte {len(frags) - len(done)} fragmentos entre {', '.join(participants)}")

        last_pub = 0.0
        try:
            while True:
                with self.lock:
                    finished = len(done) == len(frags)
                if finished:
                    break
                if not self.c.is_leader:
                    raise LostLeadership()
                cancel = self.etcd.get(K_CANCEL, as_json=False)
                if cancel == self.jid:
                    self.stop.set()
                    self.etcd.delete(K_CANCEL)
                    self.save(estado="cancelado", fin=now())
                    event(self.etcd, self.c.name, "trabajo", f"trabajo {self.jid} cancelado")
                    return
                # nubes apagadas o caídas durante el trabajo -> dejan de recibir
                alive = self.c._alive_nodes()
                for name in list(participants):
                    if name not in self.failed and (name not in alive or alive[name].get("estado") != "viva"):
                        self.failed.add(name)
                        event(self.etcd, self.c.name, "fallo", f"{name} dejó de responder; sus fragmentos se reasignan")
                # todas fallaron: el líder calcula (continuidad)
                if all(n in self.failed for n in participants) and not any(t.is_alive() for t in threads):
                    if self.c.name in self.failed or self.c.name not in alive:
                        raise RuntimeError("todas las nubes fallaron")
                    me = {"info": alive[self.c.name], "modo": "referencia",
                          "cli": M.RemoteNode(self.c.name, self.c.url, self.c.token, timeout=600)}
                    participants[self.c.name] = me
                    self.failed.discard(self.c.name)
                    event(self.etcd, self.c.name, "fallo", f"todas las nubes fallaron: {self.c.name} continúa solo")
                    launch(self.c.name, me)
                if time.time() - last_pub > 0.6:
                    last_pub = time.time()
                    with self.lock:
                        prog = {"fase": "repartiendo", "hechos": len(done), "en_curso": dict(self.inflight),
                                "errores": dict(self.errors), "caidos": sorted(self.failed)}
                    self.save(progreso=prog)
                time.sleep(0.15)
        finally:
            self.stop.set()
            for f in seq_files:
                f.close()

        # --------------------------------------------------- resultado final
        t_end = now()
        recs = [done[i] for i in range(len(frags))]
        result = self._merge(mode, recs, metas)
        baseline = None
        if self.p.get("verificar"):
            self.save(progreso={"fase": "verificando", "hechos": len(done)})
            baseline = self._baseline(mode, metas, pats, frags)
        summary = self._summary(recs, t_start, t_end, result, baseline, metas)
        self.etcd.put(K_HIST + self.jid, summary)
        self.save(estado="done", fin=t_end, resultado=summary, progreso={"fase": "terminado", "hechos": len(done)})
        event(self.etcd, self.c.name, "trabajo",
              f"trabajo {self.jid} terminado en {summary['segundos']} s ({summary['gb_s']} GB/s)")

    # ------------------------------------------------------------------
    def _merge(self, mode, recs, metas):
        if mode == "comparar":
            r = {"comparadas": 0, "iguales": 0, "diferentes": 0}
            for x in recs:
                for k in r:
                    r[k] += x["res"].get(k, 0)
            r["sobrantes"] = abs(metas[0]["seq_size"] - metas[1]["seq_size"])
            r["similitud_pct"] = round(r["iguales"] / r["comparadas"] * 100, 6) if r["comparadas"] else 0
            return r
        r = W.merge_counts(x["res"] for x in recs)
        valid = r["A"] + r["C"] + r["G"] + r["T"]
        r["gc_pct"] = round((r["G"] + r["C"]) / valid * 100, 4) if valid else 0
        r["detalle_otros"] = dict(sorted(r["detalle_otros"].items(), key=lambda kv: -kv[1])[:20])
        return r

    def _baseline(self, mode, metas, pats, frags):
        """Verificación: el MISMO cálculo en el líder con 1 núcleo."""
        t0 = time.perf_counter()
        if mode == "comparar":
            res = M.run_baseline("comparar", metas[0], metas[1], b"", 64 * M.MB, log=lambda *_: None)["resultado"]
        else:
            parts = []
            for fi, meta in enumerate(metas):
                with open(meta["seq_path"], "rb") as fh:
                    for f_i, off, n, ov in frags:
                        if f_i == fi:
                            parts.append(W.count_region(os.pread(fh.fileno(), n + ov, off), ov, patterns=pats))
            res = W.merge_counts(parts)
        return {"segundos": round(time.perf_counter() - t0, 3), "resultado": res}

    def _summary(self, recs, t0, t1, result, baseline, metas):
        dur = max(t1 - t0, 1e-6)
        nodes_info = self.c._alive_nodes()
        reg = {k[len(K_REGISTRO):]: v for k, v in self.etcd.get_prefix(K_REGISTRO).items()}
        per: dict[str, dict] = {}
        for x in recs:
            st = per.setdefault(x["nodo"], {"nodo": x["nodo"], "fragmentos": 0, "bytes": 0, "bytes_red": 0,
                                           "seg_calculo": 0.0, "seg_pared": 0.0, "modo": x.get("modo")})
            st["fragmentos"] += 1
            st["bytes"] += x["bytes"]
            st["bytes_red"] += x.get("bytes_red", 0)
            st["seg_calculo"] += x["seg"]
            st["seg_pared"] += x.get("pared", 0)
        total_bytes = sum(s["bytes"] for s in per.values()) or 1
        names = set(per) | set(self.job.get("participantes", {}))
        for name in names:
            info = nodes_info.get(name) or reg.get(name) or {}
            st = per.setdefault(name, {"nodo": name, "fragmentos": 0, "bytes": 0, "bytes_red": 0,
                                       "seg_calculo": 0.0, "seg_pared": 0.0})
            ch = node_cost_hour(info)
            st.update(pais=info.get("pais"), provider=info.get("provider"), region=info.get("region"),
                      instancia=info.get("instancia"), cpus=info.get("cpus"), cobro=info.get("cobro"),
                      costo_hora=round(ch, 6), costo_mes=round(ch * 730, 2),
                      costo_analisis=round(ch * dur / 3600, 8),
                      gb=round(st["bytes"] / 1e9, 4), pct_trabajo=round(st["bytes"] / total_bytes * 100, 2),
                      gb_s=round(st["bytes"] / 1e9 / st["seg_pared"], 3) if st["seg_pared"] else None,
                      seg_calculo=round(st["seg_calculo"], 3), seg_pared=round(st["seg_pared"], 3),
                      errores=self.errors.get(name, 0), fallo=name in self.failed)
        cost = sum(s["costo_analisis"] for s in per.values())
        for s in per.values():
            s["usd_por_gb"] = round(s["costo_analisis"] / s["gb"], 8) if s["gb"] else None
            s["pct_costo"] = round(s["costo_analisis"] / cost * 100, 2) if cost else 0
        out = {"id": self.jid, "modo": self.p.get("modo", "contar"), "archivos": [m["file"] for m in metas],
               "patrones": self.p.get("patrones", []), "chunk_mb": self.p.get("chunk_mb"),
               "fragmentos": len(recs), "bytes": sum(m["seq_size"] for m in metas),
               "caracteres": sum(m["seq_size"] - m["records"] for m in metas),
               "inicio": t0, "fin": t1, "segundos": round(dur, 3),
               "gb_s": round(total_bytes / 1e9 / dur, 3), "lideres": self.job.get("lideres", []),
               "nodos": sorted(per.values(), key=lambda s: -s["bytes"]), "resultado": result,
               "costo_total": round(cost, 8), "costo_por_1000": round(cost * 1000, 6)}
        if baseline:
            keys = ("comparadas", "iguales", "diferentes") if out["modo"] == "comparar" else \
                ("A", "C", "G", "T", "N", "otros", "total", "registros", "minusculas")
            same = all(result.get(k) == baseline["resultado"].get(k) for k in keys)
            if out["modo"] != "comparar":
                same = same and result.get("patrones") == baseline["resultado"].get("patrones")
            out.update(identico=same, seg_1_nucleo=baseline["segundos"],
                       speedup=round(baseline["segundos"] / dur, 2))
        return out


# =============================================================================
# Arranque del nodo completo (APP_MODE=nodo)
# =============================================================================
def run_node() -> int:
    """worker (8000) + coordinador + dashboard (8080) en un solo contenedor."""
    import sys
    name = os.getenv("NODE_NAME", "")
    token = os.getenv("CLUSTER_TOKEN", "")
    endpoints = os.getenv("ETCD_ENDPOINTS", "http://127.0.0.1:2379")
    if not name or not token:
        print("ERROR: defina NODE_NAME y CLUSTER_TOKEN", file=sys.stderr)
        return 1
    W.start_pool()                         # antes de cualquier hilo
    W.start_background()
    etcd = Etcd(endpoints)
    worker_port = int(os.getenv("WORKER_PORT", "8000"))
    private_url = os.getenv("PRIVATE_URL") or f"http://{os.getenv('PRIVATE_IP', '127.0.0.1')}:{worker_port}"
    order = [x.strip() for x in os.getenv("ORDEN", "usa,europa,china,latam,ecuador").split(",") if x.strip()]
    coord = Coordinator(etcd, name, private_url, token, order)

    import cluster_api
    import server
    cluster_api.init(etcd, coord)
    dash = server.make_server(int(os.getenv("PORT", "8080")), os.getenv("DASH_BIND", "127.0.0.1"))
    threading.Thread(target=dash.serve_forever, daemon=True).start()
    coord.start()
    srv = W.ThreadingHTTPServer((os.getenv("WORKER_BIND", "0.0.0.0"), worker_port), W.Handler)
    srv.daemon_threads = True
    print(f"Nodo '{name}': worker :{worker_port} | dashboard {os.getenv('DASH_BIND', '127.0.0.1')}:"
          f"{os.getenv('PORT', '8080')} | etcd {endpoints} | {private_url}", flush=True)
    srv.serve_forever()
    return 0
