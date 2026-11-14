# Panel web servido desde el ESP32 (MicroPython).
# Se conecta al Wi-Fi de config.py; si no puede, crea su propia red (modo AP).
import asyncio
import gc
import json
import os
import time

import esp
import esp32
import machine
import network

import config

led = machine.Pin(config.LED_PIN, machine.Pin.OUT)
led.value(0)

START = time.time()
state = {"mode": "", "ssid": "", "requests": 0}
wlan = None


def connect():
    """Devuelve (interfaz, modo). Intenta Wi-Fi y cae a punto de acceso propio."""
    try:
        network.hostname(config.HOSTNAME)
    except Exception:
        pass

    if config.WIFI_SSID:
        sta = network.WLAN(network.STA_IF)
        sta.active(True)
        sta.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        for _ in range(config.WIFI_TIMEOUT_S * 4):
            if sta.isconnected():
                state["ssid"] = config.WIFI_SSID
                return sta, "wifi"
            led.value(not led.value())  # parpadea mientras conecta
            time.sleep(0.25)
        sta.active(False)

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try:
        ap.config(ssid=config.AP_SSID, password=config.AP_PASSWORD,
                  security=network.WLAN.SEC_WPA2)
    except Exception:
        ap.config(essid=config.AP_SSID, password=config.AP_PASSWORD,
                  authmode=network.AUTH_WPA2_PSK)
    state["ssid"] = config.AP_SSID
    return ap, "ap"


def temperature_c():
    try:
        return round((esp32.raw_temperature() - 32) / 1.8, 1)
    except Exception:
        try:
            return round(esp32.mcu_temperature(), 1)
        except Exception:
            return None


def status():
    gc.collect()
    free = gc.mem_free()
    rssi = None
    if state["mode"] == "wifi":
        try:
            rssi = wlan.status("rssi")
        except Exception:
            pass
    mac = ":".join("%02x" % b for b in wlan.config("mac"))
    return {
        "name": config.DEVICE_NAME,
        "mode": state["mode"],
        "ssid": state["ssid"],
        "ip": wlan.ifconfig()[0],
        "hostname": config.HOSTNAME,
        "mac": mac,
        "rssi": rssi,
        "connected": wlan.isconnected() if state["mode"] == "wifi" else True,
        "uptime_s": time.time() - START,
        "mem_free": free,
        "mem_total": free + gc.mem_alloc(),
        "temp_c": temperature_c(),
        "cpu_mhz": machine.freq() // 1000000,
        "flash_mb": esp.flash_size() // (1024 * 1024),
        "led": bool(led.value()),
        "requests": state["requests"],
        "micropython": os.uname().release,
    }


async def send(writer, code, ctype, body):
    if isinstance(body, str):
        body = body.encode()
    writer.write(("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                  "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                  % (code, ctype, len(body))).encode())
    writer.write(body)
    await writer.drain()


async def send_json(writer, obj, code="200 OK"):
    await send(writer, code, "application/json", json.dumps(obj))


async def send_file(writer, path, ctype):
    try:
        size = os.stat(path)[6]
    except OSError:
        await send(writer, "404 Not Found", "text/plain", "No encontrado")
        return
    writer.write(("HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                  "Connection: close\r\n\r\n" % (ctype, size)).encode())
    buf = bytearray(1024)
    with open(path, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            writer.write(bytes(buf[:n]) if n < len(buf) else buf)
            await writer.drain()


async def handle(reader, writer):
    try:
        line = await asyncio.wait_for(reader.readline(), 5)
        parts = line.decode().split()
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1].split("?")[0]

        length = 0
        while True:
            h = await asyncio.wait_for(reader.readline(), 5)
            if h in (b"\r\n", b"\n", b""):
                break
            if h.lower().startswith(b"content-length:"):
                length = int(h.split(b":")[1])
        body = b""
        if 0 < length <= 512:
            body = await asyncio.wait_for(reader.readexactly(length), 5)

        state["requests"] += 1

        if method == "GET" and path in ("/", "/index.html"):
            await send_file(writer, "www/index.html", "text/html; charset=utf-8")
        elif method == "GET" and path == "/api/status":
            await send_json(writer, status())
        elif method == "POST" and path == "/api/led":
            try:
                data = json.loads(body) if body else {}
            except ValueError:
                data = {}
            if "on" in data:
                led.value(1 if data["on"] else 0)
            else:
                led.value(not led.value())
            await send_json(writer, {"led": bool(led.value())})
        elif method == "GET" and path == "/favicon.ico":
            await send(writer, "204 No Content", "text/plain", "")
        else:
            await send(writer, "404 Not Found", "text/plain; charset=utf-8", "No encontrado")
    except Exception as e:
        print("error en petición:", repr(e))
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def keep_wifi():
    """Reconecta si se cae el Wi-Fi."""
    while True:
        await asyncio.sleep(15)
        if state["mode"] == "wifi" and not wlan.isconnected():
            print("Wi-Fi caído, reconectando…")
            try:
                wlan.disconnect()
                wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
            except Exception as e:
                print("reconexión falló:", repr(e))


async def main():
    global wlan
    wlan, state["mode"] = connect()
    led.value(0)
    ip = wlan.ifconfig()[0]
    if state["mode"] == "wifi":
        print("Conectado a '%s'. Panel: http://%s/  (o http://%s.local/)"
              % (state["ssid"], ip, config.HOSTNAME))
    else:
        print("Modo punto de acceso. Red: '%s'. Panel: http://%s/"
              % (state["ssid"], ip))
    await asyncio.start_server(handle, "0.0.0.0", 80, backlog=4)
    asyncio.create_task(keep_wifi())
    while True:
        await asyncio.sleep(3600)


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
