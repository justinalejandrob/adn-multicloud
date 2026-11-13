#!/usr/bin/env bash
# =============================================================================
# nube.sh - Operaciones REALES sobre los contenedores de una nube (por SSH).
#   (El botón «Apagar nube» del dashboard es una simulación: la nube deja de
#    aceptar trabajo. Este script detiene de verdad los contenedores.)
#
#   bash scripts/cluster/nube.sh estado            # todas: contenedores + WireGuard
#   bash scripts/cluster/nube.sh apagar  usa       # docker stop adn-nodo  (caída real)
#   bash scripts/cluster/nube.sh apagar  usa --etcd  # también el miembro de etcd
#   bash scripts/cluster/nube.sh encender usa      # docker start adn-etcd adn-nodo
#   bash scripts/cluster/nube.sh logs    usa       # docker logs --tail 50 adn-nodo
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/_nubes.sh"
ACCION="${1:-estado}"; N="${2:-}"
case "$ACCION" in
  estado)
    while IFS='|' read -r n _ _ priv _; do
      echo "== $n ($priv)"
      en "$n" "sudo docker ps -a --filter name=adn- --format '   {{.Names}}: {{.Status}}'; \
               echo \"   WireGuard: \$(sudo wg show wg0 latest-handshakes 2>/dev/null | awk '\$2>0' | wc -l) túneles activos\"" </dev/null \
        || echo "   (sin conexión SSH)"
    done < <(nubes) ;;
  apagar)
    [ -n "$N" ] || { echo "Indique la nube"; exit 1; }
    if [ "${3:-}" = "--etcd" ]; then en "$N" "sudo docker stop adn-nodo adn-etcd"; else en "$N" "sudo docker stop adn-nodo"; fi ;;
  encender)
    [ -n "$N" ] || { echo "Indique la nube"; exit 1; }
    en "$N" "sudo docker start adn-etcd adn-nodo" ;;
  logs)
    [ -n "$N" ] || { echo "Indique la nube"; exit 1; }
    en "$N" "sudo docker logs --tail 50 adn-nodo" ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
