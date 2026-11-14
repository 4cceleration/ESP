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

## Panel web (estado actual de la placa)

La placa corre **MicroPython v1.29.0** con un panel web propio (`device/`):
estado en vivo (tiempo encendida, temperatura, memoria, señal Wi-Fi) y un
interruptor para el LED integrado.

- `device/main.py`: servidor HTTP (`/`, `/api/status`, `POST /api/led`).
- `device/www/index.html`: la página.
- `device/config.py`: Wi-Fi y red propia. Contiene contraseñas; no compartir.

Se conecta al Wi-Fi de `config.py` (solo 2.4 GHz) y queda en
`http://esp32-panel.local/`. Si no hay Wi-Fi configurado o no conecta, crea la
red `ESP32-Panel` (clave `AP_PASSWORD` de `config.py`) y sirve en `http://192.168.4.1/`.

```sh
scripts/esp.sh upload     # sube config.py, main.py y www/ y muestra el log con la IP
scripts/esp.sh preview    # vista previa en el computador con datos simulados
scripts/esp.sh repl       # consola MicroPython
```

El panel no tiene contraseña: cualquiera en la misma red puede verlo y mover el LED.

Para volver al firmware de fábrica (ESP-AT): `scripts/esp.sh restore`.

## Estructura

```
backup/   factory-esp-at-2.4.0-4MB.bin  volcado completo del flash de fábrica + SHA256SUMS
docs/     chip-info.txt, efuses.txt, boot-log.txt  salidas originales de las lecturas
scripts/  esp.sh (atajos), monitor.py (monitor serie sin dependencias)
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
