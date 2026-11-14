# Copia este archivo como config.py y rellena los datos.
# config.py NO debe compartirse: contiene contraseñas.

HOSTNAME = "esp32-panel"      # el panel queda en http://esp32-panel.local/

# Wi-Fi al que se conecta la placa (solo redes de 2.4 GHz).
# Si WIFI_SSID queda vacío, o no logra conectar, la placa crea su propia red.
WIFI_SSID = ""
WIFI_PASSWORD = ""
WIFI_TIMEOUT_S = 15

# Red propia de la placa (modo punto de acceso). Contraseña de 8+ caracteres.
AP_SSID = "ESP32-Panel"
AP_PASSWORD = "cambia-esta-clave"

LED_PIN = 2                   # LED azul integrado en la mayoría de DevKit

# Actualización automática: la placa consulta este repositorio público de GitHub
# y, cuando hay un commit nuevo, descarga la página. Vacío = desactivado.
GITHUB_REPO = "4cceleration/ESP"
GITHUB_BRANCH = "main"
GITHUB_PAGE = "index.html"
UPDATE_EVERY_S = 300
