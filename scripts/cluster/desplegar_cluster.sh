#!/usr/bin/env bash
# =============================================================================
# desplegar_cluster.sh - Instala o actualiza el clúster en las 5 nubes.
#
# Uso (en la PC, carpeta del proyecto; después de wireguard_malla.sh):
#   bash scripts/cluster/desplegar_cluster.sh 'CLAVE'               # docker pull en cada nube
#   bash scripts/cluster/desplegar_cluster.sh 'CLAVE' --migrar      # migración en vivo (save/load)
#   bash scripts/cluster/desplegar_cluster.sh 'CLAVE' europa china  # solo esas nubes
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/_nubes.sh"
TOKEN="${1:?Uso: desplegar_cluster.sh 'CLAVE' [--migrar] [nubes...]}"; shift
MIGRAR=0; ONLY=()
for a in "$@"; do [ "$a" = "--migrar" ] && MIGRAR=1 || ONLY+=("$a"); done
IMAGE="${IMAGE:-ghcr.io/justinalejandrob/adn-multicloud:latest}"
PEERS="$(etcd_peers)"; ENDS="$(etcd_endpoints)"; ORDEN="$(orden)"
ok=(); fail=()

while IFS='|' read -r n userip port priv prov pais region inst ch cm cobro; do
  if [ ${#ONLY[@]} -gt 0 ] && [[ ! " ${ONLY[*]} " == *" $n "* ]]; then continue; fi
  echo; echo "================= $n ($prov · $region) ================="
  tmp="$(mktemp)"
  cat > "$tmp" <<EOF
PRIVATE_IP=$priv
PUBLIC_IP=${userip#*@}
CLOUD_PROVIDER=$prov
CLOUD_ORIGIN=$pais
CLOUD_REGION=$region
INSTANCE_TYPE=$inst
COST_HOUR=$ch
COST_MONTH=$cm
BILLING=$cobro
CLUSTER_PEERS=$PEERS
ETCD_ENDPOINTS=http://127.0.0.1:2379,$ENDS
ORDEN=$ORDEN
EOF
  if en "$n" "mkdir -p ~/cluster-adn" </dev/null &&
     copiar "$n" "~/cluster-adn/" "$ROOT/scripts/cluster/instalar_nodo.sh" "$ROOT/scripts/bootstrap_vm.sh" &&
     copiar "$n" "~/cluster-adn/nodo.env" "$tmp"; then
    if [ "$MIGRAR" = 1 ]; then
      bash "$ROOT/scripts/cluster/migrar_imagen.sh" "$n" "${MIGRATE_IMAGE:-adn-multicloud:latest}" </dev/null || { fail+=("$n"); rm -f "$tmp"; continue; }
      img="${MIGRATE_IMAGE:-adn-multicloud:latest}"
    else
      img="$IMAGE"
    fi
    en "$n" "cd ~/cluster-adn && IMAGE='$img' bash instalar_nodo.sh '$n' '$TOKEN'" </dev/null && ok+=("$n") || fail+=("$n")
  else
    fail+=("$n")
  fi
  rm -f "$tmp"
done < <(nubes)

echo
echo "Instaladas : ${ok[*]:-ninguna}"
echo "Con errores: ${fail[*]:-ninguna}"
echo "Abra el dashboard con:  bash scripts/cluster/conectar.sh"
