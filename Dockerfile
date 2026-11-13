# =============================================================================
# Imagen ÚNICA del proyecto ADN multinube. La misma imagen corre en las 5 nubes
# (AWS, Alibaba Cloud, OVHcloud, DonWeb, Telecu) y sirve para todo:
#   APP_MODE=nodo    worker (8000) + coordinador (líder con etcd) + dashboard (8080)
#   APP_MODE=etcd    miembro de etcd (memoria compartida del clúster)
#   APP_MODE=server  dashboard / modo PaaS          APP_MODE=batch  procesa y termina
# Multi-arquitectura: linux/amd64 (Intel/AMD) y linux/arm64 (Graviton, Ampere, Yitian).
# =============================================================================

# --- Etapa 1: binario de etcd para la arquitectura de destino -----------------
FROM python:3.12-slim AS etcd
ARG TARGETARCH=amd64
ARG ETCD_VER=v3.5.17
RUN python -c "import io,tarfile,urllib.request; \
u='https://github.com/etcd-io/etcd/releases/download/${ETCD_VER}/etcd-${ETCD_VER}-linux-${TARGETARCH}.tar.gz'; \
t=tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(u).read())); \
[ (setattr(m,'name',m.name.split('/')[-1]), t.extract(m,'/usr/local/bin')) for m in t.getmembers() if m.name.split('/')[-1] in ('etcd','etcdctl') ]" \
 && /usr/local/bin/etcd --version

# --- Etapa 2: aplicación --------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="adn-multicloud" \
      org.opencontainers.image.description="Clúster de ADN en 5 nubes con líder elegido por etcd" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DNA_FILE=/data/adn.txt \
    OUTPUT_DIR=/results \
    DATA_DIR=/datos \
    MODE=both \
    CHUNK_MB=32 \
    PATTERN=GATTACA

WORKDIR /app

# 1) Dependencias primero (aprovecha la caché de capas de Docker)
COPY app/requirements.txt .
RUN pip install -r requirements.txt

# 2) etcd (misma imagen para todo: no se usa una imagen aparte)
COPY --from=etcd /usr/local/bin/etcd /usr/local/bin/etcdctl /usr/local/bin/

# 3) Código de la aplicación
COPY app/ .

# 4) Usuario sin privilegios (buena práctica de seguridad)
RUN useradd --create-home --uid 1000 adn \
 && mkdir -p /data /results /datos /etcd-data \
 && chown -R adn:adn /data /results /datos /etcd-data /app
USER adn

# Volúmenes: ADN de entrada, resultados, FASTA del clúster y datos de etcd
VOLUME ["/data", "/results", "/datos", "/etcd-data"]

# 8080 dashboard · 8000 worker · 2379/2380 etcd
EXPOSE 8080 8000 2379 2380
ENV APP_MODE=batch \
    PORT=8080

ENTRYPOINT ["python", "main.py"]
CMD []
