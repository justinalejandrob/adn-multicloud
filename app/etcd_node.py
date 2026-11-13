"""
etcd_node.py - Arranca un miembro de etcd con la MISMA imagen (APP_MODE=etcd).

Variables (no usan el prefijo ETCD_ porque etcd lee esas variables por su cuenta):
  NODE_NAME      nombre del miembro (usa, europa, china, latam, ecuador)
  PRIVATE_IP     IP de WireGuard de esta nube (10.99.0.x)
  CLUSTER_PEERS     usa=http://10.99.0.1:2380,europa=http://10.99.0.2:2380,...
  CLUSTER_STATE     new (primera vez) | existing (al re-unirse un miembro)
  CLUSTER_ETCD_DATA      carpeta de datos (por defecto /etcd-data)

etcd replica su información con Raft entre las 5 nubes: tolera la caída de
2 miembros (necesita mayoría: 3 de 5). Se comunica solo por la red privada
WireGuard; el puerto de clientes (2379) escucha en la IP privada y en localhost.
"""

import os
import shutil
import sys


def main() -> int:
    name, ip = os.getenv("NODE_NAME", ""), os.getenv("PRIVATE_IP", "")
    peers = os.getenv("CLUSTER_PEERS", "")
    if not name or not ip or not peers:
        print("ERROR: defina NODE_NAME, PRIVATE_IP y CLUSTER_PEERS", file=sys.stderr)
        return 1
    binary = shutil.which("etcd") or "/usr/local/bin/etcd"
    args = [
        binary, "--name", name,
        "--data-dir", os.getenv("CLUSTER_ETCD_DATA", "/etcd-data"),
        "--listen-peer-urls", f"http://{ip}:2380",
        "--initial-advertise-peer-urls", f"http://{ip}:2380",
        "--listen-client-urls", f"http://{ip}:2379,http://127.0.0.1:2379",
        "--advertise-client-urls", f"http://{ip}:2379",
        "--initial-cluster", peers,
        "--initial-cluster-state", os.getenv("CLUSTER_STATE", "new"),
        "--initial-cluster-token", "adn-multinube",
        # tolerante a enlaces intercontinentales (RTT de 100-300 ms)
        "--heartbeat-interval", os.getenv("CLUSTER_HEARTBEAT_MS", "250"),
        "--election-timeout", os.getenv("CLUSTER_ELECTION_MS", "2500"),
        "--quota-backend-bytes", str(512 * 1024 * 1024),
        "--auto-compaction-retention", "1",
    ]
    print("etcd:", " ".join(args[1:]), flush=True)
    os.execv(binary, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
