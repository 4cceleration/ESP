"""Vista previa del panel en el computador, con datos SIMULADOS (sin la placa).
Uso: python3 scripts/preview.py  ->  http://localhost:8032/
"""
import json
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "device" / "www" / "index.html"
START = time.time()
state = {"led": False, "requests": 0}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        state["requests"] += 1
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", INDEX.read_bytes())
        elif self.path == "/api/status":
            free = 98000 + random.randint(-4000, 4000)
            self._send(200, "application/json", json.dumps({
                "name": "ESP32 Panel (vista previa)", "mode": "wifi", "ssid": "Red simulada",
                "ip": "192.168.1.50", "hostname": "esp32-panel", "mac": "xx:xx:xx:xx:xx:xx",
                "rssi": -58 + random.randint(-3, 3), "connected": True,
                "uptime_s": int(time.time() - START), "mem_free": free, "mem_total": 124000,
                "temp_c": round(47 + random.random() * 2, 1), "cpu_mhz": 160, "flash_mb": 4,
                "led": state["led"], "requests": state["requests"], "micropython": "1.29.0",
            }).encode())
        else:
            self._send(404, "text/plain", b"No encontrado")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        state["led"] = bool(data["on"]) if "on" in data else not state["led"]
        self._send(200, "application/json", json.dumps({"led": state["led"]}).encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Vista previa (datos simulados): http://localhost:8032/")
    ThreadingHTTPServer(("127.0.0.1", 8032), Handler).serve_forever()
