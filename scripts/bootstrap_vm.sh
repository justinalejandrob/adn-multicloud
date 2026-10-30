#!/usr/bin/env bash
# =============================================================================
# bootstrap_vm.sh - Prepara una VM Linux recién creada en CUALQUIER nube.
#
# Instala Docker Engine + plugin compose. Funciona en Ubuntu/Debian (y en
# CentOS/Rocky/EulerOS vía el script oficial get.docker.com).
#
# Dos formas de usarlo:
#   a) Pegarlo como "User data"/"cloud-init"/"Script de inicialización" al
#      crear la VM (Azure: Custom data, Huawei: User Data, Magalu: user data).
#   b) Ejecutarlo por SSH: ssh usuario@IP 'bash -s' < scripts/bootstrap_vm.sh
# =============================================================================
set -euo pipefail

log() { echo "[bootstrap] $*"; }

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  log "Docker y compose ya están instalados: $(docker --version)"
  exit 0
fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

log "Instalando Docker con el script oficial (get.docker.com)..."
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
$SUDO sh /tmp/get-docker.sh

$SUDO systemctl enable --now docker

# Permite usar docker sin sudo al usuario que inició sesión
TARGET_USER="${SUDO_USER:-${USER:-}}"
if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ]; then
  $SUDO usermod -aG docker "$TARGET_USER" || true
  log "Usuario $TARGET_USER agregado al grupo docker (vuelva a iniciar sesión)."
fi

# VMs pequeñas (1 GB RAM) de capa gratuita: se crea swap de 2 GB para evitar
# que el procesamiento sea terminado por falta de memoria.
if ! swapon --show | grep -q . ; then
  log "Creando swap de 2 GB..."
  $SUDO fallocate -l 2G /swapfile || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=2048
  $SUDO chmod 600 /swapfile
  $SUDO mkswap /swapfile
  $SUDO swapon /swapfile
  echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
fi

log "Listo: $(docker --version) | $($SUDO docker compose version)"
