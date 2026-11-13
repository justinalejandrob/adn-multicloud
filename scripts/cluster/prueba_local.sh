#!/usr/bin/env bash
# =============================================================================
# prueba_local.sh - Prueba completa del clúster con etcd EN UNA SOLA MÁQUINA.
#
# Levanta 3 miembros de etcd + 3 nodos (usa, europa, china) en localhost,
# lanza un análisis con 2 patrones, MATA AL LÍDER a mitad del trabajo y comprueba:
#   - que otra nube tomó el mando y retomó el trabajo,
#   - que el resultado es idéntico al cálculo con 1 núcleo.
# Sirve para el CI (GitHub Actions) y para demostrarlo en Linux o WSL.
#
#   bash scripts/cluster/prueba_local.sh          (necesita python3, numpy y curl)
# =============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/app"; W="${PRUEBA_DIR:-$ROOT/.prueba}"; ETCD_VER=v3.5.17
rm -rf "$W"; mkdir -p "$W"; PIDS=()
fin() { for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null; pkill -9 -P "$p" 2>/dev/null; done; }
trap fin EXIT

ETCD="$(command -v etcd || true)"
if [ -z "$ETCD" ]; then
  ETCD="$ROOT/.cache/etcd-$ETCD_VER/etcd"
  if [ ! -x "$ETCD" ]; then
    echo "Descargando etcd $ETCD_VER…"; mkdir -p "$ROOT/.cache"
    curl -fsSL "https://github.com/etcd-io/etcd/releases/download/$ETCD_VER/etcd-$ETCD_VER-linux-amd64.tar.gz" | tar xz -C "$ROOT/.cache"
    mv "$ROOT/.cache/etcd-$ETCD_VER-linux-amd64" "$ROOT/.cache/etcd-$ETCD_VER"
  fi
fi

echo "== Datos de prueba (dos FASTA sintéticos) =="
python3 "$APP/generate_dna.py" --size 24MB --seed 7 -o "$W/base/a.fna" >/dev/null
python3 "$APP/generate_dna.py" --size 16MB --seed 8 -o "$W/base/b.fna" >/dev/null
rm -f "$W"/base/*.sha256

N=(usa europa china); PEERS=""; ENDS=""
for i in 0 1 2; do PEERS+="${PEERS:+,}${N[$i]}=http://127.0.0.1:$((22380 + i * 10))"; ENDS+="${ENDS:+,}http://127.0.0.1:$((22379 + i * 10))"; done
echo "== 3 miembros de etcd =="
for i in 0 1 2; do
  "$ETCD" --name "${N[$i]}" --data-dir "$W/etcd-${N[$i]}" --initial-cluster-token prueba \
    --listen-peer-urls "http://127.0.0.1:$((22380 + i * 10))" --initial-advertise-peer-urls "http://127.0.0.1:$((22380 + i * 10))" \
    --listen-client-urls "http://127.0.0.1:$((22379 + i * 10))" --advertise-client-urls "http://127.0.0.1:$((22379 + i * 10))" \
    --initial-cluster "$PEERS" > "$W/etcd-${N[$i]}.log" 2>&1 & PIDS+=($!); disown
done
sleep 3
echo "== 3 nodos (worker + coordinador + dashboard) =="
for i in 0 1 2; do
  n=${N[$i]}; mkdir -p "$W/datos-$n"; cp "$W"/base/*.fna "$W/datos-$n/"
  ( cd "$APP" && APP_MODE=nodo NODE_NAME=$n CLUSTER_TOKEN=prueba WORKER_PORT=$((18101 + i)) PORT=$((18201 + i)) \
    PRIVATE_URL=http://127.0.0.1:$((18101 + i)) ETCD_ENDPOINTS="http://127.0.0.1:$((22379 + i * 10)),$ENDS" ORDEN=usa,europa,china \
    DATA_DIR="$W/datos-$n" OUTPUT_DIR="$W/res-$n" DNA_FILE="$W/d-$n/adn.txt" CLOUD_PROVIDER=local CLOUD_ORIGIN=Prueba COST_HOUR=0.05 \
    exec python3 main.py > "$W/nodo-$n.log" 2>&1 ) & PIDS+=($!); disown
done

python3 - "$W" <<'EOF'
import json, os, signal, sys, time, urllib.request
W = sys.argv[1]
def est(port):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cluster/estado", timeout=10).read())
def post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())
t0 = time.time()
while True:                                   # esperar líder y datos listos en las 3 nubes
    try:
        d = est(18203)
        ready = [n for n in d["nodos"] if all(f.get("listo") for f in n.get("archivos", [])) and len(n.get("archivos", [])) == 2]
        if d.get("lider") and len(ready) == 3: break
    except Exception: pass
    if time.time() - t0 > 90: sys.exit("ERROR: el clúster no arrancó (revise .prueba/*.log)")
    time.sleep(1)
print(f"líder inicial: {d['lider']} · líder de etcd: {d['etcd_lider']}")
print(post(18203, "/api/cluster/ejecutar", {"archivos": ["a.fna", "b.fna"], "patrones": ["TATAAA", "GAATTC"], "chunk_mb": 1, "verificar": True})["mensaje"])
while True:
    d = est(18203); j = d.get("trabajo") or {}
    if j.get("estado") == "running" and len(d["fragmentos"]) >= 8: break
    time.sleep(0.05)
lider = d["lider"]
for pid in os.listdir("/proc"):              # caída REAL del proceso del líder
    try:
        env = open(f"/proc/{pid}/environ", "rb").read()
    except Exception: continue
    if b"APP_MODE=nodo" in env and f"NODE_NAME={lider}\0".encode() in env:
        os.kill(int(pid), signal.SIGKILL)
print(f"→ proceso del líder {lider} terminado con {len(d['fragmentos'])}/{j['fragmentos_total']} fragmentos hechos")
port = 18203 if lider != "china" else 18202
t1 = time.time()
while True:
    d = est(port); j = d.get("trabajo") or {}
    if j.get("estado") not in ("running", None): break
    if time.time() - t1 > 120: sys.exit("ERROR: el trabajo no terminó")
    time.sleep(0.5)
s = j.get("resultado") or {}
print(f"nuevo líder: {d['lider']} · líderes del trabajo: {' → '.join(s.get('lideres', []))} · recuperación {time.time() - t1:.1f} s")
print(f"patrones: {s.get('resultado', {}).get('patrones')} · idéntico a 1 núcleo: {s.get('identico')}")
ok = j.get("estado") == "done" and s.get("identico") is True and len(s.get("lideres", [])) >= 2
print("PRUEBA SUPERADA ✓" if ok else "PRUEBA FALLIDA ✗")
sys.exit(0 if ok else 1)
EOF
