#!/usr/bin/env bash
# =============================================================================
# conectar.sh - Abre el dashboard del clúster en la PC por un túnel SSH.
#
#   bash scripts/cluster/conectar.sh          # prueba las nubes en orden
#   bash scripts/cluster/conectar.sh europa   # por una nube concreta
#
# Reenvía 8080 (dashboard) y 2379 (etcd) de la nube a su PC. Luego abra:
#   http://localhost:8080/#cluster
# El dashboard no está abierto a internet: solo se llega con su llave SSH.
# Si esa nube se cae, vuelva a ejecutar este script: se conecta por otra.
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/_nubes.sh"
CAND=("$@"); [ ${#CAND[@]} -eq 0 ] && mapfile -t CAND < <(nubes | cut -d'|' -f1)
for n in "${CAND[@]}"; do
  echo "Conectando vía $n ($(campo "$n" 2))…"
  echo "  → abra http://localhost:8080/#cluster   (Ctrl+C para cerrar el túnel)"
  ssh -N -p "$(campo "$n" 3)" -o ExitOnForwardFailure=yes -o ConnectTimeout=8 -o ServerAliveInterval=15 \
      -L 8080:127.0.0.1:8080 -L 2379:127.0.0.1:2379 "$(campo "$n" 2)" && exit 0
  echo "  $n no respondió; probando la siguiente nube…"
done
echo "No se pudo conectar a ninguna nube."; exit 1
