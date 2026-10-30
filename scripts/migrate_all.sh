#!/usr/bin/env bash
# =============================================================================
# migrate_all.sh - Migra el MISMO contenedor por las 4 nubes, una tras otra.
#
# Lee la lista de nubes de clouds.env (copie clouds.env.example) y llama a
# deploy_remote.sh para cada una. Al final genera la comparación entre nubes.
#
# Uso:
#   export IMAGE=ghcr.io/usuario/adn-multicloud:latest
#   DNA_SIZE=100MB scripts/migrate_all.sh
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="${CONF:-$ROOT/clouds.env}"
[ -f "$CONF" ] || { echo "No existe $CONF. Copie clouds.env.example a clouds.env"; exit 1; }

ok=(); failed=()
# Formato de cada línea: nombre|usuario@ip|llave|origen|región|tipo_vm
while IFS='|' read -r name host key origin region instance; do
  [[ -z "$name" || "$name" =~ ^# ]] && continue
  key="${key/#\~/$HOME}"
  if "$ROOT/scripts/deploy_remote.sh" "$name" "$host" "$key" "$origin" "$region" "$instance"; then
    ok+=("$name")
  else
    failed+=("$name")
    echo "!! Falló el despliegue en $name, se continúa con la siguiente nube"
  fi
done < "$CONF"

echo
echo "Nubes OK     : ${ok[*]:-ninguna}"
echo "Nubes fallidas: ${failed[*]:-ninguna}"

if command -v python3 >/dev/null; then
  python3 "$ROOT/analysis/compare_clouds.py" "$ROOT/results" || true
fi
[ ${#failed[@]} -eq 0 ]
