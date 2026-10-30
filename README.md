# ADN Multinube: comparación de ADN migrando entre nubes con contenedores

**Materia:** Computación Paralela, Distribuida y en la Nube (PDN), Unidad III: Cloud Computing
**Proyecto:** P3.x XaaS, defensa de la Semana 09 (individual)
**Nubes:** americana · china · latinoamericana (Brasil) · ecuatoriana

Una sola imagen Docker procesa una cadena de ADN y se ejecuta **sin cambios** en cuatro proveedores de nube distintos y en dos modelos de servicio:

- **IaaS** (Azure, Huawei Cloud y Claro Cloud): se crea una VM, se instala Docker y el contenedor corre en **modo batch** por SSH.
- **PaaS** (GuaraCloud): la plataforma solo recibe la imagen y la ejecuta en **modo servidor HTTP**. No hay VM ni SSH.

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

El archivo que entregó el docente (Dropbox "ADN ARN 2025") es el **genoma humano de referencia GRCh38.p14** en formato FASTA (`.fna`, unos 3.11 GB):

- `GCA_000001405.29_GRCh38.p14_genomic.fna`: versión GenBank.
- `GCF_000001405.40_GRCh38.p14_genomic.fna`: versión RefSeq. Es el mismo ensamblaje, pero con otros nombres de secuencia.

Qué encontrarás en el resultado:

| Dato | Significado en el genoma real |
|---|---|
| Secuencias (registros) | Cromosomas 1 a 22, X, Y, mitocondrial y cientos de *scaffolds* y parches alternativos |
| Minúsculas | Regiones repetitivas enmascaradas (*soft-masking*). El programa las cuenta como bases válidas |
| N | Huecos del ensamblaje (centrómeros, telómeros), con millones de N |
| Inválidos | Códigos IUPAC de ambigüedad (R, Y, M, K…), que son muy pocos |

**Cómo llega el archivo a cada nube:** subir 3 GB desde tu laptop a cuatro nubes sería lento. Por eso cada nube **descarga el archivo directamente** desde el Dropbox del docente con `fetch_dna.py`, usando la conexión del datacenter. El programa calcula el **SHA-256** del archivo descargado, y si coincide en todas las nubes queda demostrado que procesaron exactamente el mismo archivo.

Para obtener el enlace de un **archivo** (no de la carpeta): en Dropbox, pasa el ratón sobre el archivo, abre el menú **⋯** y elige **Copiar enlace**. El programa convierte `dl=0` en `dl=1` automáticamente.

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
  Azure (EE.UU.)  Huawei (China) Claro (Ecuador)  GuaraCloud (BR) │
  ── IaaS: VM + docker compose, modo batch ──    ── PaaS ──       │
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
│   ├── main.py                # punto de entrada: APP_MODE=batch o server
│   ├── dna_processor.py       # procesamiento secuencial/paralelo
│   ├── server.py              # servidor HTTP + API del dashboard (PaaS y local)
│   ├── web/                   # interfaz gráfica (index.html, app.js, styles.css)
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
│   └── migrate_all.sh         # migra a todas las VMs y compara
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

En las tres nubes IaaS (Azure, Huawei y Claro) harás lo mismo. GuaraCloud tiene su propio paso (4B).

1. Crea una VM con **Ubuntu 22.04 o 24.04**, de 1 a 2 vCPU y de 1 a 4 GB de RAM.
2. Descarga o crea la **llave SSH**.
3. Abre el **puerto 22** en el firewall o grupo de seguridad.
4. Anota la **IP pública**.

Opcionalmente, pega `scripts/bootstrap_vm.sh` en el campo *User data* o *cloud-init* para que Docker quede instalado al arrancar la VM.

| Nube | Proveedor | Cómo obtenerlo | Recurso |
|---|---|---|---|
| 🇺🇸 Americana | **Microsoft Azure** (Azure for Students) | Registro con el correo institucional. Da USD 100 de crédito por 12 meses sin tarjeta | `Standard_B1s` o `B2s`, región `eastus` |
| 🇨🇳 China | **Huawei Cloud** (internacional) | Paquete gratuito de 12 meses para cuentas nuevas. Pide registrar un método de pago | `s6.medium.2`, región **LA-Santiago** o **LA-Mexico City1** (menor latencia desde Ecuador) |
| 🇧🇷 Latinoamericana | **GuaraCloud** (PaaS brasileña, servidores en São Paulo) | Inicio de sesión con GitHub o Google en guaracloud.com. Cobra en reales | Servicio desde imagen Docker (no es VM) |
| 🇪🇨 Ecuatoriana | **Claro Cloud Empresarial** (América Móvil, datacenter en Ecuador) | Compra en línea en clarocloud.com.ec. Cobra por uso: USD 0.0125 por vCPU/hora y USD 0.0069 por GB de RAM/hora | 2 vCPU y 4 GB, con Ubuntu |

**Notas importantes por proveedor**

- **Azure:** si antes activaste la prueba gratuita normal con el mismo correo, es posible que ya no puedas usar Azure for Students.
- **Huawei Cloud:** el paquete gratuito aplica solo a imágenes Linux. Las cuentas registradas en Brasil, Perú o Chile no son elegibles, pero una cuenta de Ecuador sí debería serlo.
- **GuaraCloud:** se eligió en lugar de Magalu Cloud, que no permitió activar la cuenta. Incluye en el informe la captura del bloqueo de Magalu como justificación. GuaraCloud es una **PaaS**: según su autor, corre sobre infraestructura de Linode/Akamai en São Paulo. Discute esto en el análisis: la empresa y la facturación son brasileñas, pero el hardware es de un proveedor estadounidense.
- **Claro Cloud (Ecuador):** es uno de los proveedores ecuatorianos del documento. Se compra en línea, Claro valida los datos y envía por correo el acceso al panel. Como cobra por uso, una VM de 2 vCPU y 4 GB encendida unas 10 horas cuesta menos de USD 1, más unos USD 2.40 al mes por un disco de 30 GB. Antes de comprar, confirma con Claro (sop.tec.empresa.ec@claro.com.ec, 04 500-500) si aceptan persona natural con cédula y qué formas de pago admiten. Si Claro no es viable, las alternativas de la misma lista son Telconet o CNT, pero ambas se contratan por cotización comercial.
- Usuario SSH por defecto: Azure usa `azureuser`, Huawei usa `root`. En Claro, revísalo en el panel al crear la VM.

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

# Ejemplo: Azure
scripts/deploy_remote.sh azure azureuser@IP_AZURE ~/.ssh/azure.pem "EE.UU." eastus Standard_B1s
```

El script hace todo solo: copia el compose, instala Docker si hace falta, descarga la **misma** imagen, descarga el genoma en la nube, lo procesa y trae el JSON a `results/azure/`. También trae el SHA-256 y el tiempo de descarga del genoma.

**Requisitos de la VM para el genoma completo:** al menos **8 GB de disco libre** (el archivo ocupa 3.1 GB) y 1 GB de RAM o más. Con 1 GB de RAM usa `WORKERS=1` o `CHUNK_MB=16`.

Para migrar a las tres VMs de una sola vez:

```bash
cp clouds.env.example clouds.env   # completa las IPs, usuarios y llaves reales
scripts/migrate_all.sh
```

`migrate_all.sh` también registra cuánto tardó el despliegue en cada nube, en `results/deploy_times.csv`.

### Paso 4B: Desplegar en GuaraCloud (PaaS)

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

Cuando termines y guardes las evidencias, **elimina las VMs, los discos y las IPs públicas** en Azure, Huawei y Claro, y el servicio en GuaraCloud, para no consumir crédito ni recibir cobros.

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
