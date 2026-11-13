# Evaluación S11: Cloud Computing y Sistemas Distribuidos

Las respuestas se apoyan en dos fuentes: información verificada (ver **Fuentes** al final) y **evidencia medida con este proyecto**. El proyecto es un clúster de ADN que corre la misma imagen Docker en 5 nubes: EE. UU. (AWS, Ohio), China (Huawei Cloud, Hong Kong), Europa (OVHcloud, Fráncfort), Latinoamérica (DonWeb, Argentina) y Ecuador (Telecu Cloud, Guayaquil). El líder del clúster se elige con etcd y las nubes se comunican por una red privada WireGuard.

> **Antes de presentar:** completa las tablas marcadas con 📏 usando tus propias mediciones. Están en el dashboard, sección **Clúster → Medir red** y **Resultado del trabajo**, y en `results/red_*.json` y `results/cluster_*.json`.

---

## Pregunta 1: Latencia y rendimiento en procesamiento transaccional

**Respuesta:** para un RTT menor a 15 ms, la opción que lo garantiza es el **data center local TIER III en Ecuador** (por ejemplo, Telconet en Quito, o los centros de Claro en Quito y Durán, también certificados TIER III por el Uptime Institute). Una región de un hiperescalar en EE. UU. **no puede** cumplirlo, por una limitación física.

**Por qué es física y no un tema de proveedor:**
- La luz en la fibra viaja a unos 200 000 km/s. Eso equivale a **1 ms de ida y vuelta por cada 100 km**, sin contar los equipos intermedios.
- Quito–Miami son unos 2 900 km en línea recta, así que el **mínimo teórico es de unos 29 ms**.
- Quito–Virginia (la región us-east de AWS y Azure) son unos 4 400 km, con un **mínimo de unos 44 ms**.
- La ruta real es más larga: baja de Quito a la costa, sigue por cable submarino vía Panamá o Colombia y pasa por varios saltos de red. En la práctica, la latencia suele ser mucho mayor que esos mínimos.
- Un data center en Quito está a menos de 50 km de la oficina. Su RTT típico es de **1 a 5 ms**, con poca variación (jitter).

**Impacto en los SLA:**
- Los SLA de los hiperescalares garantizan **disponibilidad** del servicio (por ejemplo, 99.9 %), no la latencia de extremo a extremo por internet, que depende de redes ajenas al proveedor.
- A más distancia, más saltos y más jitter, y por lo tanto más riesgo de superar el umbral en los percentiles altos (p95/p99). Además, cada fallo de un tramo internacional afecta al servicio.
- Con un data center local, el banco puede firmar un SLA de latencia con el proveedor de conectividad, porque controla toda la ruta.

**Recomendación:** el microservicio de autorizaciones debe correr en el DC local TIER III, que es donde se cumple el RTT. El hiperescalar se puede usar para lo que tolera latencia: analítica, respaldo y recuperación ante desastres.

📏 **Evidencia del proyecto:** en la pestaña **Red entre nubes** del dashboard, cada nube mide su **latencia (RTT, en ms)** y su **velocidad de transferencia (MB/s)** hacia las otras por WireGuard. Los valores menores a 15 ms se marcan con ✓. La fila **ECUADOR** (Telecu, en Ecuador) da la latencia desde un servidor del país hacia las demás regiones. Además, desde la PC del estudiante en Quito se mide el `ping` hacia la IP pública de cada nube.

| Desde la PC en Quito hacia | Ubicación | RTT medido (ms) | ¿< 15 ms? | Transferencia (MB/s) |
|---|---|---|---|---|
| usa | AWS, Ohio (EE. UU.) | … | … | … |
| latam | DonWeb, Argentina | … | … | … |
| europa | OVHcloud, Fráncfort | … | … | … |
| china | Huawei Cloud, Hong Kong | … | … | … |

La conclusión esperada es que ninguna región fuera de Ecuador queda por debajo de 15 ms. Para el umbral del banco, solo sirve un servidor dentro del país.

---

## Pregunta 2: Soberanía de datos y cumplimiento normativo

**Marco legal:**
- La **Ley Orgánica de Protección de Datos Personales (LOPDP)** de Ecuador, vigente desde 2021.
- La **Norma General de Transferencias Nacionales e Internacionales** (Resolución SPDP-SPD-2026-0004-R, del 28 de enero de 2026). Esta norma solo permite transferencias internacionales:
  - a países con **nivel adecuado** reconocido por la Superintendencia (SPDP);
  - con **garantías adecuadas**: cláusulas contractuales modelo de la Red Iberoamericana de Protección de Datos, normas corporativas vinculantes, códigos de conducta o certificaciones;
  - o con **autorización excepcional** de la SPDP, previo análisis de riesgo y evaluación de impacto.
- Además, exige documentar cada transferencia e inscribirla en el **Registro Nacional de Transferencias Internacionales**.

| Opción | Implicaciones legales | Gobernanza |
|---|---|---|
| **a) Nube estatal ecuatoriana (CNT EP)** | Los datos no salen del país, así que **no hay transferencia internacional** que justificar. Es el camino de menor riesgo legal y está bajo jurisdicción ecuatoriana | Hay que verificar certificaciones (TIER, ISO 27001), cifrado y control de accesos. Depender de un solo proveedor estatal implica evaluar su capacidad y su continuidad |
| **b) Proveedor soberano europeo (OVHcloud)** | Es una **transferencia internacional**: requiere nivel adecuado o cláusulas contractuales y su registro. OVHcloud es europeo y no está sujeto a la ley estadounidense; su plataforma SNC Cloud Platform obtuvo en 2026 la calificación **SecNumCloud** de la ANSSI (Francia). Aplica el GDPR, que es de un nivel alto | La institución depende de contratos y auditorías en otra jurisdicción. Si hay una disputa, se resuelve en Europa |
| **c) Hiperescalar de EE. UU. (sujeto al CLOUD Act)** | También es una transferencia internacional. Además, el **CLOUD Act (2018)** permite a las autoridades de EE. UU. exigir a un proveedor estadounidense los datos bajo su control, **aunque estén almacenados fuera de EE. UU.** Esto puede chocar con el deber de confidencialidad de la LOPDP | Es la opción de mayor riesgo para registros ciudadanos confidenciales. Se mitiga parcialmente con cifrado y claves gestionadas por la institución (fuera del proveedor), aunque eso no elimina el riesgo jurídico |

**Recomendación:** usar la **nube estatal ecuatoriana (CNT EP) o un DC nacional certificado** para los registros ciudadanos. Las opciones b y c quedan solo para datos anonimizados o no personales, o con cláusulas contractuales, cifrado propio y registro ante la SPDP.

📏 **Evidencia del proyecto (hallazgo real):**
- Durante el montaje se probó primero un VPS facilitado por un tercero y presentado como «ecuatoriano». Al verificarlo técnicamente, resultó estar en **Canadá**:
  - `curl ipinfo.io` desde el propio servidor: IP `51.161.124.237`, **AS16276 OVH SAS, Beauharnois (Quebec)**.
  - Registro de la IP en **ARIN** (Norteamérica), no en LACNIC.
  - `ping` desde Quito: **111 ms** mínimo. Un servidor en Ecuador responde en menos de 15 ms.
  - `tracert`: la ruta sale del país en el salto 7 (de 7 a 70 ms) y termina en rangos de OVH Canadá.
- Por eso se reemplazó por un VPS **TPX11 de Telecu Cloud** con geolocalización Ecuador, y se repitieron las mismas pruebas:
  - `curl ipinfo.io`: IP `205.235.2.2`, **AS23246 GIGAIPNET** (la red propia de Telecu), **Guayaquil, Ecuador**.
  - `ping` desde Quito: **13 ms** mínimo (17 ms de promedio), frente a 111 ms del VPS de prueba en Canadá.
  - `tracert`: 10 saltos, todos dentro de redes ecuatorianas, sin salida internacional.
- Es decir, **la etiqueta «servidor ecuatoriano» no garantiza que los datos queden en Ecuador**: hay que comprobarlo. Si los datos personales se procesan fuera del país, para la LOPDP es una **transferencia internacional**, con las obligaciones descritas arriba.
- Por eso, en el clúster el filtro **Opciones → Soberanía de datos** usa el país donde está **físicamente** el servidor, no la nacionalidad del proveedor. La lista ofrece solo los países reales («Solo servidores en Canadá», «Solo servidores en Alemania»…), y el líder reparte los fragmentos únicamente a esas nubes, con resultado idéntico.
- **Lección para la institución:** exigir en el contrato la **ubicación física** del centro de datos y verificarla técnicamente (IP, sistema autónomo, latencia), no solo la razón social del proveedor.

---

## Pregunta 3: Estructura de costos, transferencia de datos (egress) y modelo financiero

| Modelo | Cómo cobra | Precio de salida de datos (egress) a internet | Riesgo al escalar |
|---|---|---|---|
| **Hiperescalares de EE. UU. (AWS/Azure)** | Pago por uso, por segundo u hora | AWS: 100 GB/mes gratis, luego **US$ 0.09/GB** (primeros 10 TB). Azure: 100 GB gratis, luego **US$ 0.087/GB** | El egress crece en proporción al tráfico. Se suman costos menos visibles: tráfico entre zonas, NAT gateway, IP públicas, CDN y soporte |
| **Hiperescalares asiáticos (Alibaba/Tencent)** | Pago por uso, con precios agresivos | Alibaba (fuera de China continental): **200 GB/mes gratis**, luego unos **0.50 CNY/GB** en Norteamérica y Europa, y **0.78 CNY/GB** en Sudamérica | Más barato en egress, pero con riesgo regulatorio, menor presencia en la región (más latencia) y facturación en otra moneda |
| **VPS local de tarifa fija (Telconet/Netlife)** | Mensualidad fija | Normalmente incluido, pero con **ancho de banda limitado (Mbps)** | El costo es predecible, pero **no escala de forma elástica**: en un pico, el enlace se satura en lugar de facturar más. Crecer exige cambiar de plan o firmar contratos |

**Ejemplo con 50 TB al mes de video saliente (precios de lista):**
- AWS: 100 GB gratis, 10 TB a US$ 0.09 y unos 39.9 TB a US$ 0.085. Total: **≈ US$ 4 395 al mes**, solo en egress.
- Azure: **≈ US$ 4 280 al mes**.
- Un VPS local de tarifa fija no tendría ese costo variable, pero tendría que sostener unos 150 Mbps de promedio, con picos mucho mayores. Lo más probable es que el enlace no lo soporte.

**Riesgos de sobrecosto oculto:**
1. El **egress**, que crece con el éxito de la aplicación.
2. El **tráfico entre zonas y regiones**, por la redundancia.
3. Los recursos olvidados encendidos (VMs, discos, IP).
4. La conversión de moneda en proveedores asiáticos.
5. Los planes de soporte empresariales.
6. El "impuesto de salida" (exit fee) si se quiere migrar todo el contenido a otro proveedor.

**Recomendación:**
- Servir la multimedia con una **CDN**, que tiene precio por GB menor y caché.
- Poner **alertas de presupuesto**.
- Usar la tarifa fija local como base y el pago por uso solo para los picos (cloud bursting).

📏 **Evidencia del proyecto:**
- Cada nube descarga el genoma **una sola vez** (el ingreso de datos es gratuito en los hiperescalares).
- Durante el análisis, por la red solo viaja la orden *{archivo, offset, longitud}* y un JSON de pocos KB por fragmento. Analizar 6.7 GB genera un egress casi nulo.
- La pestaña **Costo por transacción** calcula, para cada nube, la tarifa por hora, la cuota mensual prorrateada (mes ÷ 730 h), el costo del análisis, el costo por cada 1 000 análisis y el costo por GB procesado.
- Ahí se ve el contraste de la pregunta: AWS, Alibaba y OVH cobran **por uso**, mientras que DonWeb y Telecu son VPS de **tarifa fija mensual**.

---

## Pregunta 4: Capacidad de cómputo especializado para IA y Big Data

| Criterio | Proveedores de EE. UU. (Google Vertex AI / AWS SageMaker) | Proveedores asiáticos (Huawei ModelArts / Alibaba) |
|---|---|---|
| **Aceleradores** | GPU NVIDIA de última generación, **TPU** (Google) y **Trainium/Inferentia** (AWS) | Huawei: NPU **Ascend** (ModelArts, framework MindSpore). En 2026, Huawei evalúa llevar sus chips Ascend a su nube en Latinoamérica, sin fecha confirmada. Los controles de exportación de EE. UU. limitan su acceso a las GPU NVIDIA más avanzadas |
| **Flexibilidad PaaS/FaaS** | MLOps completo: entrenamiento administrado, endpoints serverless, *pipelines*, *feature store*. Funciones con Cloud Run Functions y Lambda | ModelArts cubre entrenamiento, despliegue y MLOps. FaaS con FunctionGraph (Huawei) y Function Compute (Alibaba). En Alibaba, la plataforma de IA es **PAI**; **ApsaraDB** es la familia de **bases de datos**, útil para Big Data pero no para entrenar modelos |
| **Madurez del ecosistema** | Muy alta: soporte nativo de PyTorch, TensorFlow y JAX, gran comunidad, documentación e integraciones | En crecimiento. Usar Ascend puede requerir adaptar el código (CANN/MindSpore), con menos ejemplos y comunidad fuera de China |
| **Regiones cercanas a Ecuador** | Varias en EE. UU. y São Paulo | Huawei tiene regiones en Santiago, Ciudad de México y São Paulo |

**Conclusión:**
- Para *deep learning* a gran escala hoy, los proveedores de EE. UU. ofrecen el ecosistema **más maduro y flexible**.
- Los asiáticos compiten en **precio** y en presencia regional (Huawei es el tercer proveedor en Latinoamérica), pero con **mayor riesgo de dependencia tecnológica** (código atado a Ascend/CANN) y de restricciones geopolíticas.
- En todos los casos, el acelerador **reduce la portabilidad**: el código CUDA no corre sin cambios en una NPU Ascend.

📏 **Evidencia del proyecto:** nuestra carga es de **CPU pura** (Python + numpy), y por eso la misma imagen corre en las 5 nubes y en dos arquitecturas (amd64 y arm64). Con IA esa portabilidad se pierde si el código depende de un acelerador concreto. Es la diferencia entre la **portabilidad del contenedor** y la **portabilidad del hardware**.

---

## Pregunta 5: Estrategia multinube y mitigación del vendor lock-in

**Complejidad operativa de orquestar entre plataformas multinacionales (Azure, IBM Cloud) e integradores regionales (Sonda Ecuador, Movistar Empresas):**

- **Interoperabilidad de APIs:**
  - Cada nube tiene su propia API de cómputo, redes, identidades (IAM), almacenamiento y monitoreo.
  - Los multinacionales ofrecen capas de gestión híbrida (Azure Arc, IBM Cloud Satellite sobre Red Hat OpenShift), pero cada una funciona mejor dentro de su propio ecosistema.
  - Los integradores regionales suelen ofrecer VMware, OpenStack o servicios administrados con APIs menos estandarizadas.
- **Gobernanza:**
  - Hay que unificar identidades, políticas de seguridad, registros (logs), etiquetado, auditoría y cumplimiento (LOPDP) en proveedores con modelos de permisos distintos.
  - Sin una capa común, cada equipo termina gobernando una nube distinta.
- **Duplicación de costos:**
  - Se pagan dos o más contratos de soporte, herramientas, capacitación y personal especializado.
  - Se paga egress **entre nubes** y se pierden descuentos por volumen al repartir el gasto.
  - La multinube elimina el lock-in a cambio de **más costo operativo**.
- **Cómo se mitiga:**
  - **Contenedores** + Kubernetes (estándar CNCF).
  - Infraestructura como código (Terraform/Ansible).
  - Usar servicios basados en estándares abiertos (S3-compatible, PostgreSQL) en lugar de servicios propietarios.
  - Observabilidad centralizada.
  - Separar los datos según su sensibilidad.

📏 **Evidencia del proyecto (y lo que aprendimos en la práctica):**
- **Lo que funcionó:** una sola imagen, el mismo código y solo variables de entorno distintas (`NODE_NAME`, país, costo) en las 5 nubes. La **migración en vivo** (`docker save | gzip | ssh | docker load`) mueve la aplicación sin reescribirla, y el resultado es idéntico en todas.
- **Dónde aparece el lock-in real**, aun con contenedores:
  - En la **gestión de cuentas**: Magalu Cloud no permitió activar la cuenta sin un documento brasileño.
  - En la **verificación de identidad**: Alibaba Cloud bloqueó la creación de la VM («Your account is at risk») hasta validar pasaporte o licencia, con unos 3 días hábiles de revisión. Se reemplazó por **Huawei Cloud**, también china, sin cambiar una línea de código.
  - En la **activación**: AWS retuvo la cuenta hasta verificar la tarjeta, y OVHcloud deja el proyecto en «modo Discovery» hasta validar un medio de pago.
  - En la **ubicación real**: un VPS de prueba presentado como «ecuatoriano» estaba en un centro de datos de OVH en Canadá; se detectó con ping, traceroute y el registro de la IP, y se reemplazó por Telecu (Ecuador).
  - En el **acceso**: DonWeb usa SSH en otro puerto, y cada nube tiene su propio usuario, firewall y grupo de seguridad (hubo que abrir UDP 51820 en las 5 para WireGuard).
  - En el **tipo de VPS**: algunos VPS mensuales no permiten módulos del kernel, y por eso WireGuard necesita una variante en espacio de usuario.
  - En los **precios y la facturación**, que son diferentes en cada proveedor.
- Es exactamente la complejidad operativa que plantea la pregunta.
- **Cómo la mitigamos:** una capa común propia, que **no pertenece a ningún proveedor**: etcd (coordinación), WireGuard (red privada) y contenedores. Así el clúster funciona igual sobre AWS, Huawei, OVH, DonWeb y Telecu, y cualquier nube se puede reemplazar sin cambiar el código.

---

## Pregunta 6: Almacenamiento masivo (STaaS) y redundancia geográfica

**STaaS global (AWS S3 / Google Cloud Storage):**
- S3 Standard está diseñado para una durabilidad de **99.999999999 % ("11 nueves")**, porque guarda cada objeto de forma redundante en **al menos 3 zonas de disponibilidad**. GCS ofrece la misma durabilidad.
- Escala a petabytes sin planificar capacidad, con clases frías (Glacier/Archive) más baratas.
- **Contras para Ecuador:**
  - La recuperación cruza el enlace internacional, así que tiene alta latencia (decenas de ms por petición).
  - Cada descarga paga **egress**.
  - Los datos quedan fuera del país (ver pregunta 2).

**Almacenamiento privado local (Internexa / Telconet):**
- Tiene **baja latencia** dentro de Ecuador y no hay egress internacional.
- Mantiene la soberanía.
- Pero su durabilidad depende de **cuántas copias y en cuántos sitios** se repliquen los datos. Con un solo DC, un incendio o una falla regional puede causar la pérdida total. Llegar a "11 nueves" exige replicar en varios sitios geográficamente separados, y eso tiene un costo alto.

**El trade-off:**
- La durabilidad distribuida globalmente se consigue **alejando las copias**: más sitios y más distancia significan más durabilidad, pero también más latencia de recuperación y más costo de transferencia.
- La latencia local se consigue **acercando los datos**: es rápida, pero con menos redundancia geográfica.
- **La práctica recomendada para streaming es por capas:**
  - el catálogo "caliente" se sirve desde caché o almacenamiento local o una CDN cerca del usuario;
  - la copia maestra va en STaaS global con varias zonas (y una clase fría para lo antiguo);
  - se sigue la regla **3-2-1**: 3 copias, 2 medios distintos, 1 fuera del sitio.

📏 **Evidencia del proyecto:** cada nube calcula el **SHA-256** del archivo (el genoma de 3.1 GB) y el dashboard comprueba que todas tengan **la misma huella**. Es la misma idea con la que los servicios de almacenamiento verifican la integridad de cada copia: la durabilidad no solo consiste en guardar copias, sino en **verificar** que sean idénticas.

---

## Pregunta 7: Servicios de borde (Edge Computing), 5G e IoT

**Proveedores asiáticos (KT Cloud / Huawei Cloud):**
- Huawei tiene la plataforma más integrada: **Intelligent EdgeFabric (IEF)** lleva las aplicaciones en contenedor de la nube a nodos de borde y las gestiona centralmente (se basa en KubeEdge, de código abierto). Huawei además fabrica equipos 5G y soluciones MEC (*Multi-access Edge Computing*).
- KT Cloud (Corea) opera MEC sobre su propia red 5G.
- **Limitación:** son plataformas maduras, pero **sin infraestructura de borde propia en Ecuador**. El nodo de borde sería hardware local gestionado desde una región lejana, con dependencia del enlace internacional para la orquestación.

**Infraestructura regional sudamericana (Internexa / Claro Cloud):**
- Internexa aporta **red de transporte** de fibra entre países de la región.
- Claro tiene **red 5G en Ecuador** y data centers locales TIER III.
- En Ecuador, **CNT EP fue la primera operadora en activar 5G** y luego se sumaron Claro y Movistar (hoy de Tigo/Millicom). A fines de 2025 había 233 radiobases 5G, y la meta oficial era tener cobertura nacional a mediados de 2026.
- La ventaja es la **proximidad física**: el procesamiento queda a pocos km de los sensores, con latencia de un dígito en ms.
- La desventaja es una plataforma de software de borde menos madura que la de Huawei.

**Recomendación:**
- Usar una arquitectura de **tres niveles**: sensores, borde local (MEC del operador 5G o un nodo en Quito) y nube central.
- En el borde se **filtra y se decide** de inmediato (alarmas, control). A la nube central solo se envían **agregados**, lo que reduce la latencia, el ancho de banda y el egress.
- Para no quedar atados a un proveedor, conviene orquestar el borde con estándares abiertos (Kubernetes/KubeEdge) y **contenedores multiarquitectura**, porque muchos equipos de borde son ARM.

📏 **Evidencia del proyecto:**
- La nube `ecuador` (Telecu, en Ecuador) cumple el papel de **nodo de borde**: es la más cercana a los usuarios del país y puede procesar sin sacar los datos (opción de soberanía). El VPS de prueba que estaba en Canadá **no habría servido** como borde: el borde tiene que estar físicamente cerca.
- La imagen se publica para **amd64 y arm64**, así que puede correr en un servidor x86 o en un dispositivo de borde ARM.
- El worker solo devuelve un **resumen** (conteos, en KB), no los datos crudos. Es el mismo patrón que el borde aplica con los datos de los sensores.

---

## Pregunta 8: SLA, disponibilidad y red internacional

**El riesgo:**
- Ecuador sale a internet por **pocos cables submarinos**: PAN-AM (el primero, de 1999), PCCS (Pacific Caribbean Cable System, del que Telconet es cofundador), Mistral (Claro/Telxius, de 2021) y el de Cable Andino en Manta. Telconet construye además el CSN-1 hacia Florida, previsto para 2026.
- Como son pocos y aterrizan en pocos puntos (Manta y Punta Carnero, en Salinas), el riesgo está **concentrado**. Las disputas regulatorias sobre estos cables ya han llevado a la prensa a preguntarse si el país "podría quedarse sin internet".
- Si se corta el tráfico internacional, una solución **100 % en nubes públicas globales** queda **inaccesible**: el SLA del 99.9 % del proveedor no sirve si el usuario no puede llegar a él. Ese SLA cubre el servicio dentro de la nube, no el cable.

**Cómo la nube híbrida local garantiza la continuidad:**
1. Las cargas **críticas** (pagos, autorizaciones, servicios ciudadanos) corren en un DC local TIER III (Telconet, Sonda o similar), con réplica en un segundo DC nacional.
2. El tráfico nacional se intercambia **dentro del país** a través del punto de intercambio nacional (NAP.EC), así que no depende de los cables.
3. La nube pública se usa para analítica, picos de demanda y respaldo. Los datos se sincronizan cuando el enlace vuelve (consistencia eventual).
4. Se aplica un plan de continuidad (BCP/DRP) con objetivos de tiempo y de pérdida de datos (RTO/RPO) definidos y **pruebas periódicas** de conmutación.
5. Se contratan enlaces internacionales de **dos operadores distintos**, por cables distintos.

📏 **Evidencia del proyecto:** el clúster no tiene un punto único de falla:
- **etcd** replica el estado en 5 nubes con Raft y sigue funcionando aunque caigan 2.
- Si una nube que calcula falla, sus fragmentos **se reasignan** a las demás.
- Si cae **la nube líder**, su *lease* en etcd expira y otra nube **toma el mando sola** y **retoma el trabajo** desde el último fragmento guardado.
- Si quedan pocas nubes, el líder sigue calculando con las que respondan. Con "Solo nubes en Ecuador", el trabajo continúa dentro del país, que es el principio de la nube híbrida local.
- En las pruebas, el proceso líder cayó con 25 de 104 fragmentos hechos y otra nube retomó el trabajo en unos 11 s. Con 2 de 5 nubes caídas, el resultado siguió siendo **idéntico** al cálculo de referencia con 1 núcleo.
- La **Línea de tiempo** del dashboard muestra la pausa y la marca del nuevo líder. 📏 Repite la prueba en las nubes reales con `bash scripts/cluster/nube.sh apagar usa` durante un análisis y anota el tiempo de recuperación medido.

---

## Cómo demostrar cada respuesta en la defensa

| Pregunta | Qué mostrar en el dashboard (sección Clúster) |
|---|---|
| 1 Latencia | **Medir red** y pestaña **Red entre nubes**: la fila ECUADOR, con los valores menores a 15 ms marcados con ✓ |
| 2 Soberanía | La verificación de ubicación (ping, traceroute, ipinfo) y **Opciones → Soberanía de datos → Solo servidores en Ecuador**, que filtra por ubicación física |
| 3 Costos | Pestaña **Costo por transacción**: USD/h, USD/mes, costo por análisis, por 1 000 análisis y por GB |
| 4 IA | Tarjetas de las nubes: potencia en GFLOPS, «GPU: no tiene», CPU y núcleos |
| 5 Multinube | La misma imagen en 5 nubes, `migrar_imagen.sh` (migración en vivo) y **Ceder mando** entre nubes de distintos proveedores |
| 6 Almacenamiento | Pestaña **Datos en las nubes**: las 5 copias con el mismo SHA-256 |
| 7 Borde | La nube ECUADOR (Telecu) y la imagen amd64 y arm64 |
| 8 Continuidad | `nube.sh apagar usa` durante un análisis: otra nube toma el mando y retoma el trabajo (pestañas **Línea de tiempo** y **Eventos**) |

---

## Fuentes

- Telconet, data center TIER III en Quito: [DCD](https://www.datacenterdynamics.com/es/noticias/el-data-center-de-telconet-en-quito-consigue-la-certificaci%C3%B3n-tier-iii/)
- Claro Ecuador, TIER III del Uptime Institute (Quito y Durán, 2021): [DPL News](https://dplnews.com/?p=97644)
- Norma SPDP-SPD-2026-0004-R sobre transferencias internacionales: [NMS Law](https://nmslaw.com.ec/blog/2026/02/02/spdp-transferencias-comunicaciones-datos-personales-ecuador-internacionales/)
- CLOUD Act (2018): [Orrick, «The CLOUD Act, Explained»](https://www.orrick.com/en/Insights/2018/04/The-CLOUD-Act-Explained)
- OVHcloud y SecNumCloud (SNC Cloud Platform, 2026): [OVHcloud Newsroom](https://corporate.ovhcloud.com/en/newsroom/news/ovhcloud-obtains-secnumcloud-qualification-snc-cloud-platform/)
- Precios de OVHcloud Public Cloud y tráfico incluido: [OVHcloud](https://www.ovhcloud.com/en/public-cloud/prices/?currency=USD)
- Egress de AWS, Azure y GCP: [American Cloud](https://americancloud.com/blog/egress-fees-explained)
- Tráfico de internet de Alibaba Cloud (200 GB gratis, precio por GB): [Alibaba Cloud CDT](https://help.aliyun.com/en/cdt/internet-data-transfers/)
- Durabilidad de S3 (11 nueves, varias zonas): [AWS S3 Storage Classes](https://aws.amazon.com/s3/storage-classes/)
- Huawei y los chips Ascend en Latinoamérica: [SCMP](https://www.scmp.com/news/china/article/3356967/huawei-considering-deploying-ascend-ai-chips-latin-america-cloud-chief-says)
- Huawei Cloud, tercer proveedor en Latinoamérica: [DPL News](https://dplnews.com/?p=311041)
- Intelligent EdgeFabric (IEF): [Huawei Cloud](https://support.huaweicloud.com/intl/en-us/productdesc-ief/ief_productdesc_0001.html)
- 5G en Ecuador (2026): [TeleSemana](https://www.telesemana.com/blog/2026/04/30/ecuador-acelera-el-5g-y-supera-metas-tras-renegociar-concesiones/)
- Cables submarinos de Ecuador: [Primicias](https://primicias.ec/noticias/tecnologia/cables-submarinos-internet-telconet-ecuador), [Capacity (CSN-1, PCCS)](https://capacityglobal.com/news/2026-submarine-carnival-looms-into-view-in-the-americas/)
- Riesgo de conectividad internacional (conflicto Telconet–Gobierno, 2024): [Vistazo](https://www.vistazo.com/actualidad/nacional/2024-11-30-conflicto-telconet-gobierno-podria-ecuador-quedarse-sin-internet-BE8402542)
