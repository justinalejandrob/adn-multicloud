#!/usr/bin/env bash
# =============================================================================
# run_paas.sh - Ejecuta el procesamiento en una nube PaaS (ej. GuaraCloud)
# y descarga los resultados, igual que deploy_remote.sh hace con las VMs.
#
# En PaaS no hay SSH: el contenedor corre en modo servidor (APP_MODE=server)
# y se controla por HTTP.
#
# Uso:
#   scripts/run_paas.sh <nombre> <url_publica> [tamaño|límite_MB] [modo]
#     - Con DNA_URL configurada en la nube: 3er parámetro = límite en MB
#       (0 = genoma completo, 500 = primeros 500 MB)
#     - Sin DNA_URL: 3er parámetro = tamaño del ADN sintético (100MB, 4MB...)
# Ejemplos:
#   scripts/run_paas.sh guaracloud https://adn-multinube.guaracloud.com 0 both
#   scripts/run_paas.sh guaracloud https://adn-multinube.guaracloud.com 100MB both
# =============================================================================
set -euo pipefail

if [ $# -lt 2 ]; then sed -n '2,18p' "$0"; exit 1; fi

NAME="$1"; URL="${2%/}"; SIZE="${3:-100MB}"; MODE="${4:-both}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
log() { printf '\n\033[1;34m[%s]\033[0m %s\n' "$NAME" "$*"; }

START=$(date +%s)

log "1/4 Verificando que el servicio esté en línea"
curl -fsS --max-time 30 "$URL/health" && echo

if [[ "$SIZE" =~ ^[0-9]+$ ]]; then QUERY="limit_mb=$SIZE"; else QUERY="size=$SIZE"; fi
log "2/4 Lanzando procesamiento ($QUERY, mode=$MODE)"
curl -fsS "$URL/run?$QUERY&mode=$MODE" && echo

log "3/4 Esperando a que termine..."
while true; do
  sleep 5
  STATUS=$(curl -fsS "$URL/status" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')
  echo "  estado: $STATUS"
  [ "$STATUS" = "running" ] || break
done
[ "$STATUS" = "done" ] || { curl -fsS "$URL/status"; exit 1; }

log "4/4 Descargando resultados"
mkdir -p "$ROOT/results/$NAME"
curl -fsS "$URL/results" -o "$ROOT/results/$NAME/resultado_${NAME}_$(date -u +%Y%m%dT%H%M%SZ).json"

END=$(date +%s)
log "Completo en $((END - START)) s. Resultados en results/$NAME/"
echo "$NAME,$URL,$((END - START))" >> "$ROOT/results/deploy_times.csv"
