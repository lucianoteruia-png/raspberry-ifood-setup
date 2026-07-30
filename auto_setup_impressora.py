#!/usr/bin/env python3
"""
auto_setup_impressora.py
========================
Script único — faz o setup na primeira execução e depois vira um serviço
de monitoramento contínuo.

Uso (primeira vez, como root):
    sudo python3 auto_setup_impressora.py

O que faz na primeira execução:
    1. Instala CUPS, cups-bsd e dependências Python
    2. Cria e habilita o serviço systemd (boot automático)
    3. Inicia o serviço (que chama este mesmo script em loop)

O que faz como serviço (loop contínuo):
    1. Lê o MAC address da Raspberry
    2. Busca no Firestore: nome da mesa e FC
    3. Cadastra a impressora Zebra no CUPS se necessário
    4. Registra no Kdabra como servidor de impressão
    5. Monitora continuamente:
       - Desconectada → checa a cada 5s (detecção rápida)
       - Conectada    → checa a cada 30 min
       - Offline >2h  → desregistra do Kdabra
       - Volta        → re-registra automaticamente
"""

import os
import sys
import re
import subprocess
import time
import requests
from google.oauth2 import service_account
import google.auth
import google.auth.transport.requests

# ─────────────────────────────────────────────
# CREDENCIAIS FIREBASE
# ⚠  Mantenha este arquivo em local seguro se as credenciais tiverem
#    permissões de escrita. Para uso somente-leitura no Firestore,
#    o risco de exposição é baixo.
# ─────────────────────────────────────────────
FIREBASE_CREDENTIALS = {
  "type": "service_account",
  "project_id": "impressoras-etiquetas",
  "private_key_id": "2458c3eb13f31762e48e392912b73494e36f9c0e",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCrhtFp5GjAU6Eq\ndEYYpJYhmHtYQx8Vdwl+QD2ZQ6mB+Dsm+7MAzhktJ3yQhMbCjSt+JYaSH4Wcm5b1\nkfTW+x34lUiZOaEKlIIsR8M1glppTlXpdzA+BJPXs84j/VyYbOEP0pz1Ouq+6tuj\n9gWq0D+7/jPN8+jM6G/LHy5/OA73V5HAACxRx1gvpHn+ScRawTNNSb3xb7wqPHB5\nJUKFynDnn3KPaY4fXr9C6FiY65/ntYfmblMdneALVgOuzSJklRfkbRTRB/+hyldU\nfVoaW/6svq20UhoNE6UuBb4Ctle/9EKC08BWd3HL3+GFIGTwpyDzxKmLjXHVN725\nU6SwMZGbAgMBAAECggEABwK/qcsC17mTVh+NLedW65Cb71ju+vrz5wvLzhPh6G9e\nRj2gwguqeRoAEWLGl5/Fg1EYAFOhgRaAQ7vvfJ9O86DGaDI0JDE7ENbuDPstpC2Q\n0rYNwWXWf8ktnR2h8ej2r1A1x3WHsBNRXuY+B7lIoZpw654TNIIw75BwChXJ0Xow\nTfEWeJ8Rgrp9VftsyjDA9D9a01h9hKq2Xra5XmY1gF1oS4YYz4yydQtFn06Q1u/B\nX4HI6uqMl3yeTrcMnwZ8uqa20401dtoO9NRXMU95MlBSYGLyXw8Q7KHB8TwrgPiB\n6pWXgmGsdaOR/mtGlhTnWJXpTeU4oEQTt21jOgTEwQKBgQDgckyH9Fs6Y7iYRxaA\nZjr4fLkRPP85HjPZ/4xOVGZCYfq3cAXZr40qaQ97sQrKs+ZWrXISRC2X3Ss4b3ro\nQdmmcPPFoIFuyaX9bEE6F4EhaHvpc0Jl6TbbgMt2BVF/8eNPaYZTwub7PuwCunnc\n8dZW9OfBYasoZnbro9sbezZygwKBgQDDo/bBoxrejHaEAxLjl/4XrT0LQIv0F1o7\nnGhlfseVfdjpq/edeFbuxnDBY9ip3HccZSfK6aw4L1NmImSj1DH5LdMhm/FhLlP2\nnueC/cIICeG6oSRWi3NHuvz/c/QglXzb3ddavT9Gk5NxhjqBPU2od6uqwzEM4+sg\nwOGqAyhZCQKBgGA1/sJkp9qOtqloB6hAqlSsOjS+ffVBEh8HoWBOY4tfLrcFaSyY\nSR397SoriSG9HibXsMdNvHGV2BoYB4qZ96+WSZjUpccU33eTuR4qxyrH/B3lT3ga\nEW7kddMAkqAS00rOREuRh6v5m/fLccOZUzTxRIsrz8/ApId8NMdB+OP7AoGAeoGb\nrJlD5AO02ulJ1LaCZ7UVOoyKlqhg2l8QiC2hMJ0DTR9gCH0ogpBEXvT04TiqZV96\nUXeNXglUgeobdvMS7+OgB7Wsqpvl+9J5Se84puv5K3JoXMEpyMrwTc4AGr9A1jTN\n+4Xxr3INq9LPo8oNbOay2lUry9SUkYf2Rw1/IHECgYEAtLndZN1b9jmzby0vwoLy\nIdR4tsMHBS/ZR7ZtTSeoYg41a2tHgZAIKG8MI42dgIlmSZCvHnYsDmJ0AtD6ZznJ\nlHOXNo/2jliWwEomtqQyZ0BamLkkRNz3EFaZ6xL6RWA7W2k9RWhzV+iUafUgVNPd\nDERMMgnnnMXU7t9QYzce+1A=\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@impressoras-etiquetas.iam.gserviceaccount.com",
  "client_id": "117471603464454861042",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40impressoras-etiquetas.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────

SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR  = os.path.dirname(SCRIPT_PATH)

FIRESTORE_COLLECTION = "raspberrys"
KDABRA_URL_PADRAO    = "https://stock.api.wms.kdabra.com.br"
PRINTER_SERVER_PORT  = 2525
WAIT_BETWEEN_RETRIES = 10
MAX_RETRIES          = 10
NOME_PADRAO          = "Impressora_Sem_Nome"
FC_PADRAO            = 2

SERVICE_NAME = "auto-setup-impressora"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"

# Intervalos de monitoramento
CHECK_OFFLINE_SEG  = 5           # checa a cada 5s quando impressora está desconectada
CHECK_ONLINE_SEG   = 30 * 60    # checa a cada 30 min quando está conectada
TEMPO_OFFLINE_DESREGISTRAR = 2 * 60 * 60  # 2 horas → desregistrar do Kdabra


# ─────────────────────────────────────────────
# SETUP AUTOMÁTICO (primeira execução)
# ─────────────────────────────────────────────

def ja_instalado():
    return os.path.exists(SERVICE_FILE)


def executar(cmd, descricao=""):
    """Executa um comando do sistema e retorna True se sucesso."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return True
        log(f"AVISO [{descricao}]: {result.stderr.strip() or result.stdout.strip()}")
        return False
    except Exception as e:
        log(f"ERRO [{descricao}]: {e}")
        return False


def fazer_setup():
    """
    Instala dependências, cria o serviço systemd e o inicia.
    Chamado automaticamente na primeira execução (quando rodado como root).
    """
    if os.geteuid() != 0:
        print("ERRO: Execute como root na primeira vez: sudo python3 auto_setup_impressora.py")
        sys.exit(1)

    print("")
    print("╔══════════════════════════════════════════╗")
    print("║   Setup Servidor de Impressão Zebra      ║")
    print("║   Kdabra - Raspberry Pi                  ║")
    print("╚══════════════════════════════════════════╝")
    print("")

    # 1. Dependências do sistema
    print("[1/4] Instalando dependências...")
    executar(["apt-get", "update", "-qq"], "apt-get update")
    executar(["apt-get", "install", "-y", "cups", "cups-bsd", "cups-client", "-qq"], "apt-get install cups")
    executar(["systemctl", "enable", "cups", "--quiet"], "enable cups")
    executar(["systemctl", "start", "cups"], "start cups")
    executar(["usermod", "-aG", "lpadmin", "pi"], "usermod lpadmin")
    print("  ✓ CUPS instalado")

    # 2. Dependências Python
    executar(
        ["pip3", "install", "google-auth", "requests", "--break-system-packages", "-q"],
        "pip3 install"
    )
    print("  ✓ Dependências Python instaladas")

    # 3. Serviço systemd
    print("[2/4] Criando serviço systemd...")
    service_content = f"""[Unit]
Description=Auto Setup Impressora Zebra - Kdabra
After=network.target cups.service

[Service]
User=root
ExecStart=/usr/bin/python3 {SCRIPT_PATH}
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    with open(SERVICE_FILE, "w") as f:
        f.write(service_content)

    executar(["systemctl", "daemon-reload"], "daemon-reload")
    executar(["systemctl", "enable", SERVICE_NAME, "--quiet"], "enable service")
    print(f"  ✓ Serviço {SERVICE_NAME} criado e habilitado no boot")

    # 4. Detectar e cadastrar Zebra no CUPS agora
    print("[3/4] Detectando impressora Zebra...")
    time.sleep(2)
    uri = detectar_zebra_usb()
    if uri:
        print(f"  ✓ Zebra detectada: {uri}")
        cadastrar_impressora_cups(uri)
    else:
        print("  ⚠ Nenhuma Zebra detectada agora. O monitoramento cadastrará ao conectar.")

    # 5. Iniciar serviço
    print("[4/4] Iniciando serviço...")
    executar(["systemctl", "start", SERVICE_NAME], "start service")
    time.sleep(3)

    try:
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            capture_output=True, text=True
        )
        status = result.stdout.strip()
    except Exception:
        status = "desconhecido"

    print("")
    print("╔══════════════════════════════════════════╗")
    print("║          ✓  Setup concluído!             ║")
    print("╚══════════════════════════════════════════╝")
    print("")
    print(f"  Serviço: {status}")
    print("")
    print("  Comportamento automático:")
    print("    • Desconectada → checa a cada 5s")
    print("    • Ao conectar  → registra imediatamente no Kdabra")
    print("    • Offline >2h  → remove do Kdabra")
    print("    • Volta        → re-registra automaticamente")
    print("")
    print("  Comandos úteis:")
    print(f"    journalctl -u {SERVICE_NAME} -f   (log em tempo real)")
    print(f"    systemctl status {SERVICE_NAME}   (status)")
    print("")


# ─────────────────────────────────────────────
# FUNÇÕES AUXILIARES
# ─────────────────────────────────────────────

def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def get_mac_address():
    for iface in ["wlan0", "eth0"]:
        try:
            result = subprocess.run(
                ["ip", "link", "show", iface],
                capture_output=True, text=True, timeout=5
            )
            match = re.search(r"link/ether\s+([0-9a-f:]{17})", result.stdout)
            if match:
                mac = match.group(1).upper()
                log(f"MAC address ({iface}): {mac}")
                return mac
        except Exception:
            continue
    log("AVISO: Não foi possível obter o MAC address.")
    return None


def buscar_config_firestore(mac_address):
    try:
        creds = service_account.Credentials.from_service_account_info(
            FIREBASE_CREDENTIALS,
            scopes=["https://www.googleapis.com/auth/datastore"]
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)

        project_id = creds.service_account_email.split("@")[1].split(".")[0]
        url = (
            f"https://firestore.googleapis.com/v1/projects/{project_id}"
            f"/databases/(default)/documents/{FIRESTORE_COLLECTION}/{mac_address}"
        )
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=15
        )

        if response.status_code == 200:
            fields = response.json().get("fields", {})
            data = {
                "nome_mesa": fields.get("nome_mesa", {}).get("stringValue", NOME_PADRAO),
                "fulfillment_center_id": int(fields.get("fulfillment_center_id", {}).get("integerValue", FC_PADRAO)),
                "kdabra_url": fields.get("kdabra_url", {}).get("stringValue", KDABRA_URL_PADRAO),
            }
            log(f"Firestore: {data}")
            return data
        elif response.status_code == 404:
            log(f"AVISO: MAC {mac_address} não encontrado no Firestore. Usando padrão.")
        else:
            log(f"ERRO Firestore HTTP {response.status_code}: {response.text}")

    except Exception as e:
        log(f"ERRO Firestore: {e}")

    return {"nome_mesa": NOME_PADRAO, "fulfillment_center_id": FC_PADRAO, "kdabra_url": KDABRA_URL_PADRAO}


def detectar_zebra_usb():
    try:
        result = subprocess.run(["lpinfo", "-v"], capture_output=True, text=True, timeout=10)
        for line in result.stdout.splitlines():
            if any(k in line.lower() for k in ["zebra", "zd220", "ztc"]):
                return line.strip().split(" ")[-1]
        return None
    except Exception:
        return None


def impressora_fisicamente_conectada():
    try:
        result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        if any(k in result.stdout.lower() for k in ["zebra", "zd220", "ztc"]):
            return True
    except Exception:
        pass
    return detectar_zebra_usb() is not None


def impressora_cadastrada_cups(nome="ZD220"):
    try:
        result = subprocess.run(
            ["lpstat", "-p", nome, "-l"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"}
        )
        saida = result.stdout.lower()
        ok = "enabled" in saida and ("idle" in saida or "printing" in saida)
        log(f"CUPS '{nome}': {'OK' if ok else 'não cadastrada'}")
        return ok
    except Exception as e:
        log(f"ERRO CUPS: {e}")
        return False


def cadastrar_impressora_cups(uri, nome="ZD220"):
    log(f"Cadastrando '{nome}' no CUPS: {uri}")
    for cmd in [
        ["lpadmin", "-p", nome, "-E", "-v", uri, "-m", "raw"],
        ["cupsenable", nome],
        ["cupsaccept", nome],
        ["lpoptions", "-d", nome],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            log(f"  {' '.join(cmd)}: {r.stdout.strip() or r.stderr.strip() or 'OK'}")
        except Exception as e:
            log(f"  ERRO {' '.join(cmd)}: {e}")
    time.sleep(3)


def aguardar_printer_server():
    url = f"http://localhost:{PRINTER_SERVER_PORT}/health"
    log(f"Aguardando printer_server ({url})...")
    for i in range(1, MAX_RETRIES + 1):
        try:
            if requests.get(url, timeout=5).status_code == 200:
                log(f"printer_server OK (tentativa {i})")
                return True
        except Exception:
            pass
        log(f"  Tentativa {i}/{MAX_RETRIES} — {WAIT_BETWEEN_RETRIES}s...")
        time.sleep(WAIT_BETWEEN_RETRIES)
    log("ERRO: printer_server não respondeu.")
    return False


def verificar_config_atual():
    try:
        r = requests.get(f"http://localhost:{PRINTER_SERVER_PORT}/health", timeout=5)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def aplicar_config(nome_mesa, fc_id, kdabra_url):
    payload = {"kdabra_url": kdabra_url, "fulfillment_center_id": fc_id,
               "device_name": nome_mesa, "printer_server": True}
    log(f"Registrando no Kdabra: {payload}")
    try:
        r = requests.post(f"http://localhost:{PRINTER_SERVER_PORT}/config", json=payload, timeout=10)
        if r.status_code == 200:
            log("Registrado no Kdabra.")
            return True
        log(f"ERRO registro: {r.status_code} - {r.text}")
    except Exception as e:
        log(f"ERRO /config: {e}")
    return False


def desregistrar_printer_server(nome_mesa, fc_id, kdabra_url):
    payload = {"kdabra_url": kdabra_url, "fulfillment_center_id": fc_id,
               "device_name": nome_mesa, "printer_server": False}
    log(f"Desregistrando do Kdabra: {payload}")
    try:
        r = requests.post(f"http://localhost:{PRINTER_SERVER_PORT}/config", json=payload, timeout=10)
        if r.status_code == 200:
            log("Desregistrado do Kdabra.")
            return True
        log(f"ERRO desregistro: {r.status_code} - {r.text}")
    except Exception as e:
        log(f"ERRO /config desregistrar: {e}")
    return False


def loop_monitoramento(nome_mesa, fc_id, kdabra_url):
    log(f"Monitoramento iniciado "
        f"(offline→{CHECK_OFFLINE_SEG}s | online→{CHECK_ONLINE_SEG//60}min | "
        f"desregistra após {TEMPO_OFFLINE_DESREGISTRAR//3600}h)")

    printer_server_ativo = True
    offline_desde = None

    while True:
        intervalo = CHECK_ONLINE_SEG if printer_server_ativo else CHECK_OFFLINE_SEG
        time.sleep(intervalo)

        log("--- Verificação ---")
        conectada = impressora_fisicamente_conectada()

        if conectada:
            if not printer_server_ativo:
                log("Impressora reconectada. Re-registrando...")
                uri = detectar_zebra_usb()
                if uri and not impressora_cadastrada_cups("ZD220"):
                    cadastrar_impressora_cups(uri, "ZD220")
                if aguardar_printer_server():
                    aplicar_config(nome_mesa, fc_id, kdabra_url)
                printer_server_ativo = True
            else:
                log("Impressora OK.")
            offline_desde = None

        else:
            if offline_desde is None:
                offline_desde = time.time()
                log("Impressora não detectada. Monitorando...")

            horas = (time.time() - offline_desde) / 3600
            log(f"Offline há {horas:.1f}h (desregistra após {TEMPO_OFFLINE_DESREGISTRAR//3600}h)")

            if printer_server_ativo and (time.time() - offline_desde) >= TEMPO_OFFLINE_DESREGISTRAR:
                log("Tempo limite atingido. Removendo do Kdabra...")
                if desregistrar_printer_server(nome_mesa, fc_id, kdabra_url):
                    printer_server_ativo = False


# ─────────────────────────────────────────────
# FLUXO PRINCIPAL
# ─────────────────────────────────────────────

def main():
    # Se ainda não está instalado como serviço, faz o setup primeiro
    if not ja_instalado():
        fazer_setup()
        return  # o serviço vai iniciar este script automaticamente

    # Já está instalado → roda como serviço de monitoramento
    log("=" * 60)
    log("Iniciando auto_setup_impressora (modo serviço)")
    log("=" * 60)

    mac = get_mac_address()
    if not mac:
        log("ERRO: MAC address não identificado.")
        return

    config = buscar_config_firestore(mac)
    nome_mesa = config["nome_mesa"]
    fc_id     = config["fulfillment_center_id"]
    kdabra_url = config["kdabra_url"]

    if not impressora_cadastrada_cups("ZD220"):
        uri = detectar_zebra_usb()
        if uri:
            cadastrar_impressora_cups(uri, "ZD220")
        else:
            log("AVISO: Nenhuma Zebra encontrada. Monitoramento vai cadastrar ao conectar.")
    else:
        log("Impressora já cadastrada no CUPS.")

    if not aguardar_printer_server():
        log("ERRO: printer_server indisponível.")
        return

    config_atual = verificar_config_atual()
    if config_atual:
        ja_ok = (
            config_atual.get("device_name") == nome_mesa and
            config_atual.get("fulfillment_center_id") == fc_id and
            config_atual.get("printer_server") is True
        )
        if ja_ok:
            log("Configuração já correta no Kdabra.")
        else:
            aplicar_config(nome_mesa, fc_id, kdabra_url)
    else:
        aplicar_config(nome_mesa, fc_id, kdabra_url)

    log("Setup inicial concluído. Entrando em monitoramento contínuo...")
    loop_monitoramento(nome_mesa, fc_id, kdabra_url)


if __name__ == "__main__":
    main()
