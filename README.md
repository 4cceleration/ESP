# ESP — un sitio web servido desde un ESP32

Este repositorio es un sitio web que **vive en un microcontrolador ESP32**: la
página se diseña en [Stronglify](https://app.stronglify.com), Stronglify la publica
aquí con un push, la placa la descarga sola y la sirve a internet a través de un
relevo en Cloudflare.

**Sitio en vivo:** https://esp.4cceleration.workers.dev

La página tiene un fondo ASCII animado y un botón rojo: al presionarlo, desde
cualquier lugar del mundo, titila el LED de la placa.

## Cómo funciona

```
 Stronglify ──push──▶ GitHub (este repo) ◀──consulta cada 5 min── ESP32
 (tema "ESP")          index.html                                   │
                                                                    │ WebSocket saliente
 Visitante ──https──▶ Cloudflare Worker (relay/) ◀──────────────────┘
```

1. **Stronglify** genera `index.html` (y `sitemap.xml`) y hace push a la raíz de
   este repositorio. Todos los cambios de la página se hacen allí, no a mano.
2. **La placa** pregunta a GitHub cada 5 minutos cuál es el último commit. Si
   cambió, descarga `index.html` ya comprimido en gzip, lo guarda en su flash y lo
   empieza a servir sin reiniciarse.
3. **El relevo** es un Cloudflare Worker con un Durable Object. La placa abre hacia
   él una conexión WebSocket saliente y la deja abierta; así no hay que abrir
   puertos en el router ni exponer la red de casa. Cuando alguien visita el sitio,
   el Worker le pide la página a la placa por esa conexión y la guarda un minuto.
4. **El botón rojo** hace `POST /api/blink`. El Worker le pasa la orden a la placa
   por el WebSocket y la placa hace titilar su LED.

La placa solo necesita corriente y Wi-Fi: no depende de ningún computador. Si se
desconecta, el Worker sigue entregando la última copia de la página, pero el botón
rojo deja de responder. Al volver a darle corriente se reengancha sola en unos
segundos.

## Qué hay en el repositorio

| Ruta | Qué es |
|---|---|
| `index.html`, `sitemap.xml` | El sitio, generado y publicado por Stronglify. No editar a mano. |
| `device/main.py` | Servidor web de la placa (MicroPython). |
| `device/config.example.py` | Plantilla de configuración. La real (`config.py`) no se sube: lleva contraseñas. |
| `relay/` | Cloudflare Worker que conecta internet con la placa. |
| `scripts/esp.sh` | Atajos: subir a la placa, monitor serie, respaldo y restauración del flash. |
| `scripts/monitor.py` | Monitor serie sin dependencias. |

## La placa

| Dato | Valor |
|---|---|
| Módulo | ESP32-WROOM-32 (chip ESP32-D0WD-V3, doble núcleo, 240 MHz) |
| Flash / RAM | 4 MB de flash, unos 120 KB de RAM libres con MicroPython |
| Conexión | Wi-Fi de 2.4 GHz; USB-serie CP2102 a 115200 baudios |
| Firmware | MicroPython v1.29.0 (`ESP32_GENERIC`) |

### El servidor (`device/main.py`)

Está escrito para gastar la menor memoria posible:

- La página se guarda comprimida (`www/index.html.gz`) y se envía tal cual.
- Un único búfer de 1 KB, reservado al arrancar, sirve todos los envíos.
- Las cabeceras de respuesta son constantes; no se construyen en cada petición.
- Límites por petición: 2 KB de cabeceras, 4 s de espera, 4 conexiones a la vez.
- Rutas fijas: lo que pide el cliente nunca toca el sistema de archivos.
- Un vigilante recoge basura cada 10 s y reinicia la placa si quedan menos de 24 KB.

Rutas que atiende:

| Ruta | Respuesta |
|---|---|
| `GET /` | La página (gzip, con `ETag` y 304 si no cambió). |
| `GET /api/status` | Memoria libre, mínimo histórico, peticiones y commit servido. |
| `POST /api/blink` | Hace titilar el LED unos dos segundos. |

Con el relevo conectado quedan unos 80 KB de RAM libres.

### Puesta en marcha

```sh
# 1. Herramientas (una sola vez)
python3 -m venv ~/.venvs/esptool
~/.venvs/esptool/bin/pip install esptool mpremote

# 2. Grabar MicroPython (borra lo que tenga la placa)
~/.venvs/esptool/bin/esptool --port /dev/cu.usbserial-0001 erase-flash
~/.venvs/esptool/bin/esptool --port /dev/cu.usbserial-0001 --baud 230400 \
    write-flash 0x1000 ESP32_GENERIC-20260824-v1.29.0.bin

# 3. Configurar y subir
cp device/config.example.py device/config.py   # poner Wi-Fi, repo y relevo
scripts/esp.sh upload                          # sube todo y muestra el log con la IP
```

Otros atajos: `scripts/esp.sh monitor`, `repl`, `info`, `efuses`, `backup`,
`restore` y `erase` (los dos últimos piden confirmación).

## El relevo (`relay/`)

```sh
cd relay
npm install
npx wrangler deploy
npx wrangler secret put BOARD_KEY   # la misma clave que RELAY_KEY en device/config.py
```

- `GET /` entrega la página que envió la placa (se refresca como mucho cada 60 s).
- `POST /api/blink` reenvía la orden de titilar (máximo una por segundo).
- `GET /_status` dice si la placa está conectada y la edad de la copia guardada.
- `/_board` es la entrada WebSocket de la placa; exige la clave `BOARD_KEY`.

## Límites conocidos

- La placa no valida los certificados TLS al hablar con GitHub ni con el relevo
  (MicroPython no trae autoridades certificadoras). Por eso la actualización
  automática solo reemplaza el HTML, nunca el código de la placa.
- El sitio no tiene contraseña: cualquiera con el enlace puede hacer titilar el LED.
- La placa atiende pocas conexiones a la vez; el relevo absorbe el tráfico.
- Un cambio publicado tarda hasta 6 minutos en verse (5 de la consulta a GitHub
  más 1 de la copia del relevo).
