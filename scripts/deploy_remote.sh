#!/usr/bin/env bash
# =============================================================================
# deploy_remote.sh - Despliega y ejecuta el contenedor de ADN en UNA nube.
#
# Pasos automáticos:
#   1. Copia docker-compose.yml y un .env con los datos de la nube a la VM.
#   2. Instala Docker si hace falta (bootstrap_vm.sh).
#   3. Descarga (pull) la MISMA imagen publicada en el registro.
#   4. Genera el ADN determinista y lo procesa (docker compose up).
#   5. Trae el JSON de resultados a ./results/<proveedor>/
#
# Uso:
#   scripts/deploy_remote.sh <nombre> <usuario@ip> <llave.pem> <origen> <región> <tipo_vm>
# Ejemplo:
#   scripts/deploy_remote.sh azure azureuser@20.1.2.3 ~/.ssh/azure.pem \
#       "EE.UU." "eastus" "Standard_B2s"
#
# Variables opcionales: IMAGE, DNA_URL, DNA_LIMIT_MB, DNA_SIZE, MODE, WORKERS,
#                       CHUNK_MB, PATTERN, SEED
#   DNA_URL  -> enlace del genoma real (Dropbox del docente o NCBI). Cada nube lo
#               descarga directamente; sin DNA_URL se usa ADN sintético.
# =============================================================================
set -euo pipefail

if [ $# -lt 3 ]; then
  sed -n '2,20p' "$0"; exit 1
fi

NAME="$1"; HOST="$2"; KEY="$3"
ORIGIN="${4:-desconocido}"; REGION="${5:-desconocida}"; INSTANCE="${6:-desconocido}"
IMAGE="${IMAGE:?Defina IMAGE, ej: export IMAGE=ghcr.io/usuario/adn-multicloud:latest}"
DNA_SIZE="${DNA_SIZE:-100MB}"
DNA_URL="${DNA_URL:-}"
DNA_LIMIT_MB="${DNA_LIMIT_MB:-0}"
MODE="${MODE:-both}"
REMOTE_DIR="adn-multicloud"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)

log() { printf '\n\033[1;34m[%s]\033[0m %s\n' "$NAME" "$*"; }

START=$(date +%s)

log "1/5 Copiando archivos de despliegue a $HOST"
ssh "${SSH_OPTS[@]}" "$HOST" "mkdir -p ~/$REMOTE_DIR"
cat > "/tmp/.env.$NAME" <<EOF
IMAGE=$IMAGE
CLOUD_PROVIDER=$NAME
CLOUD_ORIGIN=$ORIGIN
CLOUD_REGION=$REGION
INSTANCE_TYPE=$INSTANCE
DNA_URL='$DNA_URL'
DNA_LIMIT_MB=$DNA_LIMIT_MB
DNA_SIZE=$DNA_SIZE
SEED=${SEED:-2026}
MODE=$MODE
WORKERS=${WORKERS:-0}
CHUNK_MB=${CHUNK_MB:-32}
PATTERN=${PATTERN:-GATTACA}
EOF
scp "${SSH_OPTS[@]}" "$ROOT/docker-compose.yml" "$ROOT/scripts/bootstrap_vm.sh" \
    "$HOST:~/$REMOTE_DIR/"
scp "${SSH_OPTS[@]}" "/tmp/.env.$NAME" "$HOST:~/$REMOTE_DIR/.env"
rm -f "/tmp/.env.$NAME"

log "2/5 Verificando/instalando Docker"
ssh "${SSH_OPTS[@]}" "$HOST" "bash ~/$REMOTE_DIR/bootstrap_vm.sh"

log "3/5 Descargando la imagen $IMAGE"
ssh "${SSH_OPTS[@]}" "$HOST" "cd ~/$REMOTE_DIR && \
  mkdir -p data results && sudo chown -R 1000:1000 data results && \
  sudo docker compose pull --quiet"

if [ -n "$DNA_URL" ]; then
  log "4/5 Descargando el genoma real en la nube y procesando (modo $MODE)"
  ssh "${SSH_OPTS[@]}" "$HOST" "df -h ~ | tail -1 | awk '{print \"  disco libre: \" \$4}'"
else
  log "4/5 Generando ADN sintético ($DNA_SIZE) y procesando (modo $MODE)"
fi
ssh "${SSH_OPTS[@]}" "$HOST" "cd ~/$REMOTE_DIR && \
  sudo docker compose run --rm prepare && \
  sudo docker compose run --rm --no-deps processor"

log "5/5 Descargando resultados"
mkdir -p "$ROOT/results/$NAME"
scp "${SSH_OPTS[@]}" "$HOST:~/$REMOTE_DIR/results/*.json" "$ROOT/results/$NAME/"
for f in adn.txt.sha256 adn.txt.download_seconds; do
  scp "${SSH_OPTS[@]}" "$HOST:~/$REMOTE_DIR/data/$f" "$ROOT/results/$NAME/" 2>/dev/null || true
done

END=$(date +%s)
log "Despliegue completo en $((END - START)) s. Resultados en results/$NAME/"
echo "$NAME,$HOST,$((END - START))" >> "$ROOT/results/deploy_times.csv"
