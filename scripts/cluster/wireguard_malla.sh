#!/usr/bin/env bash
# =============================================================================
# wireguard_malla.sh - Red privada WireGuard entre las 5 nubes (malla completa).
#
# Cada nube recibe una IP privada 10.99.0.x (cluster/nubes.conf) y un túnel
# cifrado directo hacia cada una de las otras 4. Por esa red viajan etcd
# (2379/2380) y los pedidos al worker (8000): nada de eso queda expuesto a internet.
#
# Uso (en la PC, desde la carpeta del proyecto):
#   bash scripts/cluster/wireguard_malla.sh
#
# Requisitos: SSH sin contraseña a cada nube y el puerto UDP 51820 abierto en el
# firewall / grupo de seguridad de cada proveedor.
# Las claves privadas NUNCA salen de su nube: se generan allí y solo se
# intercambian las públicas.
# =============================================================================
set -euo pipefail
source "$(dirname "$0")/_nubes.sh"
PORT_WG=51820
declare -A PUB

echo "== 1/3 Instalando WireGuard y generando claves en cada nube =="
while IFS='|' read -r n _; do
  PUB[$n]=$(en "$n" 'command -v wg >/dev/null || { (sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard-tools) >/dev/null 2>&1 || sudo dnf install -y -q wireguard-tools || sudo yum install -y -q wireguard-tools; } ;
    sudo sh -c "umask 077; mkdir -p /etc/wireguard; [ -f /etc/wireguard/adn.key ] || wg genkey > /etc/wireguard/adn.key; wg pubkey < /etc/wireguard/adn.key"' </dev/null | tail -1)
  echo "  $n -> clave pública ${PUB[$n]:0:12}…"
done < <(nubes)

echo "== 2/3 Configurando la malla (wg0) =="
while IFS='|' read -r n userip _ priv _; do
  conf="[Interface]
# Nube: $n
Address = $priv/24
ListenPort = $PORT_WG
PostUp = wg set %i private-key /etc/wireguard/adn.key
"
  while IFS='|' read -r m userip2 _ priv2 _; do
    [ "$m" = "$n" ] && continue
    conf+="
[Peer]
# $m
PublicKey = ${PUB[$m]}
Endpoint = ${userip2#*@}:$PORT_WG
AllowedIPs = $priv2/32
PersistentKeepalive = 25
"
  done < <(nubes)
  printf '%s' "$conf" | en "$n" "sudo sh -c 'umask 077; cat > /etc/wireguard/wg0.conf' &&
    (command -v ufw >/dev/null && sudo ufw status | grep -q active && sudo ufw allow $PORT_WG/udp >/dev/null && sudo ufw allow from 10.99.0.0/24 >/dev/null || true) &&
    sudo systemctl enable wg-quick@wg0 >/dev/null 2>&1; sudo systemctl restart wg-quick@wg0 || sudo wg-quick up wg0"
  echo "  $n: wg0 = $priv"
done < <(nubes)

echo "== 3/3 Probando la malla (ping por la red privada) =="
sleep 3
while IFS='|' read -r n _; do
  line="  $n →"
  while IFS='|' read -r m _ _ priv2 _; do
    [ "$m" = "$n" ] && continue
    if ms=$(en "$n" "ping -c 2 -W 2 $priv2 | tail -1 | awk -F/ '{print \$5}'" </dev/null) && [ -n "$ms" ]; then
      line+=" $m ${ms} ms"
    else
      line+=" $m ✗"
    fi
  done < <(nubes)
  echo "$line"
done < <(nubes)
echo
echo "Si alguna ruta sale ✗: abra UDP $PORT_WG en el panel de esa nube. Si el VPS no permite"
echo "módulos del kernel (contenedores LXC/OpenVZ), instale wireguard-go o boringtun."
