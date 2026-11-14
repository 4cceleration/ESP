#!/bin/zsh
# Atajos para trabajar con el ESP32 conectado por USB (CP2102).
# Uso: scripts/esp.sh <info|efuses|monitor|backup|restore|erase> [args]
set -e

ROOT="${0:A:h:h}"
BIN="$HOME/.venvs/esptool/bin"
PORT="${ESP_PORT:-/dev/cu.usbserial-0001}"
BAUD="${ESP_BAUD:-230400}"   # 460800 falla con este cable/placa

if [[ ! -e "$PORT" ]]; then
  echo "No encuentro $PORT. ¿Está conectada la placa? Puertos disponibles:" >&2
  ls /dev/cu.usbserial* 2>/dev/null >&2 || echo "  (ninguno)" >&2
  exit 1
fi

case "$1" in
  info)
    "$BIN/esptool" --port "$PORT" flash-id
    ;;
  efuses)
    "$BIN/espefuse" --port "$PORT" summary
    ;;
  monitor)
    # Reinicia la placa y muestra el log serie durante N segundos (por defecto 10).
    python3 -I "$ROOT/scripts/monitor.py" 115200 reset "${2:-10}"
    ;;
  upload)
    # Sube el panel (config.py, main.py, www/) a la placa y la reinicia.
    cd "$ROOT/device"
    [[ -f config.py ]] || { echo "Falta device/config.py (copia config.example.py)." >&2; exit 1; }
    "$BIN/mpremote" connect "$PORT" mkdir :www 2>/dev/null || true
    "$BIN/mpremote" connect "$PORT" cp config.py :config.py + cp www/index.html :www/index.html + cp main.py :main.py
    python3 -I "$ROOT/scripts/monitor.py" 115200 reset "${2:-20}"
    ;;
  repl)
    "$BIN/mpremote" connect "$PORT" repl
    ;;
  preview)
    python3 "$ROOT/scripts/preview.py"
    ;;
  backup)
    out="${2:-$ROOT/backup/flash-$(date +%Y%m%d-%H%M%S).bin}"
    "$BIN/esptool" --port "$PORT" --baud "$BAUD" read-flash 0 0x400000 "$out"
    shasum -a 256 "$out"
    ;;
  restore)
    img="${2:-$ROOT/backup/factory-esp-at-2.4.0-4MB.bin}"
    echo "Voy a SOBRESCRIBIR todo el flash con: $img"
    read "ok?¿Continuar? (escribe si): "
    [[ "$ok" == "si" ]] || { echo "Cancelado."; exit 1; }
    "$BIN/esptool" --port "$PORT" --baud "$BAUD" write-flash 0 "$img"
    ;;
  erase)
    echo "Voy a BORRAR todo el flash del ESP32."
    read "ok?¿Continuar? (escribe si): "
    [[ "$ok" == "si" ]] || { echo "Cancelado."; exit 1; }
    "$BIN/esptool" --port "$PORT" erase-flash
    ;;
  *)
    echo "Uso: $0 <info|efuses|monitor [seg]|upload|repl|preview|backup [archivo]|restore [archivo]|erase>"
    exit 1
    ;;
esac
