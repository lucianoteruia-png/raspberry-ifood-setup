#!/usr/bin/env python3
# =============================================================================
# rpi-agent.py  --  Agente de monitoramento para o "Painel de Raspberry"
#
# Expoe dois endpoints HTTP que o painel consome, com CORS liberado:
#     GET /health   -> {"status":"ok","hostname":"..."}
#     GET /devices  -> {"devices":[{"name":..,"type":..,"status":..}, ...]}
#
# Tipos: printer | usb | network | storage | outro
# Status por device: ready | busy | error
#
# Roda em porta propria (padrao 2526) para NAO conflitar com o print server
# na 2525. E somente leitura: nao imprime, nao altera nada no Pi.
# Sem dependencias externas -- usa apenas a biblioteca padrao do Python 3.
# =============================================================================

import json, os, socket, subprocess, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT               = int(os.environ.get("AGENT_PORT", "2526"))
PRINT_SERVER_PORT  = int(os.environ.get("PRINT_SERVER_PORT", "2525"))


def run(cmd, timeout=4):
    """Executa um comando e devolve stdout (string vazia em caso de erro)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def printers():
    """Impressoras do CUPS via `lpstat -p`."""
    devs = []
    for line in run(["lpstat", "-p"]).splitlines():
        line = line.strip()
        if not line.startswith("printer "):
            continue
        name = line.split()[1] if len(line.split()) > 1 else "impressora"
        low = line.lower()
        if "disabled" in low or "stopped" in low or "not accepting" in low:
            status = "error"
        elif "printing" in low:
            status = "busy"
        else:
            status = "ready"
        devs.append({"name": name.replace("_", " "), "type": "printer", "status": status})
    return devs


def usb_devices():
    """Perifericos USB via `lsusb` (ignora root hubs e impressoras ja no CUPS)."""
    devs = []
    for line in run(["lsusb"]).splitlines():
        if "ID " not in line:
            continue
        desc = line.split("ID ", 1)[1]
        bits = desc.split(None, 1)                 # remove o "xxxx:xxxx"
        label = bits[1].strip() if len(bits) > 1 else desc.strip()
        low = label.lower()
        if not label or "root hub" in low:
            continue
        if "zebra" in low or "printer" in low:     # impressora ja vem pelo CUPS
            continue
        devs.append({"name": label, "type": "usb", "status": "ready"})
    return devs


def network_devices():
    """Interfaces de rede que estao UP (eth0 / wlan0)."""
    devs, base = [], "/sys/class/net"
    try:
        for iface in sorted(os.listdir(base)):
            if iface == "lo":
                continue
            try:
                oper = open(os.path.join(base, iface, "operstate")).read().strip()
            except Exception:
                oper = ""
            if oper == "up":
                if iface.startswith("e"):
                    nm = iface + " (cabeada)"
                elif iface.startswith("w"):
                    nm = iface + " (wifi)"
                else:
                    nm = iface
                devs.append({"name": nm, "type": "network", "status": "ready"})
    except Exception:
        pass
    return devs


def print_server():
    """Reporta se o print server local (2525) esta de pe."""
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/health" % PRINT_SERVER_PORT, timeout=2)
        st = "ready"
    except Exception:
        st = "error"
    return [{"name": "Print Server :%d" % PRINT_SERVER_PORT, "type": "outro", "status": st}]


def collect():
    return printers() + usb_devices() + network_devices() + print_server()


class Handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("", "/health"):
            self._json(200, {"status": "ok", "hostname": socket.gethostname()})
        elif path == "/devices":
            self._json(200, {"devices": collect()})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *args):     # silencia o log padrao (muito verboso)
        pass


if __name__ == "__main__":
    print("Agente do Painel de Raspberry ouvindo em 0.0.0.0:%d" % PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
