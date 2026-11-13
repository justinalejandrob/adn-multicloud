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
#   bash scripts/cluster/nube.sh reiniciar usa     # docker restart adn-nodo
#   bash scripts/cluster/nube.sh logs    usa       # docker logs --tail 50 adn-nodo
# =============================================================================
set -uo pipefail
source "$(dirname "$0")/_nubes.sh"
ACCION="${1:-estado}"; N="${2:-}"
S='S=""; [ "$(id -u)" -ne 0 ] && S=sudo;'   # con root no hace falta sudo (imágenes mínimas)
case "$ACCION" in
  estado)
    while IFS='|' read -r n _ _ priv _; do
      echo "== $n ($priv)"
      en "$n" "$S"' $S docker ps -a --filter name=adn- --format "   {{.Names}}: {{.Status}}";
               echo "   WireGuard: $($S wg show wg0 latest-handshakes 2>/dev/null | awk "\$2>0" | wc -l) túneles activos";
               echo "   Nodo: $(curl -s -m 5 http://'"$priv"':8000/health | head -c 160)"' </dev/null \
        || echo "   (sin conexión SSH)"
    done < <(nubes)
    n1="$(nubes | head -1 | cut -d'|' -f1)"
    echo "== Miembros de etcd (vistos desde $n1)"
    en "$n1" "$S"' $S docker exec adn-etcd etcdctl --endpoints=http://127.0.0.1:2379 member list -w table;
             $S docker exec adn-etcd etcdctl --endpoints='"$(etcd_endpoints)"' endpoint status -w table' </dev/null ;;
  apagar)
    [ -n "$N" ] || { echo "Indique la nube"; exit 1; }
    if [ "${3:-}" = "--etcd" ]; then en "$N" "$S"' $S docker stop adn-nodo adn-etcd'; else en "$N" "$S"' $S docker stop adn-nodo'; fi ;;
  encender)
    [ -n "$N" ] || { echo "Indique la nube"; exit 1; }
    en "$N" "$S"' $S docker start adn-etcd adn-nodo' ;;
  reiniciar)
    [ -n "$N" ] || { echo "Indique la nube"; exit 1; }
    en "$N" "$S"' $S docker restart adn-nodo' ;;
  logs)
    [ -n "$N" ] || { echo "Indique la nube"; exit 1; }
    en "$N" "$S"' $S docker logs --tail 50 adn-nodo 2>&1' ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
