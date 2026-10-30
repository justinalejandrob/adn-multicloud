# =============================================================================
# Imagen del procesador de ADN - portable entre nubes (AWS/Azure, Huawei,
# Magalu Cloud, proveedor ecuatoriano...). La misma imagen corre en todas.
# Multi-arquitectura: linux/amd64 (Intel/AMD) y linux/arm64 (Ampere, Kunpeng).
# =============================================================================
FROM python:3.12-slim

LABEL org.opencontainers.image.title="adn-multicloud" \
      org.opencontainers.image.description="Procesamiento paralelo de cadenas de ADN portable entre nubes" \
      org.opencontainers.image.licenses="MIT"

# Python sin buffer (logs en tiempo real) y sin archivos .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DNA_FILE=/data/adn.txt \
    OUTPUT_DIR=/results \
    MODE=both \
    CHUNK_MB=32 \
    PATTERN=GATTACA

WORKDIR /app

# 1) Dependencias primero (aprovecha la caché de capas de Docker)
COPY app/requirements.txt .
RUN pip install -r requirements.txt

# 2) Código de la aplicación
COPY app/ .

# 3) Usuario sin privilegios (buena práctica de seguridad)
RUN useradd --create-home --uid 1000 adn \
 && mkdir -p /data /results \
 && chown -R adn:adn /data /results /app
USER adn

# Volúmenes: el ADN entra por /data y los resultados salen por /results
VOLUME ["/data", "/results"]

# Modo servidor (PaaS): APP_MODE=server escucha en $PORT
EXPOSE 8080
ENV APP_MODE=batch \
    PORT=8080

# main.py elige el modo: batch (VMs) o server (PaaS como GuaraCloud)
ENTRYPOINT ["python", "main.py"]
CMD []
