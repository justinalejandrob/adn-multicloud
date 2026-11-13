#!/usr/bin/env bash
# Funciones comunes: lee cluster/nubes.conf
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONF="${NUBES_CONF:-$ROOT/cluster/nubes.conf}"
[ -f "$CONF" ] || { echo "Falta $CONF (copie cluster/nubes.conf.example y complete las IP)"; exit 1; }

# nubes: imprime una línea limpia por nube (sin comentarios ni espacios extra)
nubes() { grep -vE '^\s*(#|$)' "$CONF" | sed -E 's/[[:space:]]*\|[[:space:]]*/|/g; s/^[[:space:]]+|[[:space:]]+$//g'; }

# campo NOMBRE NUM  (1=nombre 2=user@ip 3=puerto 4=ip_privada 5=proveedor ...)
campo() { nubes | awk -F'|' -v n="$1" -v c="$2" '$1==n {print $c}'; }

# ejecutar por SSH en una nube:  en NOMBRE "comando"
en() { local n="$1"; shift; ssh -p "$(campo "$n" 3)" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$(campo "$n" 2)" "$@"; }
copiar() { local n="$1" dest="$2"; shift 2; scp -q -P "$(campo "$n" 3)" -o StrictHostKeyChecking=accept-new "$@" "$(campo "$n" 2):$dest"; }

# lista de miembros de etcd: usa=http://10.99.0.1:2380,...
etcd_peers() { nubes | awk -F'|' '{printf "%s%s=http://%s:2380", (NR>1?",":""), $1, $4}'; }
etcd_endpoints() { nubes | awk -F'|' '{printf "%shttp://%s:2379", (NR>1?",":""), $4}'; }
orden() { nubes | awk -F'|' '{printf "%s%s", (NR>1?",":""), $1}'; }
