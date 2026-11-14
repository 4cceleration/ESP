# Servidor web del ESP32 (MicroPython), pensado para gastar la menor RAM posible.
#
# - La página se guarda ya comprimida (www/index.html.gz) y se envía tal cual.
# - Un único búfer de 1 KB, reservado al arrancar, sirve todos los envíos.
# - Las cabeceras de respuesta son constantes: no se construyen por petición.
# - Peticiones acotadas: 2 KB de cabeceras, 4 s de espera, 4 conexiones a la vez.
# - Solo GET/HEAD y rutas fijas: lo que pide el cliente nunca toca el sistema de archivos.
# - Un vigilante recoge basura cada 10 s y reinicia la placa si la memoria se agota.
# - Cada pocos minutos consulta GitHub y, si hay un commit nuevo, baja la página.
# - Mantiene una conexión saliente a un relevo en Cloudflare: por ahí le llegan las
#   visitas de internet, sin abrir puertos en el router.
import asyncio
import binascii
import gc
import json
import os
import time

import machine
import micropython
import network

import config

micropython.alloc_emergency_exception_buf(100)

PAGE_GZ = "www/index.html.gz"
PAGE_TMP = "www/index.tmp"
SHA_FILE = "www/version.txt"

MAX_CONN = 4          # conexiones simultáneas; el resto recibe 503
MAX_HEAD = 2048       # bytes máximos de cabeceras por petición
IO_TIMEOUT = 4        # segundos de espera por cliente
LOW_MEM = 24000       # si queda menos RAM libre tras limpiar, se reinicia
MAX_PAGE = 300000     # tamaño máximo aceptado al actualizar la página

BUF = bytearray(1024)
MV = memoryview(BUF)
send_lock = asyncio.Lock()   # el búfer es único: un envío de archivo a la vez

led = machine.Pin(config.LED_PIN, machine.Pin.OUT)
led.value(0)

START = time.time()
conns = 0
requests_served = 0
mem_min = gc.mem_free()
etag = b""
page_size = 0
wlan = None
mode = ""
blinking = False

H_PAGE = (b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
          b"Content-Encoding: gzip\r\nVary: Accept-Encoding\r\n"
          b"Cache-Control: public, max-age=60\r\nConnection: close\r\n")
H_304 = b"HTTP/1.1 304 Not Modified\r\nCache-Control: public, max-age=60\r\nConnection: close\r\n"
H_JSON = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
          b"Cache-Control: no-store\r\nConnection: close\r\n")
R_202 = b"HTTP/1.1 202 Accepted\r\nCache-Control: no-store\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
R_404 = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
R_405 = b"HTTP/1.1 405 Method Not Allowed\r\nAllow: GET, HEAD\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
R_400 = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
R_503 = b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 2\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


async def blink():
    """Hace titilar el LED de la placa unos segundos."""
    global blinking
    blinking = True
    try:
        for _ in range(16):
            led.value(not led.value())
            await asyncio.sleep_ms(110)
    finally:
        led.value(0)
        blinking = False


def start_blink():
    if not blinking:
        asyncio.create_task(blink())


def read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def load_page_info():
    """Recalcula tamaño y ETag de la página guardada."""
    global etag, page_size
    try:
        page_size = os.stat(PAGE_GZ)[6]
    except OSError:
        page_size = 0
    version = read_text(SHA_FILE)[:12] or "local"
    etag = ('"%s-%d"' % (version, page_size)).encode()


def connect():
    try:
        network.hostname(config.HOSTNAME)
    except Exception:
        pass
    ap = network.WLAN(network.AP_IF)
    sta = network.WLAN(network.STA_IF)
    if config.WIFI_SSID:
        ap.active(False)            # el punto de acceso encendido cuesta RAM
        sta.active(True)
        sta.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        for _ in range(config.WIFI_TIMEOUT_S * 4):
            if sta.isconnected():
                return sta, "wifi"
            led.value(not led.value())
            time.sleep(0.25)
        sta.active(False)
    ap.active(True)
    try:
        ap.config(ssid=config.AP_SSID, password=config.AP_PASSWORD,
                  security=network.WLAN.SEC_WPA2)
    except Exception:
        ap.config(essid=config.AP_SSID, password=config.AP_PASSWORD,
                  authmode=network.AUTH_WPA2_PSK)
    return ap, "ap"


async def read_head(reader):
    """Lee las cabeceras con tope de tamaño. Devuelve bytes o None si no son válidas."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = await asyncio.wait_for(reader.read(512), IO_TIMEOUT)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_HEAD:
            return None
    return data


async def send_page(writer, head_only):
    writer.write(H_PAGE)
    writer.write(b"ETag: " + etag + b"\r\nContent-Length: %d\r\n\r\n" % page_size)
    if head_only:
        await writer.drain()
        return
    async with send_lock:
        with open(PAGE_GZ, "rb") as f:
            while True:
                n = f.readinto(BUF)
                if not n:
                    break
                writer.write(MV[:n])
                await writer.drain()


async def handle(reader, writer):
    global conns, requests_served
    conns += 1
    try:
        if conns > MAX_CONN:
            writer.write(R_503)
            await writer.drain()
            return
        data = await read_head(reader)
        if not data:
            if data is None:
                writer.write(R_400)
                await writer.drain()
            return
        end = data.find(b"\r\n")
        parts = data[:end].split(b" ")
        if len(parts) < 2:
            writer.write(R_400)
            await writer.drain()
            return
        method = parts[0]
        path = parts[1].split(b"?")[0]
        requests_served += 1

        if path == b"/api/blink":
            if method == b"POST":
                start_blink()
                writer.write(R_202)
            else:
                writer.write(R_405)
        elif method not in (b"GET", b"HEAD"):
            writer.write(R_405)
        elif path in (b"/", b"/index.html"):
            if not page_size:
                writer.write(R_404)
            elif etag in data:          # If-None-Match coincide: nada que enviar
                writer.write(H_304)
                writer.write(b"ETag: " + etag + b"\r\n\r\n")
            else:
                await send_page(writer, method == b"HEAD")
        elif path == b"/api/status":
            body = b'{"uptime_s":%d,"mem_free":%d,"mem_min":%d,"requests":%d,"version":"%s"}' % (
                time.time() - START, gc.mem_free(), mem_min, requests_served,
                read_text(SHA_FILE)[:12].encode() or b"local")
            writer.write(H_JSON)
            writer.write(b"Content-Length: %d\r\n\r\n" % len(body))
            if method == b"GET":
                writer.write(body)
        else:
            writer.write(R_404)
        await writer.drain()
    except Exception as e:
        print("petición:", repr(e))
    finally:
        conns -= 1
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def housekeeper():
    """Limpia memoria, vigila el Wi-Fi y reinicia si la RAM se agota."""
    global mem_min
    n = 0
    while True:
        await asyncio.sleep(10)
        gc.collect()
        free = gc.mem_free()
        if free < mem_min:
            mem_min = free
        if free < LOW_MEM:
            print("memoria baja (%d), reiniciando" % free)
            machine.reset()
        n += 1
        if n % 2 == 0 and mode == "wifi" and not wlan.isconnected():
            print("Wi-Fi caído, reconectando")
            try:
                wlan.disconnect()
                wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
            except Exception as e:
                print("reconexión:", repr(e))


def fetch_update():
    """Consulta GitHub y, si hay commit nuevo, descarga la página. Devuelve True si cambió."""
    import requests
    repo = config.GITHUB_REPO
    ua = {"User-Agent": "esp32-panel", "Accept": "application/vnd.github.sha"}
    r = requests.get("https://api.github.com/repos/%s/commits/%s" % (repo, config.GITHUB_BRANCH),
                     headers=ua, timeout=10)
    try:
        if r.status_code != 200:
            print("GitHub respondió", r.status_code)
            return False
        sha = r.raw.read(40).decode()
    finally:
        r.close()
    if len(sha) != 40 or sha == read_text(SHA_FILE):
        return False

    gc.collect()
    r = requests.get("https://raw.githubusercontent.com/%s/%s/%s" % (repo, sha, config.GITHUB_PAGE),
                     headers={"User-Agent": "esp32-panel", "Accept-Encoding": "gzip"}, timeout=10)
    try:
        if r.status_code != 200:
            print("descarga respondió", r.status_code)
            return False
        if r.headers.get("Content-Encoding", "") != "gzip":
            print("la descarga no llegó comprimida; se conserva la página actual")
            return False
        total = 0
        with open(PAGE_TMP, "wb") as f:
            while True:
                n = r.raw.readinto(BUF)
                if not n:
                    break
                total += n
                if total > MAX_PAGE:
                    raise ValueError("página demasiado grande")
                f.write(MV[:n])
    finally:
        r.close()
    if total < 20:
        return False
    with open(PAGE_TMP, "rb") as f:
        if f.read(2) != b"\x1f\x8b":      # firma gzip
            return False
    os.rename(PAGE_TMP, PAGE_GZ)
    with open(SHA_FILE, "w") as f:
        f.write(sha)
    print("página actualizada a", sha[:12], "(%d bytes)" % total)
    return True


async def updater():
    await asyncio.sleep(20)
    while True:
        if wlan.isconnected() and gc.mem_free() > 50000:
            gc.collect()
            async with send_lock:          # no se sirve la página mientras se reemplaza
                try:
                    led.value(1)
                    if fetch_update():
                        load_page_info()
                except Exception as e:
                    print("actualización:", repr(e))
                finally:
                    led.value(0)
            gc.collect()
        await asyncio.sleep(config.UPDATE_EVERY_S)


def ws_send(writer, op, payload):
    """Escribe una trama WebSocket de cliente (máscara en ceros: no altera los datos)."""
    n = len(payload)
    if n < 126:
        writer.write(bytes((0x80 | op, 0x80 | n, 0, 0, 0, 0)))
    else:
        writer.write(bytes((0x80 | op, 0xFE, n >> 8, n & 0xFF, 0, 0, 0, 0)))
    writer.write(payload)


async def ws_read(reader):
    h = await reader.readexactly(2)
    n = h[1] & 0x7F
    if n == 126:
        n = int.from_bytes(await reader.readexactly(2), "big")
    if n > 512:
        raise OSError("trama demasiado grande")
    return h[0] & 0x0F, (await reader.readexactly(n) if n else b"")


async def relay_request(writer, data):
    """Atiende una orden del relevo: titilar o enviar la página."""
    global requests_served
    try:
        m = json.loads(data)
    except ValueError:
        return
    if m.get("cmd") == "blink":
        start_blink()
        return
    rid = m.get("id")
    if not isinstance(rid, int):
        return
    requests_served += 1
    async with send_lock:
        ws_send(writer, 1, b'{"id":%d,"status":%d,"gzip":true,"etag":%s}'
                % (rid, 200 if page_size else 404, json.dumps(etag.decode()).encode()))
        if page_size:
            BUF[0] = (rid >> 24) & 0xFF
            BUF[1] = (rid >> 16) & 0xFF
            BUF[2] = (rid >> 8) & 0xFF
            BUF[3] = rid & 0xFF
            body = MV[4:]
            with open(PAGE_GZ, "rb") as f:
                while True:
                    n = f.readinto(body)
                    if not n:
                        break
                    ws_send(writer, 2, MV[:n + 4])
                    await writer.drain()
        ws_send(writer, 1, b'{"id":%d,"end":true}' % rid)
        await writer.drain()


async def relay_session():
    import ssl
    host = config.RELAY_HOST
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_NONE
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, 443, ssl=ctx, server_hostname=host), 20)
    try:
        writer.write(b"GET /_board HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
                     b"Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                     b"Sec-WebSocket-Key: %s\r\nX-Board-Key: %s\r\n\r\n"
                     % (host.encode(), binascii.b2a_base64(os.urandom(16)).strip(),
                        config.RELAY_KEY.encode()))
        await writer.drain()
        head = await read_head(reader)
        if not head or b" 101 " not in head[:16]:
            raise OSError("el relevo rechazó la conexión: %s" % (head or b"")[:32])
        print("relevo conectado:", host)
        last = time.time()
        while True:
            try:
                op, data = await asyncio.wait_for(ws_read(reader), 30)
            except asyncio.TimeoutError:
                if time.time() - last > 100:
                    raise OSError("el relevo dejó de responder")
                ws_send(writer, 1, b"ping")
                await writer.drain()
                continue
            last = time.time()
            if op == 8:
                raise OSError("el relevo cerró la conexión")
            if op == 9:
                ws_send(writer, 10, data)
                await writer.drain()
            elif op == 1 and data != b"pong":
                await relay_request(writer, data)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def relay():
    """Mantiene viva la conexión con el relevo; si se cae, reintenta."""
    await asyncio.sleep(3)
    while True:
        if wlan.isconnected():
            try:
                await relay_session()
            except Exception as e:
                print("relevo:", repr(e))
            gc.collect()
        await asyncio.sleep(15)


async def main():
    global wlan, mode
    wlan, mode = connect()
    led.value(0)
    load_page_info()
    gc.collect()
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
    ip = wlan.ifconfig()[0]
    if mode == "wifi":
        print("Conectado a '%s'. Sitio: http://%s/  (o http://%s.local/)"
              % (config.WIFI_SSID, ip, config.HOSTNAME))
    else:
        print("Modo punto de acceso '%s'. Sitio: http://%s/" % (config.AP_SSID, ip))
    print("memoria libre al arrancar:", gc.mem_free())
    await asyncio.start_server(handle, "0.0.0.0", 80, backlog=MAX_CONN)
    asyncio.create_task(housekeeper())
    if mode == "wifi" and config.GITHUB_REPO:
        asyncio.create_task(updater())
    if mode == "wifi" and config.RELAY_HOST:
        asyncio.create_task(relay())
    while True:
        await asyncio.sleep(3600)


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
