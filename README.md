# ESP32-WROOM-32

Placa ESP32 conectada por USB (puente CP2102). Aquí está su ficha, el respaldo
del firmware de fábrica y los scripts para trabajar con ella.

## Ficha del dispositivo

| Dato | Valor |
|---|---|
| Módulo | ESP32-WROOM-32 |
| Chip | ESP32-D0WD-V3, revisión v3.1, doble núcleo, 240 MHz |
| Radio | Wi-Fi + Bluetooth |
| Cristal | 40 MHz |
| MAC | `xx:xx:xx:xx:xx:xx` |
| Flash | 4 MB (fabricante `0x68`, dispositivo `0x4016`), 3.3 V, DIO, 40 MHz |
| USB-serie | Silicon Labs CP2102 (VID `0x10C4`, PID `0xEA60`) |
| Puerto | `/dev/cu.usbserial-0001`, 115200 baudios |
| Firmware de fábrica | ESP-AT 2.4.0 (bootloader ESP-IDF `qa-test-v4.3.3-20220423`) |

Seguridad (eFuses): sin cifrado de flash, sin Secure Boot, JTAG y descarga por
UART habilitados, eFuses sin protección de escritura. Se puede flashear libremente.

Con ESP-AT, los comandos AT **no** van por el USB: se atienden en UART1
(GPIO16 = RX, GPIO17 = TX). El USB (UART0) solo muestra el log de arranque.

### Tabla de particiones de fábrica

| Partición | Offset | Tamaño |
|---|---|---|
| `phy_init` | `0x00F000` | 4 KB |
| `otadata` | `0x010000` | 8 KB |
| `nvs` | `0x012000` | 56 KB |
| `at_customize` | `0x020000` | 896 KB |
| `ota_0` | `0x100000` | 1.5 MB |
| `ota_1` | `0x280000` | 1.5 MB |

## Sitio web (estado actual de la placa)

La placa corre **MicroPython v1.29.0** y sirve una página estática en
`http://esp32-panel.local/` (Wi-Fi de `device/config.py`, solo 2.4 GHz).

Flujo de publicación:

1. La página se edita en **Stronglify** (tema `ESP`, sitio `tudominio.com`).
2. Al publicar, Stronglify hace push de `index.html` a la raíz de `4cceleration/ESP`.
3. La placa consulta GitHub cada 5 minutos; si hay un commit nuevo descarga
   `index.html` comprimido y lo empieza a servir, sin reiniciarse.

Los push al repositorio se hacen solo desde Stronglify.

`device/main.py` está escrito para gastar poca RAM: página guardada en gzip, un
único búfer de 1 KB, cabeceras constantes, límites por petición (2 KB, 4 s,
4 conexiones), solo GET/HEAD con rutas fijas y un vigilante que recoge basura y
reinicia la placa si la memoria baja de 24 KB. `GET /api/status` devuelve memoria
libre, mínimo histórico, peticiones y versión servida.

```sh
scripts/esp.sh upload     # sube config.py, main.py y la página local; muestra el log
scripts/esp.sh preview    # vista previa de site/index.html en http://localhost:8032/
scripts/esp.sh repl       # consola MicroPython
```

Para volver al firmware de fábrica (ESP-AT): `scripts/esp.sh restore`.

## Estructura

```
backup/   factory-esp-at-2.4.0-4MB.bin  volcado completo del flash de fábrica + SHA256SUMS
docs/     chip-info.txt, efuses.txt, boot-log.txt  salidas originales de las lecturas
scripts/  esp.sh (atajos), monitor.py (monitor serie sin dependencias)
device/   main.py (servidor), config.py (Wi-Fi y repo; privado)
site/     index.html (copia local de la página publicada)
```

## Uso

`esptool` está instalado en un entorno aparte: `~/.venvs/esptool`.

```sh
scripts/esp.sh info          # chip, MAC e ID del flash
scripts/esp.sh efuses        # resumen de eFuses
scripts/esp.sh monitor 10    # reinicia la placa y muestra 10 s de log serie
scripts/esp.sh backup        # nuevo volcado del flash en backup/
scripts/esp.sh restore       # vuelve a grabar el firmware de fábrica (pide confirmación)
scripts/esp.sh erase         # borra todo el flash (pide confirmación)
```

Variables opcionales: `ESP_PORT` (otro puerto) y `ESP_BAUD` (por defecto 230400;
a 460800 la lectura falló con este cable).

Para verificar el respaldo: `cd backup && shasum -a 256 -c SHA256SUMS`.

## Notas

- El auto-reset funciona: no hace falta pulsar BOOT para flashear.
- El monitor serie reinicia la placa al abrirse (línea RTS → EN).
- `get-security-info` no existe en el ESP32 clásico; la seguridad se consulta con `efuses`.
