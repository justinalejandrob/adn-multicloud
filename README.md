# ADN Multinube: comparación de ADN migrando entre nubes con contenedores

**Materia:** Computación Paralela, Distribuida y en la Nube (PDN), Unidad III: Cloud Computing
**Proyecto:** P3.x XaaS, defensa de la Semana 09 y Evaluación S11 (individual)
**Nubes (5):** americana · china · latinoamericana (Brasil) · ecuatoriana · europea

Una sola imagen Docker procesa una cadena de ADN y se ejecuta **sin cambios** en cinco proveedores de nube distintos y en dos modelos de servicio. Se puede usar de dos maneras:

- **Migración:** la misma imagen se lleva de una nube a otra, y cada nube procesa el genoma completo (secciones 4 y 5).
- **Clúster distribuido (P4):** las 5 nubes analizan juntas el genoma, repartido en fragmentos. El **líder se elige con etcd** entre las nubes: si la nube líder se cae, otra toma el mando y retoma el trabajo. Las nubes se conectan por una **red privada WireGuard**. Ver **[docs/CLUSTER.md](docs/CLUSTER.md)**.

Hay dos modelos de servicio:

- **IaaS** (AWS, Alibaba Cloud, OVHcloud, DonWeb y Telecu): se crea una VM, se instala Docker y el contenedor corre en **modo batch** por SSH.
- **PaaS** (opcional, por ejemplo GuaraCloud): la plataforma solo recibe la imagen y la ejecuta en **modo servidor HTTP**. No hay VM ni SSH.

Cada nube devuelve los mismos conteos, y esa coincidencia es la prueba de portabilidad.

---

## 1. Qué hace el programa

| Función | Detalle |
|---|---|
| Lectura | Lee archivos de texto plano o FASTA de cualquier tamaño (4 MB, 1 GB, 4 GB) por bloques, sin cargarlos completos en RAM |
| Conteo | Cuenta A, C, G, T, N (indeterminado) y el contenido GC |
| Errores | Detecta los caracteres inválidos e indica cuántos hay de cada símbolo |
| Patrón | Busca un patrón genético (por defecto `GATTACA`) y cuenta ocurrencias solapadas, incluso las que cruzan el borde entre bloques |
| Paralelismo | Tiene modo secuencial (1 proceso) y paralelo (N procesos configurables), con cálculo de speedup y eficiencia |
| Integridad | Verifica que el resultado secuencial y el paralelo sean idénticos |
| Trazabilidad | Genera un JSON con el resultado y el hardware y la nube donde corrió |

### Datos: genoma humano de referencia GRCh38.p14

El archivo que entregó el docente (carpeta "ADN ARN 2025" en OneDrive/Dropbox) es el **genoma humano de referencia GRCh38.p14** en formato FASTA (`.fna`, unos 3.11 GB):

- `GCA_000001405.29_GRCh38.p14_genomic.fna`: versión GenBank.
- `GCF_000001405.40_GRCh38.p14_genomic.fna`: versión RefSeq. Es el mismo ensamblaje, pero con otros nombres de secuencia.

Qué encontrarás en el resultado:

| Dato | Significado en el genoma real |
|---|---|
| Secuencias (registros) | Cromosomas 1 a 22, X, Y, mitocondrial y cientos de *scaffolds* y parches alternativos |
| Minúsculas | Regiones repetitivas enmascaradas (*soft-masking*). El programa las cuenta como bases válidas |
| N | Huecos del ensamblaje (centrómeros, telómeros), con millones de N |
| Inválidos | Códigos IUPAC de ambigüedad (R, Y, M, K…), que son muy pocos |

**Cómo llega el archivo a cada nube:** subir 3 GB desde tu laptop a cinco nubes sería lento. Por eso hay tres caminos, en la pestaña **Datos en las nubes** del dashboard (detalle en `docs/CLUSTER.md`, paso 6):

1. **Desde un enlace:** cada nube descarga el archivo directamente de **OneDrive/SharePoint** o Dropbox con la conexión del datacenter. El programa convierte el enlace en descarga directa: SharePoint → `download=1`, `1drv.ms` → API `shares`, Dropbox → `dl=1`.
2. **Subir desde tu PC:** si OneDrive pide iniciar sesión, descarga el archivo y súbelo una sola vez a una nube. Puedes hacerlo desde el navegador o con `scripts/cluster/subir_genoma.sh`.
3. **Copiar entre nubes:** las demás lo copian desde esa nube por WireGuard.

En todos los casos, el programa calcula el **SHA-256** de la copia de cada nube. Si coincide en todas, queda demostrado que procesaron exactamente el mismo archivo. Si un enlace devuelve una página de inicio de sesión en vez del archivo, se rechaza con un mensaje claro y no se guarda como si fuera ADN.

Para obtener el enlace de un **archivo** (no de la carpeta) en OneDrive, haz clic derecho sobre el archivo, elige **Compartir** y luego **Copiar vínculo**, con el permiso «Cualquier persona con el vínculo».

Si no hay `DNA_URL`, el generador `generate_dna.py` crea ADN sintético **determinista**, que sirve para pruebas rápidas.

## 2. Arquitectura

```
                    ┌──────────────────────────────┐
  git push ───────► │ GitHub Actions (CI/CD)       │
                    │ test → build amd64+arm64 →   │
                    │ push ghcr.io/usuario/adn...  │
                    └──────────────┬───────────────┘
                                   │ misma imagen
       ┌──────────────┬────────────┼──────────────┬───────────────┐
       ▼              ▼            ▼              ▼               │
  AWS (EE.UU.)  Alibaba (China/SG)  OVH (Europa)  DonWeb (AR) · Telecu (EC)
  ── IaaS: VM + docker compose, modo batch ──    ── PaaS opc. ──  │
       │  (SSH + scp)  │            │             APP_MODE=server │
       │              │            │             HTTP /run        │
       └──────── results/<nube>/*.json ──────────────┘            │
                          ▼                                       │
              analysis/compare_clouds.py → tabla + gráficos ◄─────┘
```

## 3. Estructura de carpetas

```
adn-multicloud/
├── app/
│   ├── main.py                # punto de entrada: APP_MODE=batch, server o worker
│   ├── worker.py              # worker del clúster (puerto 8000, X-Token, todos los núcleos)
│   ├── coordinador.py         # latido, elección de líder con etcd, reparto y reanudación
│   ├── etcd_client.py         # cliente etcd v3 sin dependencias (con failover)
│   ├── etcd_node.py           # arranca un miembro de etcd (APP_MODE=etcd)
│   ├── cluster_api.py         # API del clúster para el dashboard (lee/escribe etcd)
│   ├── seqcache.py            # caché del FASTA limpio (.seq) y plan de fragmentos
│   ├── master.py              # maestro por terminal (modo sin etcd, pruebas)
│   ├── dna_processor.py       # procesamiento secuencial/paralelo
│   ├── server.py              # servidor HTTP + API del dashboard (PaaS y local)
│   ├── web/                   # interfaz gráfica (index.html, app.js, cluster.js, styles.css)
│   ├── prepare_data.py        # elige: descargar genoma real o generar sintético
│   ├── fetch_dna.py           # descarga el genoma (Dropbox/NCBI, .gz) + SHA-256
│   ├── generate_dna.py        # generador determinista de ADN sintético (FASTA)
│   └── requirements.txt
├── analysis/
│   └── compare_clouds.py      # comparación entre nubes + gráficos
├── scripts/
│   ├── bootstrap_vm.sh        # instala Docker en una VM nueva (cloud-init)
│   ├── deploy_remote.sh       # despliega y ejecuta en UNA VM por SSH (IaaS)
│   ├── run_paas.sh            # ejecuta y descarga resultados por HTTP (PaaS)
│   ├── migrate_all.sh         # migra a todas las VMs y compara
│   └── cluster/
│       ├── wireguard_malla.sh     # red privada WireGuard 10.99.0.x entre las 5 nubes
│       ├── desplegar_cluster.sh   # instala adn-etcd + adn-nodo en cada nube
│       ├── instalar_nodo.sh       # (se ejecuta dentro de cada nube)
│       ├── migrar_imagen.sh       # migración en vivo: docker save | gzip | ssh | docker load
│       ├── conectar.sh            # túnel SSH → http://localhost:8080/#cluster
│       ├── subir_genoma.sh        # sube el FASTA desde la PC a una nube y lo replica a las demás
│       ├── nube.sh                # estado, apagar/encender de verdad, logs
│       └── prueba_local.sh        # prueba completa en una máquina (también en el CI)
├── cluster/
│   └── nubes.conf.example     # las 5 nubes: IP, puerto SSH, IP privada, proveedor, precios
├── docs/
│   ├── CLUSTER.md             # guía del clúster en 5 nubes (etcd + WireGuard)
│   ├── COMANDOS_DOCKER.md     # build, run, ps, stop, start, rm, rmi, logs, exec, stats, save/load
│   └── EVALUACION_S11.md      # respuestas de la evaluación con evidencias del proyecto
├── .github/workflows/
│   └── docker-publish.yml     # pipeline CI/CD (test, build, push, deploy)
├── Dockerfile
├── docker-compose.yml
├── .env.example               # variables del experimento
├── clouds.env.example         # lista de VMs (IP, usuario, llave)
└── README.md
```

---

## 4. Guía paso a paso

### Paso 0: Herramientas en tu laptop

- **Git** y una cuenta de **GitHub**.
- **Docker Desktop**. En Windows, activa WSL 2.
- **Python 3.10+** y luego `pip install numpy matplotlib`.
- Una **terminal Bash** para los scripts: WSL (Ubuntu) o Git Bash en Windows.

### Paso 1: Probar en local (sin nube)

```bash
cp .env.example .env
mkdir -p data results
docker compose up --build
```

Esto usa ADN sintético de 100 MB. Para probar con el **genoma real sin descargar los 3 GB**, edita `.env` así y vuelve a ejecutar `docker compose up`:

```
DNA_URL='https://www.dropbox.com/scl/fi/...enlace-del-archivo...&dl=0'
DNA_LIMIT_MB=200
```

📸 **Evidencia:** captura de la salida con la tabla de tiempos y la línea `Validación secuencial == paralelo: OK`.

### Paso 1B: Interfaz gráfica (dashboard)

La misma imagen incluye un dashboard web sin dependencias externas:

```bash
docker compose up --build dashboard
```

Abre **http://localhost:8080**. Tiene cuatro secciones:

| Sección | Qué muestra |
|---|---|
| **Panel principal** | Estado de la ejecución (con % de avance), proveedor cloud, CPU, RAM y los 5 indicadores clave: tiempo, % GC, coincidencias del patrón, trabajadores y MB/s |
| **Procesamiento ADN** | Formulario para lanzar el análisis (límite, modo, trabajadores, bloque, patrón), avance por fases (descarga, secuencial, paralelo), composición A/C/G/T/N, contenido GC con la regla de Chargaff y códigos IUPAC inválidos |
| **Rendimiento** | Secuencial vs. paralelo, curva de speedup frente al ideal, MB/s por número de procesos, eficiencia y **ley de Amdahl** (fracción serial estimada con Karp–Flatt) |
| **Multicloud** | Comparación de todas las nubes: tarjetas por proveedor, tiempos, MB/s, speedup, descarga del genoma, tabla completa, exportación a CSV y **verificación de integridad** (mismo SHA-256 y conteos idénticos) |

La sección Multicloud lee automáticamente `results/` y sus subcarpetas `results/<nube>/`, que traen los scripts de despliegue. También puedes **arrastrar los `resultado_*.json`** de cada nube a la página. En GuaraCloud el dashboard es la página principal del servicio. En una VM, abre el puerto 8080 y ejecuta `sudo docker compose up -d dashboard`.

📸 **Evidencia:** capturas de las cuatro secciones, sobre todo Multicloud con el mensaje *"Resultados idénticos: portabilidad comprobada"*.

### Paso 2: Publicar la imagen en un registro (CI/CD)

1. Crea un repositorio **público** en GitHub llamado `adn-multicloud` y sube el proyecto:
   ```bash
   git init && git add . && git commit -m "Proyecto ADN multinube"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/adn-multicloud.git
   git push -u origin main
   ```
2. En la pestaña **Actions** verás el pipeline `build-test-deploy`. Ese pipeline prueba el código, construye la imagen para `amd64` y `arm64` y la publica en `ghcr.io/TU_USUARIO/adn-multicloud:latest`.
3. Haz pública la imagen para que las VMs puedan descargarla sin iniciar sesión. Ve a tu perfil, luego a **Packages**, abre `adn-multicloud`, entra en **Package settings** y en **Change visibility** elige **Public**.
4. En `.env.example`, reemplaza `TU_USUARIO` por tu usuario de GitHub en minúsculas.

📸 **Evidencia:** captura del pipeline en verde y del paquete publicado.

### Paso 3: Crear una VM en cada nube

En las 5 nubes (AWS, Alibaba Cloud, OVHcloud, DonWeb y Telecu) harás lo mismo. Para el **clúster con etcd** sigue después **[docs/CLUSTER.md](docs/CLUSTER.md)**. El paso 4B (PaaS) es opcional.

1. Crea una VM con **Ubuntu 22.04 o 24.04**, de 1 a 2 vCPU y de 1 a 4 GB de RAM.
2. Descarga o crea la **llave SSH**.
3. Abre el **puerto 22** en el firewall o grupo de seguridad.
4. Anota la **IP pública**.

Opcionalmente, pega `scripts/bootstrap_vm.sh` en el campo *User data* o *cloud-init* para que Docker quede instalado al arrancar la VM.

| Nube | Proveedor | Cómo obtenerlo | Recurso de referencia |
|---|---|---|---|
| 🇺🇸 Americana (`usa`) | **AWS** (us-east-2 Ohio) | Cuenta nueva con el plan gratuito: US$ 100 al registrarse y hasta US$ 100 más por usar servicios, durante 6 meses | `m7i-flex.large` (2 vCPU, 8 GB) |
| 🇨🇳 China (`china`) | **Alibaba Cloud** (internacional, ap-southeast-1 Singapur) | Cuenta internacional con tarjeta. Las regiones de China continental exigen trámites (ICP), por eso se usa la región internacional más cercana. **Anota la ubicación real** | `ecs.c9i.xlarge` (4 vCPU) o uno menor |
| 🇪🇺 Europea (`europa`) | **OVHcloud** (DE1 Fráncfort) | Public Cloud con US$ 200 de crédito y cobro por hora. El tráfico de salida está incluido (1 TB al mes por proyecto) | `b3-16` (4 vCPU, 16 GB) o `d2-4` |
| 🌎 Latinoamericana (`latam`) | **DonWeb** (Argentina) | Cloud Server con cuota mensual (precio **estimado** en el informe). Su SSH puede usar otro puerto (p. ej. 5349) | 1 vCPU, 1 GB |
| 🇪🇨 Ecuatoriana (`ecuador`) | **Telecu Cloud** (Quito) | VPS en Ecuador: TPX01 (1 vCPU, 1 GB, 20 GB SSD, 10 TB de tráfico) desde US$ 10 al mes | `TPX01` o `TPX11` |

**Notas importantes por proveedor**

- **Precios:** cópialos de **tu** panel a `cluster/nubes.conf`. El dashboard calcula con ellos el costo por transacción.
- **WireGuard:** abre **UDP 51820** en el firewall de cada nube. Si un VPS mensual (DonWeb, Telecu) es un contenedor sin módulos del kernel, usa `wireguard-go` (ver docs/CLUSTER.md).
- **Usuario SSH:** AWS (Ubuntu) usa `ubuntu`; Alibaba, `root`; OVH, `ubuntu`. En DonWeb y Telecu, el que indique el panel.

📸 **Evidencia:** captura de cada consola con la VM creada, mostrando la región y el tipo de VM.

### Paso 4: Desplegar en las VMs (IaaS)

Desde Bash en tu laptop:

```bash
export IMAGE=ghcr.io/TU_USUARIO/adn-multicloud:latest
export DNA_URL='https://www.dropbox.com/scl/fi/...enlace-del-archivo...&dl=0'
export DNA_LIMIT_MB=0          # 0 = genoma completo (3.1 GB)
export WORKERS=0               # 0 = todos los núcleos de la VM

chmod +x scripts/*.sh
chmod 600 ~/.ssh/*.pem

# Ejemplo: AWS
scripts/deploy_remote.sh usa ubuntu@IP_USA ~/.ssh/aws.pem "EE.UU." us-east-2 m7i-flex.large
```

El script hace todo solo: copia el compose, instala Docker si hace falta, descarga la **misma** imagen, descarga el genoma en la nube, lo procesa y trae el JSON a `results/usa/`. También trae el SHA-256 y el tiempo de descarga del genoma.

**Requisitos de la VM para el genoma completo:** al menos **8 GB de disco libre** (el archivo ocupa 3.1 GB) y 1 GB de RAM o más. Con 1 GB de RAM usa `WORKERS=1` o `CHUNK_MB=16`.

Para migrar a las cuatro VMs de una sola vez:

```bash
cp clouds.env.example clouds.env   # completa las IPs, usuarios y llaves reales
scripts/migrate_all.sh
```

`migrate_all.sh` también registra cuánto tardó el despliegue en cada nube, en `results/deploy_times.csv`.

### Paso 4B (opcional): Desplegar en una PaaS (por ejemplo, GuaraCloud)

En una PaaS no hay VM ni SSH. La plataforma descarga la imagen y la mantiene encendida, así que se usa la **misma imagen** en modo servidor:

1. En guaracloud.com, crea un **proyecto** (por ejemplo `adn-multinube`).
2. Crea un **servicio** y elige la opción **Docker Image**. Imagen: `ghcr.io/TU_USUARIO/adn-multicloud:latest`, que debe ser pública (Paso 2.3).
3. En **Port**, escribe `8080`.
4. En **Environment variables**, agrega:
   ```
   APP_MODE=server
   CLOUD_PROVIDER=guaracloud
   CLOUD_ORIGIN=Brasil
   CLOUD_REGION=Sao-Paulo
   INSTANCE_TYPE=plan-gratuito
   DNA_URL=https://www.dropbox.com/scl/fi/...enlace-del-archivo...&dl=0
   ```
5. Pulsa **Deploy**. Cuando el servicio esté activo, abre la URL pública (`https://...guaracloud.com`) y verás la página del procesador.
6. Ejecuta el procesamiento y descarga los resultados desde tu laptop:
   ```bash
   scripts/run_paas.sh guaracloud https://TU-SERVICIO.guaracloud.com 0 both
   ```
   El `0` significa "genoma completo". También puedes hacerlo desde el navegador con el botón **Ejecutar** y luego **Descargar JSON**.

Las PaaS suelen tener disco temporal y RAM limitados. Si el genoma completo falla por espacio o memoria, ejecuta con un límite (por ejemplo `500` = primeros 500 MB) y agrega `CHUNK_MB=8`. **Documenta ese límite en el informe**: es una diferencia real entre IaaS y PaaS.

📸 **Evidencia:** captura del servicio en el panel de GuaraCloud, de la página con el resultado y de los logs.

### Paso 5: Comparar las nubes

```bash
python analysis/compare_clouds.py results
```

Este comando genera lo siguiente en `results/`:

- `comparacion_nubes.md` y `comparacion_nubes.csv`: tiempos, speedup, eficiencia, MB/s y hardware de cada nube.
- La sección **"Validación de integridad"**, que debe decir *IDÉNTICOS en todas las nubes*. Esa es tu prueba de portabilidad.
- `grafico_tiempos.png` y `grafico_throughput.png`, más `grafico_speedup.png` si ejecutas con `MODE=benchmark`.

### Paso 6: Apagar y borrar las VMs

Cuando termines y guardes las evidencias, **elimina las VMs, los discos y las IPs públicas** en AWS, Alibaba, OVHcloud, DonWeb y Telecu (y el servicio PaaS si lo usaste), para no consumir crédito ni recibir cobros.

---

## 5. Parámetros

| Variable | Por defecto | Descripción |
|---|---|---|
| `DNA_URL` | vacío | Enlace del genoma real (Dropbox/NCBI, también `.gz`). Vacío = ADN sintético |
| `DNA_LIMIT_MB` | `0` | Procesar solo los primeros N MB del genoma (0 = completo) |
| `DNA_SIZE` | `100MB` | Tamaño del ADN sintético (`4MB`, `1GB`, `4GB`...) |
| `SEED` | `2026` | Semilla. La misma semilla genera el mismo archivo en todas las nubes |
| `MODE` | `both` | `sequential`, `parallel`, `both` o `benchmark` (prueba con 1, 2, 4... procesos) |
| `WORKERS` | `0` (todos) | Número de procesos en modo paralelo |
| `CHUNK_MB` | `32` | Tamaño de cada bloque. Bájalo en VMs de 1 GB de RAM |
| `PATTERN` | `GATTACA` | Patrón genético a buscar |
| `APP_MODE` | `batch` | `batch` procesa y termina (VMs). `server` levanta el servidor HTTP (PaaS) |
| `PORT` | `8080` | Puerto del modo servidor |

Si prefieres subir tú mismo un archivo de ADN a una VM en vez de usar `DNA_URL`, cópialo a la carpeta `data/` con otro nombre y ejecuta solo el procesador. `--no-deps` evita que se ejecute el paso de preparación:

```bash
scp -i llave.pem mi_adn.fna usuario@IP:~/adn-multicloud/data/
sudo docker compose run --rm --no-deps processor --input /data/mi_adn.fna --mode both
```

## 6. Relación con la rúbrica

| Criterio (10 pts c/u) | Dónde se evidencia |
|---|---|
| Aplicación en contenedor | `Dockerfile` (multi-arquitectura, usuario sin root, volúmenes) y `docker-compose.yml` con dos servicios |
| Portabilidad entre proveedores | Cuatro nubes y dos modelos de servicio (IaaS y PaaS) con la misma imagen y la validación de integridad en `comparacion_nubes.md` |
| Automatización (CI/CD o scripts) | GitHub Actions (test, build, push, deploy), `deploy_remote.sh`, `migrate_all.sh` y `bootstrap_vm.sh` |
| Análisis comparativo | `compare_clouds.py` (rendimiento) más la tabla cualitativa del informe: soporte de contenedores, redes, costos e integración |
| Documentación técnica | Este README, la estructura de carpetas y los pasos reproducibles |

## 7. Problemas frecuentes

| Problema | Solución |
|---|---|
| `permission denied` al escribir en `/results` | `sudo chown -R 1000:1000 data results` en la VM. El script ya lo hace |
| `denied` al hacer `docker pull` | El paquete de GHCR sigue privado. Hazlo público (Paso 2.3) |
| El proceso muere con `Killed` | Falta RAM. Usa `CHUNK_MB=8`, `WORKERS=1` o un archivo más pequeño. `bootstrap_vm.sh` crea 2 GB de swap |
| `Connection timed out` por SSH | Abre el puerto 22 en el grupo de seguridad o firewall de la nube |
| VM ARM (Ampere/Kunpeng) | Funciona igual: la imagen se publica para `arm64` |
