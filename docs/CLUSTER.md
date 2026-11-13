# Clúster ADN en 5 nubes: líder elegido con etcd y red privada WireGuard

El mismo contenedor corre en **cinco nubes de cinco regiones**. Entre todas analizan el genoma, por ejemplo los 6.7 GB de GRCh38 (GCA + GCF), repartido en fragmentos. A diferencia de un maestro fijo, aquí **no hay un punto único de falla**:

- El **líder** se elige automáticamente entre las nubes con **etcd**. Si la nube líder se cae, otra toma el mando en unos 8 a 12 segundos y **retoma el trabajo donde quedó**, sin repetir los fragmentos ya calculados.
- El mando se puede **ceder** a propósito desde el dashboard.
- Todo el tráfico interno (etcd y el trabajo) viaja por una **red privada WireGuard** (10.99.0.x) cifrada entre las nubes.
- Cada nube tiene **su propia copia** del genoma, verificada por SHA-256. Por internet solo viaja la orden *{archivo, offset, longitud}* y el resultado, no los gigabytes.

```
        Tu PC ──(túnel SSH: 8080 + 2379)──▶ cualquier nube ─▶ dashboard «Clúster»
                                                 │
      ┌──────────── red privada WireGuard 10.99.0.0/24 (UDP 51820) ────────────┐
      │                                                                        │
   ┌──┴───────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌────────┴──┐
   │   USA    │    │  EUROPA   │    │   CHINA   │    │   LATAM   │    │  ECUADOR  │
   │ AWS Ohio │    │ OVH Fránc.│    │ Huawei HK │    │ DonWeb AR │    │ Telecu EC │
   │ 10.99.0.1│    │ 10.99.0.2 │    │ 10.99.0.3 │    │ 10.99.0.5 │    │ 10.99.0.4 │
   │ adn-etcd │◀──▶│ adn-etcd  │◀──▶│ adn-etcd  │◀──▶│ adn-etcd  │◀──▶│ adn-etcd  │  Raft (5 miembros)
   │ adn-nodo │    │ adn-nodo  │    │ adn-nodo  │    │ adn-nodo  │    │ adn-nodo  │  worker + coordinador
   └──────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
        ★ líder del clúster (lease en etcd): reparte fragmentos y guarda su estado en etcd
```

## Las 5 nubes

| Nube | Proveedor | Región | Cómo se paga |
|---|---|---|---|
| `usa` | **AWS** | us-east-2 (Ohio) | Plan gratuito: hasta US$ 200 en créditos por 6 meses |
| `europa` | **OVHcloud** | DE1 (Fráncfort) | Crédito de US$ 200 y cobro por hora |
| `china` | **Huawei Cloud** | CN-Hong Kong (Alibaba exigió verificación con pasaporte) | Tarjeta (cobro por uso) |
| `latam` | **DonWeb** | Argentina | Cloud Server mensual (precio estimado). SSH en un puerto distinto (p. ej. 5349) |
| `ecuador` | **Telecu Cloud** | Guayaquil, Ecuador (red propia AS23246, verificado: 13 ms desde Quito) | VPS mensual TPX11: USD 15 + IVA |

Los datos de cada nube (IP, puerto SSH, IP privada, precios) van en `cluster/nubes.conf`.

## Qué corre en cada nube (una sola imagen, dos contenedores)

| Contenedor | `APP_MODE` | Qué hace | Escucha en |
|---|---|---|---|
| `adn-etcd` | `etcd` | Miembro de etcd. Es la memoria compartida del clúster, replicada con Raft, y tolera la caída de 2 de 5 miembros | `10.99.0.x:2379/2380` y `127.0.0.1:2379` |
| `adn-nodo` | `nodo` | **Worker** (calcula fragmentos con todos sus núcleos), **coordinador** (latido, elección de líder, reparto si es líder, medición de red) y **dashboard** | worker `10.99.0.x:8000` · dashboard `127.0.0.1:8080` |

Los dos usan `--network host` para ver la interfaz `wg0`. Ningún puerto del clúster queda abierto a internet: el worker escucha solo en la IP de WireGuard y el dashboard solo en localhost.

## Cómo funciona

1. **Latido:** cada nube publica cada 2 s en `/adn/nodos/<nube>` sus recursos (CPU por núcleo, RAM, carga, red), los archivos que tiene listos, sus IPs y su costo. La clave tiene un *lease* de 10 s: si la nube muere, desaparece sola.
2. **Elección:** el primero que crea `/adn/lider` (de forma atómica, con un *lease* de 6 s) es el líder. Las nubes compiten por orden de prioridad (el orden de `nubes.conf`). Si el líder deja de renovar su *lease*, la clave expira y otra nube toma el mando.
3. **Ceder mando:** el dashboard escribe `/adn/ceder = europa`. El líder renuncia y europa gana la elección, porque las demás esperan.
4. **Trabajo:** el líder parte los archivos en fragmentos (cada uno con `len(patrón)-1` bytes de solape) y los reparte **dinámicamente**: cada nube abre tantos pedidos como núcleos tiene, así que las rápidas procesan más. Cada fragmento terminado se guarda en `/adn/frag/<trabajo>/<n>`.
5. **Caída del líder a mitad del trabajo:** el nuevo líder lee de etcd qué fragmentos ya están hechos y **reparte solo los que faltan**.
6. **Caída de una nube trabajadora:** sus fragmentos vuelven a la cola y los toman las demás.
7. **Verificación:** opcionalmente, el líder repite el cálculo con 1 núcleo y comprueba que el resultado sea **idéntico**.

## Puesta en marcha

### 0. Crear las 5 VMs

Crea una VM Ubuntu 22.04 o 24.04 en cada nube y abre en su firewall o grupo de seguridad:
- **TCP 22** (o el puerto SSH de esa nube) para administrarla.
- **UDP 51820** para WireGuard.

**No abras** los puertos 2379, 2380, 8000 ni 8080 a internet.

### 1. SSH sin contraseña

```bash
ssh-keygen -t ed25519                                   # una vez, en tu PC
ssh-copy-id -p PUERTO -i ~/.ssh/id_ed25519.pub USUARIO@IP   # en cada nube
```

### 2. Configurar `cluster/nubes.conf`

```bash
cp cluster/nubes.conf.example cluster/nubes.conf        # completa las IP públicas y los precios reales
```

### 3. Red privada WireGuard (malla completa)

```bash
bash scripts/cluster/wireguard_malla.sh
```

El script genera las claves **dentro** de cada nube (la clave privada nunca sale de ella), configura `wg0` y prueba con ping las 20 rutas entre las nubes.

### 4. Instalar el clúster

```bash
CLAVE='invente-una-clave-larga'
bash scripts/cluster/desplegar_cluster.sh "$CLAVE"
# o con MIGRACIÓN EN VIVO (sin registro):
docker build -t adn-multicloud:latest .
bash scripts/cluster/desplegar_cluster.sh "$CLAVE" --migrar
```

### 5. Abrir el dashboard

```bash
bash scripts/cluster/conectar.sh            # → http://localhost:8080/#cluster
```

### 6. Llevar el genoma a las 5 nubes

El genoma (~3 GB) **no se guarda en GitHub ni en la imagen Docker**: va a la carpeta `~/cluster-adn/datos` de cada nube. La pestaña **Datos en las nubes** del dashboard tiene tres caminos:

| Opción | Cuándo usarla | Qué pasa |
|---|---|---|
| **① Descargar desde un enlace** | El enlace de OneDrive/SharePoint/Dropbox es del **archivo** y público («Cualquier persona con el vínculo») | Las 5 nubes descargan en paralelo con su propia conexión (lo más rápido) |
| **② Subir desde tu PC** | OneDrive pide iniciar sesión (enlace solo para la PUCE), o el enlace es de una carpeta | Primero descargas el `.fna` a tu PC y lo subes **una vez** a la nube conectada por el túnel SSH |
| **③ Copiar desde una nube** | Después de ②, o si una nube falló al descargar | Las nubes que no tienen el archivo lo copian desde la elegida por WireGuard |

Alternativa por consola a ② + ③, que se puede reanudar si se corta el internet:

```bash
bash scripts/cluster/subir_genoma.sh ~/Downloads/GCA_000001405.29_GRCh38.p14_genomic.fna usa
```

Cómo se tratan los enlaces de OneDrive:
- **SharePoint** (`…-my.sharepoint.com/:u:/…`), que es el OneDrive de la universidad: el programa agrega `download=1`.
- **OneDrive personal** (`1drv.ms/…`): el programa usa la API pública `shares` de Microsoft.

Si el enlace devuelve una página web (inicio de sesión o vista previa), la nube **no** la guarda como ADN: marca «error» y explica qué hacer.

Truco si el enlace no es público: en tu navegador inicia la descarga desde OneDrive, abre la lista de descargas, copia el enlace real del archivo (`…download.aspx?…tempauth=…`) y pégalo en la opción ①. Ese enlace funciona sin iniciar sesión durante un tiempo limitado (minutos u horas).

Al terminar, cada nube limpia el FASTA y calcula su SHA-256. La columna **¿Idéntico?** debe mostrar «✓ mismo SHA-256».

### 7. Analizar

Escribe los patrones (`TATAAA,GAATTC`), abre **Opciones**, marca los archivos y pulsa **Analizar X GB**.

## El dashboard (sección «Clúster»)

- **Barra de mando:** muestra por qué nube estás conectado, el líder del clúster, el líder de etcd (Raft) y las nubes vivas. Desde ahí defines los patrones, lanzas **Analizar** o **Cancelar**, pulsas **Medir red** y usas **Ceder mando a…**. En **Opciones** eliges archivos, operación (contar o comparar), tamaño de fragmento, pedidos por nube, soberanía (solo Ecuador), nubes participantes, verificación con 1 núcleo y "el líder solo reparte".
- **Tarjetas de las 5 nubes:**
  - Estado (VIVA, APAGADA o CAÍDA) y si es ★ líder.
  - Proveedor, región, instancia y precio.
  - CPU, vCPU, RAM, procesos, potencia en GFLOPS y GPU.
  - Carga y **CPU por núcleo**, con los núcleos que están calculando ADN coloreados.
  - IP pública e IP privada de WireGuard.
  - Botones **Apagar nube / Encender**.
- **Mapa de fragmentos:** cada casilla se colorea con la nube que la calculó. Las que están en curso parpadean.
- **Pestañas:**

| Pestaña | Contenido |
|---|---|
| Comparación por nube | Fragmentos, % del trabajo, GB, segundos de cálculo, GB/s y si la nube usó datos locales o enviados |
| Costo por transacción | USD/h, USD/mes, duración, costo del análisis, costo por 1 000 análisis, GB, USD por GB y % del costo. Incluye gráficos |
| Línea de tiempo | Diagrama de Gantt de los fragmentos por nube, con **marcas de cambio de líder** |
| Red entre nubes | Matrices 5×5 de **latencia (ms)** y **transferencia (MB/s)** entre nubes por WireGuard |
| Datos en las nubes | Qué archivo tiene cada nube y si las copias coinciden (SHA-256). Permite distribuir un archivo desde un enlace, subirlo desde la PC o replicarlo de una nube a otra |
| Historial | Todos los análisis: GB, duración, GB/s, líderes, costo y verificación |
| Eventos | Uniones, elecciones, cesiones, caídas, reasignaciones y trabajos |

## Demostraciones para la defensa

| Qué demostrar | Cómo |
|---|---|
| Migración en vivo | `bash scripts/cluster/migrar_imagen.sh europa` (`docker save \| gzip \| ssh \| docker load`) |
| Ceder el mando | **Ceder mando a → EUROPA** y luego **Ceder**: la estrella pasa a EUROPA y queda registrado en **Eventos** |
| Una nube que falla durante el análisis | Durante **Analizar**, pulsa **Apagar nube** en CHINA: sus fragmentos se reasignan |
| **Caída real del líder** | Durante **Analizar**: `bash scripts/cluster/nube.sh apagar usa`. En unos 10 s otra nube es líder y **retoma** el trabajo. La **Línea de tiempo** muestra el cambio |
| Tolerancia de etcd | `bash scripts/cluster/nube.sh apagar latam --etcd`: con 4 de 5 miembros, etcd sigue funcionando |
| Soberanía | **Opciones → Solo nubes en Ecuador** |
| Prueba local completa | `bash scripts/cluster/prueba_local.sh` (en Linux o WSL; también corre en el CI) |

## Comandos útiles

```bash
bash scripts/cluster/nube.sh estado            # contenedores y túneles WireGuard de cada nube
bash scripts/cluster/nube.sh logs europa       # docker logs del nodo
bash scripts/cluster/nube.sh encender usa      # docker start adn-etcd adn-nodo
# dentro de una nube:
sudo docker exec adn-etcd etcdctl endpoint status --cluster -w table
sudo docker exec adn-etcd etcdctl get /adn/lider
sudo wg show
```

## Problemas frecuentes

| Problema | Causa y solución |
|---|---|
| `wireguard_malla.sh` muestra ✗ en una ruta | El puerto UDP 51820 está cerrado en el panel de esa nube |
| `wg-quick` falla con *Operation not supported* | El VPS es un contenedor (LXC/OpenVZ) sin módulo del kernel. Usa `wireguard-go` o `boringtun`, o pide al proveedor un VPS KVM |
| etcd no forma quórum | Revisa la malla WireGuard. Con 5 miembros necesita al menos 3 vivos |
| Un miembro de etcd perdió su volumen | `etcdctl member remove` + `member add`, y reinstalar ese nodo con `CLUSTER_STATE=existing` en `nodo.env` |
| Una nube muestra «error» en Datos | Pasa el cursor sobre «error» para ver el motivo. Lo más común es un enlace privado de OneDrive: usa ② y ③ |
| «disco insuficiente» al subir | Se necesita ≈ 2,1 × el tamaño del archivo (archivo + caché limpia), unos 6,5 GB para el genoma. Amplía el disco de esa VM |
| «datos listos 0/2» en una nube | La nube está limpiando el FASTA (tarda unos segundos por GB), o el archivo no está en `~/cluster-adn/datos` |

**Al terminar, destruye las VMs.** AWS, Huawei y OVH cobran por hora.
