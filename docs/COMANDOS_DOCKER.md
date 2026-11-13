# Comandos Docker del proyecto (para la defensa)

Cada comando está explicado con un ejemplo real de este proyecto.

| Comando | Qué hace | Ejemplo en el proyecto |
|---|---|---|
| `docker build` | Construye una **imagen** a partir del `Dockerfile`, capa por capa (con caché) | `docker build -t adn-multicloud:latest .` |
| `docker images` | Lista las imágenes locales y su tamaño | `docker images adn-multicloud` |
| `docker run` | Crea **y arranca** un contenedor a partir de una imagen | ver abajo |
| `docker ps` | Lista los contenedores en ejecución (`-a` incluye los detenidos) | `sudo docker ps -a` |
| `docker stop` | Detiene un contenedor (le envía SIGTERM y luego SIGKILL) | `sudo docker stop adn-worker` |
| `docker start` | Vuelve a arrancar un contenedor detenido, con la misma configuración | `sudo docker start adn-worker` |
| `docker restart` | stop + start | `sudo docker restart adn-worker` |
| `docker rm` | Borra un contenedor (`-f` lo detiene antes) | `sudo docker rm -f adn-worker` |
| `docker rmi` | Borra una **imagen**, que no debe estar en uso | `sudo docker rmi adn-multicloud:latest` |
| `docker logs` | Muestra la salida del contenedor (`-f` la sigue en vivo) | `sudo docker logs -f adn-worker` |
| `docker exec` | Ejecuta un comando **dentro** de un contenedor en marcha | `sudo docker exec -it adn-worker bash` |
| `docker stats` | Muestra el uso de CPU, RAM y red de cada contenedor en vivo | `sudo docker stats adn-worker` |
| `docker inspect` | Muestra toda la configuración (variables, puertos, volúmenes) | `sudo docker inspect adn-worker \| grep CLUSTER_TOKEN` |
| `docker save` | Exporta una imagen a un archivo `.tar` | `docker save adn-multicloud:latest \| gzip > adn.tar.gz` |
| `docker load` | Importa una imagen desde un `.tar` | `gunzip -c adn.tar.gz \| sudo docker load` |
| `docker pull` / `push` | Descarga o sube una imagen a un registro | `docker pull ghcr.io/usuario/adn-multicloud:latest` |
| `docker compose` | Levanta varios servicios definidos en `docker-compose.yml` | `docker compose --profile ui up -d dashboard` |

## El `docker run` del worker, línea por línea

```bash
sudo docker run -d \                     # -d: en segundo plano (detached)
  --name adn-worker \                    # nombre fijo para stop/start/logs
  --restart unless-stopped \             # se levanta solo si la VM se reinicia
  -p 8000:8000 \                         # puerto del host : puerto del contenedor
  --env-file nodo.env \                  # proveedor, país, región, costo/hora
  -e APP_MODE=worker \                   # la misma imagen actúa como worker
  -e NODE_NAME=nodo-europa \             # lo ÚNICO que cambia entre nubes
  -e CLUSTER_TOKEN='clave' \             # clave compartida (no va en el código)
  ghcr.io/usuario/adn-multicloud:latest
```

## Migración en vivo, explicada

```bash
docker save adn-multicloud:latest | gzip -1 | ssh nodo-europa "gunzip | sudo docker load"
```

1. `docker save` escribe la imagen completa (todas sus capas) a la salida estándar.
2. `gzip -1` la comprime rápido para enviar menos bytes por internet.
3. `ssh nodo-europa "..."` envía ese flujo cifrado a la VM de Europa.
4. En la VM, `gunzip` la descomprime y `docker load` la registra como imagen local.
5. Luego `instalar_nodo.sh` ejecuta `docker run` con esa misma imagen.

**No se reescribe ni se recompila nada**: es el mismo artefacto, y en eso consiste la portabilidad.

## Imagen vs. contenedor

- **Imagen:** la plantilla inmutable (el "molde"). Es una y la misma en las 5 nubes.
- **Contenedor:** una instancia en ejecución de la imagen (la "pieza"). Hay uno por nube, con sus propias variables de entorno.
