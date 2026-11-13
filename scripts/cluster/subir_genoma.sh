#!/usr/bin/env bash
# =============================================================================
# subir_genoma.sh - Sube el FASTA del profesor desde su PC a UNA nube y le pide
# al clúster que lo copie a las demás por WireGuard.
#
#   bash scripts/cluster/subir_genoma.sh ~/Descargas/GCA_000001405.29_GRCh38.p14_genomic.fna
#   bash scripts/cluster/subir_genoma.sh archivo.fna usa              # a una nube concreta
#   bash scripts/cluster/subir_genoma.sh archivo.fna usa --sin-replicar
#
# - Usa rsync --partial si está instalado: si se corta el internet, vuelva a
#   ejecutar el mismo comando y continúa donde quedó. Si no hay rsync
#   (Git Bash en Windows), usa scp.
# - El archivo se sube UNA sola vez desde su casa; las otras 4 nubes lo copian
#   entre ellas por la red privada (mucho más rápida que su internet).
# =============================================================================
set -euo pipefail
source "$(dirname "$0")/_nubes.sh"

FILE="${1:-}"; NUBE="${2:-$(nubes | head -1 | cut -d'|' -f1)}"; MODE="${3:-}"
[ -f "$FILE" ] || { echo "Uso: $0 ARCHIVO.fna [nube] [--sin-replicar]"; exit 1; }
NAME="$(basename "$FILE" | tr ' ' '_' | tr -cd 'A-Za-z0-9._-')"
[[ "$NAME" =~ \.(fna|fa|fasta|fas|txt)$ ]] || { echo "Extensión no válida: $NAME (.fna .fa .fasta .fas .txt)"; exit 1; }
[ -n "$(campo "$NUBE" 2)" ] || { echo "La nube '$NUBE' no está en $CONF"; exit 1; }
SIZE=$(wc -c <"$FILE" | tr -d ' ')
echo "Subiendo $NAME ($((SIZE / 1024 / 1024)) MB) a $NUBE ($(campo "$NUBE" 2))…"

# espacio libre en la nube: archivo + caché .seq ≈ 2.1 × tamaño
FREE=$(en "$NUBE" "df -Pk ~/cluster-adn | awk 'NR==2{print \$4*1024}'" </dev/null)
NEED=$((SIZE * 21 / 10))
[ "$FREE" -ge "$NEED" ] || { echo "ERROR: $NUBE tiene $((FREE/1024/1024/1024)) GB libres y se necesitan ≈ $((NEED/1024/1024/1024)) GB"; exit 1; }

en "$NUBE" "mkdir -p ~/cluster-adn/subida" </dev/null
T0=$(date +%s)
if command -v rsync >/dev/null; then
  rsync --partial --progress -e "ssh -p $(campo "$NUBE" 3) -o StrictHostKeyChecking=accept-new" \
        "$FILE" "$(campo "$NUBE" 2):~/cluster-adn/subida/$NAME"
else
  echo "(rsync no está instalado: se usa scp; si se corta, empieza de nuevo)"
  scp -P "$(campo "$NUBE" 3)" -o StrictHostKeyChecking=accept-new "$FILE" "$(campo "$NUBE" 2):~/cluster-adn/subida/$NAME"
fi
SECS=$(( $(date +%s) - T0 )); [ "$SECS" -gt 0 ] || SECS=1
echo "Subida: $SECS s ($((SIZE / 1024 / 1024 / SECS)) MB/s)"

# mover a la carpeta de datos del nodo (dueño uid 1000, el usuario del contenedor)
en "$NUBE" "S=\$( [ \$(id -u) -eq 0 ] || echo sudo ); \$S mv ~/cluster-adn/subida/$NAME ~/cluster-adn/datos/$NAME && \$S chown 1000:1000 ~/cluster-adn/datos/$NAME" </dev/null
echo "✓ $NAME está en $NUBE. El nodo lo prepara solo (limpieza + SHA-256, 1–3 min para 3 GB)."
echo "$(date -Iseconds),$NUBE,$NAME,$SIZE,$SECS" >> "$ROOT/cluster/subidas.csv"

[ "$MODE" = "--sin-replicar" ] && { echo "Replique después desde la pestaña Datos (opción ③)."; exit 0; }

echo "Esperando a que $NUBE termine de preparar el archivo…"
for _ in $(seq 1 120); do
  R=$(en "$NUBE" "curl -s -X POST -H 'Content-Type: application/json' \
        -d '{\"origen\":\"$NUBE\",\"archivo\":\"$NAME\"}' http://127.0.0.1:8080/api/cluster/descargar" </dev/null || true)
  if echo "$R" | grep -q '"mensaje"'; then
    echo "✓ $(echo "$R" | sed -E 's/.*"mensaje": *"([^"]*)".*/\1/')"
    echo "  Vea el avance en http://localhost:8080/#cluster → pestaña «Datos en las nubes»."
    exit 0
  fi
  sleep 5
done
echo "La nube no terminó de preparar a tiempo. Replique desde la pestaña Datos (opción ③)."
