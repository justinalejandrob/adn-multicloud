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

# En imágenes mínimas (DonWeb, Telecu) puede no haber sudo; con root no hace falta.
PRE='S=""; [ "$(id -u)" -ne 0 ] && S=sudo; export DEBIAN_FRONTEND=noninteractive;'

echo "== 1/3 Preparando cada nube: paquetes, swap y claves WireGuard =="
while IFS='|' read -r n _; do
  PUB[$n]=$(en "$n" "$PRE"'
    need=""; for b in wg curl ping; do command -v $b >/dev/null || need=1; done
    if [ -n "$need" ]; then $S apt-get update -qq >/dev/null 2>&1; $S apt-get install -y -qq wireguard-tools curl iputils-ping ca-certificates >/dev/null 2>&1; fi
    # swap de 2 GB si la nube tiene menos de 3 GB de RAM y no tiene swap (Telecu, 2 GB)
    if [ "$(awk "/MemTotal/{print int(\$2/1024)}" /proc/meminfo)" -lt 3000 ] && [ "$(swapon --show | wc -l)" -eq 0 ]; then
      $S fallocate -l 2G /swapfile && $S chmod 600 /swapfile && $S mkswap /swapfile >/dev/null && $S swapon /swapfile &&
      { grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" | $S tee -a /etc/fstab >/dev/null; }
    fi
    $S sh -c "umask 077; mkdir -p /etc/wireguard; [ -f /etc/wireguard/adn.key ] || wg genkey > /etc/wireguard/adn.key; wg pubkey < /etc/wireguard/adn.key"' </dev/null | tail -1)
  if [ "${#PUB[$n]}" -eq 44 ] && [[ "${PUB[$n]}" == *= ]]; then
    echo "  $n -> clave pública ${PUB[$n]:0:12}…"
  else
    echo "  $n -> ERROR: no se obtuvo la clave pública (${PUB[$n]})"; exit 1
  fi
done < <(nubes)

echo "== 2/3 Configurando la malla (wg0) =="
while IFS='|' read -r n userip _ priv _; do
  conf="[Interface]
# Nube: $n
Address = $priv/24
ListenPort = $PORT_WG
PrivateKey = __CLAVE_LOCAL__
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
  # la clave privada se inserta DENTRO de la nube (nunca viaja por la red)
  printf '%s' "$conf" | en "$n" "$PRE"' $S sh -c "umask 077; sed \"s|__CLAVE_LOCAL__|\$(cat /etc/wireguard/adn.key)|\" > /etc/wireguard/wg0.conf" &&
    (command -v ufw >/dev/null && $S ufw status | grep -q active && $S ufw allow '"$PORT_WG"'/udp >/dev/null && $S ufw allow from 10.99.0.0/24 >/dev/null || true) &&
    $S systemctl enable wg-quick@wg0 >/dev/null 2>&1; $S systemctl restart wg-quick@wg0 || $S wg-quick up wg0'

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
