#!/usr/bin/env bash
# =============================================================================
# instalar_nodo.sh - Levanta los 2 contenedores de ESTA nube (misma imagen):
#   adn-etcd  (APP_MODE=etcd) : miembro de etcd, escucha en la IP de WireGuard
#   adn-nodo  (APP_MODE=nodo) : worker :8000 + coordinador (elección de líder)
#                               + dashboard en 127.0.0.1:8080
#
# Uso (dentro de la nube, en ~/cluster-adn; lo llama desplegar_cluster.sh):
#   bash instalar_nodo.sh NOMBRE 'CLAVE'
# Lee ~/cluster-adn/nodo.env (IPs, proveedor, costos, miembros de etcd).
# Ambos usan --network host: ven la interfaz wg0 (10.99.0.x) directamente.
# =============================================================================
set -euo pipefail
NAME="${1:?Uso: bash instalar_nodo.sh NOMBRE 'CLAVE'}"
TOKEN="${2:?Falta la CLAVE del clúster}"
DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${IMAGE:-ghcr.io/TU_USUARIO/adn-multicloud:latest}"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
log() { printf '\033[1;34m[%s]\033[0m %s\n' "$NAME" "$*"; }
[ -f "$DIR/nodo.env" ] || { echo "Falta $DIR/nodo.env"; exit 1; }
getv() { grep -E "^$1=" "$DIR/nodo.env" | head -1 | cut -d= -f2-; }   # (los valores pueden tener espacios)
PRIVATE_IP="$(getv PRIVATE_IP)"; CLUSTER_PEERS="$(getv CLUSTER_PEERS)"; CLUSTER_STATE="$(getv CLUSTER_STATE)"

command -v docker >/dev/null 2>&1 || { log "Instalando Docker..."; bash "$DIR/bootstrap_vm.sh"; }
ip -4 addr show wg0 2>/dev/null | grep -q "$PRIVATE_IP" || { log "ERROR: wg0 no tiene $PRIVATE_IP. Ejecute antes wireguard_malla.sh"; exit 1; }

if $SUDO docker image inspect "$IMAGE" >/dev/null 2>&1; then
  log "Imagen local: $IMAGE"
elif $SUDO docker image inspect adn-multicloud:latest >/dev/null 2>&1; then
  IMAGE=adn-multicloud:latest; log "Imagen local (migrada): $IMAGE"
else
  log "docker pull $IMAGE"; $SUDO docker pull "$IMAGE"
fi

mkdir -p "$DIR/datos" "$DIR/results"
$SUDO chown -R 1000:1000 "$DIR/datos" "$DIR/results"

# --- etcd: solo se crea si no existe (sus datos viven en el volumen adn-etcd) ---
if ! $SUDO docker ps -a --format '{{.Names}}' | grep -qx adn-etcd; then
  log "docker run adn-etcd (miembro $NAME de etcd en $PRIVATE_IP:2379)"
  $SUDO docker run -d --name adn-etcd --restart unless-stopped --network host \
    -v adn-etcd:/etcd-data \
    -e APP_MODE=etcd -e NODE_NAME="$NAME" -e PRIVATE_IP="$PRIVATE_IP" \
    -e CLUSTER_PEERS="$CLUSTER_PEERS" -e CLUSTER_STATE="${CLUSTER_STATE:-new}" \
    "$IMAGE" >/dev/null
else
  $SUDO docker start adn-etcd >/dev/null 2>&1 || true
  log "adn-etcd ya existe (se conserva su estado)"
fi

# --- nodo: se reemplaza siempre (actualizar = volver a ejecutar este script) ---
$SUDO docker rm -f adn-nodo >/dev/null 2>&1 || true
log "docker run adn-nodo (worker en $PRIVATE_IP:8000, dashboard en 127.0.0.1:8080)"
$SUDO docker run -d --name adn-nodo --restart unless-stopped --network host \
  -v "$DIR/datos:/datos" -v "$DIR/results:/results" \
  --env-file "$DIR/nodo.env" \
  -e APP_MODE=nodo -e NODE_NAME="$NAME" -e CLUSTER_TOKEN="$TOKEN" \
  -e PRIVATE_URL="http://$PRIVATE_IP:8000" -e WORKER_BIND="$PRIVATE_IP" \
  -e DASH_BIND=127.0.0.1 -e PORT=8080 \
  "$IMAGE" >/dev/null

sleep 4
if curl -fsS "http://$PRIVATE_IP:8000/health" >/dev/null; then
  log "Nodo en línea. Estado de etcd:"
  $SUDO docker exec adn-etcd etcdctl --endpoints="http://127.0.0.1:2379" endpoint status -w table 2>/dev/null || true
else
  log "El nodo no respondió. Revise: sudo docker logs adn-nodo"; exit 1
fi
