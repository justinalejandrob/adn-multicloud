"""
etcd_client.py - Cliente mínimo de etcd v3 (API JSON/HTTP), sin dependencias.

etcd es la "memoria compartida" del clúster: un almacén clave-valor
replicado con Raft en las 5 nubes. Si se cae una minoría de nubes (hasta 2 de 5),
sigue funcionando. Se usa para:
  - elegir al líder (clave con "lease": si el líder muere, la clave expira),
  - publicar el latido y los recursos de cada nube,
  - guardar el estado del trabajo (qué fragmentos ya están hechos),
    para que un nuevo líder pueda continuarlo,
  - la cola de comandos del dashboard y el registro de eventos.

Si un miembro no responde, el cliente prueba con el siguiente (failover).
"""

from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request


def _b64(s) -> str:
    return base64.b64encode(s.encode() if isinstance(s, str) else s).decode()


def _unb64(s: str) -> str:
    return base64.b64decode(s).decode()


def prefix_end(prefix: str) -> str:
    """Fin de rango para "todas las claves que empiezan con prefix"."""
    b = bytearray(prefix.encode())
    b[-1] += 1
    return base64.b64encode(bytes(b)).decode()


class EtcdError(RuntimeError):
    pass


class Etcd:
    def __init__(self, endpoints, timeout: float = 4.0):
        # serial=True en get/get_prefix: lectura "serializable" del miembro local de etcd,
        # sin ir al líder Raft. Con 100-350 ms entre continentes, una lectura linealizable
        # tarda ~0,5 s; la serializable tarda ~1 ms (puede ir unos ms atrasada).
        if isinstance(endpoints, str):
            endpoints = [e.strip() for e in endpoints.split(",") if e.strip()]
        self.endpoints = [e.rstrip("/") for e in endpoints]
        self.timeout = timeout
        self._pref = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def _call(self, path: str, body: dict, timeout=None) -> dict:
        last = None
        n = len(self.endpoints)
        with self._lock:
            start = self._pref
        for k in range(n):
            i = (start + k) % n
            url = self.endpoints[i] + path
            try:
                req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                    text = r.read().decode()
                data = json.loads(text.splitlines()[0]) if text else {}
                if "error" in data and "result" not in data:
                    raise EtcdError(data.get("message") or data["error"])
                with self._lock:
                    self._pref = i
                return data.get("result", data) if path == "/v3/lease/keepalive" else data
            except (urllib.error.URLError, OSError, ValueError, EtcdError) as exc:
                last = exc
        raise EtcdError(f"ningún miembro de etcd responde ({last})")

    # ------------------------------------------------------------------ kv
    def put(self, key: str, value, lease: str | None = None) -> None:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        body = {"key": _b64(key), "value": _b64(value)}
        if lease:
            body["lease"] = lease
        self._call("/v3/kv/put", body)

    def get(self, key: str, default=None, as_json=True, serial=False):
        body = {"key": _b64(key)}
        if serial:
            body["serializable"] = True
        kvs = self._call("/v3/kv/range", body).get("kvs") or []
        if not kvs:
            return default
        v = _unb64(kvs[0].get("value", ""))
        return _loads(v) if as_json else v

    def get_prefix(self, prefix: str, as_json=True, keys_only=False, serial=False) -> dict:
        body = {"key": _b64(prefix), "range_end": prefix_end(prefix)}
        if serial:
            body["serializable"] = True
        if keys_only:
            body["keys_only"] = True
        out = {}
        for kv in self._call("/v3/kv/range", body).get("kvs") or []:
            k = _unb64(kv["key"])
            out[k] = None if keys_only else (_loads(_unb64(kv.get("value", ""))) if as_json else _unb64(kv.get("value", "")))
        return out

    def delete(self, key: str) -> None:
        self._call("/v3/kv/deleterange", {"key": _b64(key)})

    def delete_prefix(self, prefix: str) -> None:
        self._call("/v3/kv/deleterange", {"key": _b64(prefix), "range_end": prefix_end(prefix)})

    def create(self, key: str, value: str, lease: str | None = None) -> tuple[bool, str | None]:
        """Escribe la clave SOLO si no existe (transacción atómica).
        Devuelve (ganó, valor_actual). Base de la elección de líder."""
        put = {"key": _b64(key), "value": _b64(value)}
        if lease:
            put["lease"] = lease
        r = self._call("/v3/kv/txn", {
            "compare": [{"key": _b64(key), "target": "CREATE", "result": "EQUAL", "create_revision": "0"}],
            "success": [{"request_put": put}],
            "failure": [{"request_range": {"key": _b64(key)}}]})
        if r.get("succeeded"):
            return True, value
        kvs = (r.get("responses") or [{}])[0].get("response_range", {}).get("kvs") or []
        return False, _unb64(kvs[0]["value"]) if kvs else None

    def delete_if(self, key: str, value: str) -> bool:
        """Borra la clave solo si todavía vale `value` (renunciar al liderazgo)."""
        r = self._call("/v3/kv/txn", {
            "compare": [{"key": _b64(key), "target": "VALUE", "result": "EQUAL", "value": _b64(value)}],
            "success": [{"request_delete_range": {"key": _b64(key)}}], "failure": []})
        return bool(r.get("succeeded"))

    # ------------------------------------------------------------------ leases
    def grant(self, ttl: int) -> str:
        return self._call("/v3/lease/grant", {"TTL": ttl})["ID"]

    def keepalive(self, lease: str) -> bool:
        r = self._call("/v3/lease/keepalive", {"ID": lease})
        return int(r.get("TTL", 0) or 0) > 0

    def revoke(self, lease: str) -> None:
        try:
            self._call("/v3/lease/revoke", {"ID": lease})
        except EtcdError:
            pass

    # ------------------------------------------------------------------ cluster
    def members(self) -> list[dict]:
        return self._call("/v3/cluster/member/list", {}).get("members") or []

    def leader_name(self) -> str | None:
        """Nombre del miembro de etcd que es líder de Raft."""
        st = self._call("/v3/maintenance/status", {})
        lid = st.get("leader")
        for m in self.members():
            if m.get("ID") == lid:
                return m.get("name")
        return None


def _loads(v: str):
    try:
        return json.loads(v)
    except ValueError:
        return v
