#!/usr/bin/env bash
# =============================================================================
# migrar_imagen.sh - MIGRACIÓN EN VIVO de la imagen a una nube, sin registro:
#
#   docker save IMAGEN | gzip | ssh nube "gunzip | sudo docker load"
#
# No se reescribe ni recompila nada: es el mismo artefacto en todas las nubes.
# Uso (en la PC):
#   docker build -t adn-multicloud:latest .
#   bash scripts/cluster/migrar_imagen.sh europa [IMAGEN]
# Mide el tiempo y lo registra en results/migraciones.csv.
# (desplegar_cluster.sh --migrar la usa y luego levanta los contenedores)
# =============================================================================
set -euo pipefail
source "$(dirname "$0")/_nubes.sh"
NODE="${1:?Uso: migrar_imagen.sh NUBE [IMAGEN]}"
IMAGE="${2:-adn-multicloud:latest}"
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "No existe $IMAGE en esta PC: docker build -t $IMAGE ."; exit 1; }
SIZE=$(docker image inspect "$IMAGE" --format '{{.Size}}')
echo "[migrar → $NODE] $IMAGE ($((SIZE / 1024 / 1024)) MB sin comprimir)"
en "$NODE" "command -v docker >/dev/null" </dev/null || {
  copiar "$NODE" "~/" "$ROOT/scripts/bootstrap_vm.sh"; en "$NODE" "bash ~/bootstrap_vm.sh" </dev/null; }
T0=$(date +%s)
docker save "$IMAGE" | gzip -1 | en "$NODE" "gunzip | sudo docker load"
T1=$(date +%s)
echo "[migrar → $NODE] transferida y cargada en $((T1 - T0)) s"
mkdir -p "$ROOT/results"
[ -f "$ROOT/results/migraciones.csv" ] || echo "fecha_utc,nube,imagen,mb_imagen,segundos" > "$ROOT/results/migraciones.csv"
echo "$(date -u +%FT%TZ),$NODE,$IMAGE,$((SIZE / 1024 / 1024)),$((T1 - T0))" >> "$ROOT/results/migraciones.csv"
