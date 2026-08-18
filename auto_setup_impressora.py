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

# ─────────────────────────────────────────────
# FIREBASE (Web API Key — sem JWT, sem service account)
# ─────────────────────────────────────────────
FIREBASE_API_KEY   = "AIzaSyDvFFFZCSxn2o-LN-H6PU41RxwsikjPCko"
FIREBASE_PROJECT_ID = "impressoras-etiquetas"

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

FC_NOMES = {
    1: "FC0 - Barra Funda", 2: "FC1 - Osasco", 3: "FC2 - Ribeirão Preto",
    4: "FC1 - Lojinha", 5: "FC2 - Lojinha", 6: "LJ01 - Pamplona",
    7: "FC3 - São Paulo", 8: "LJ02 - Moema", 9: "LJ03 - Pinheiros",
    10: "LJ04 - Higienópolis", 11: "LJ05 - Vila Olimpia", 12: "LJ06 - Alto de Pinheiros",
    13: "LJ07 - Barra Funda", 14: "LJ08 - Morumbi", 15: "LJ09 - Vila Mariana",
    16: "LJ10 - Brooklin", 17: "FC3 - Lojinha", 18: "LJ11 - Campinas",
    19: "LJ12 - Tatuapé", 20: "LJ13 - São Caetano", 21: "LJ15 - Vila Guilherme",
    22: "LJ16 - Consolação", 23: "LJ17 - Ribeirão Preto", 24: "LJ18 - Mooca",
    25: "FC4 - Brasilia", 26: "FC5 - Curitiba", 27: "LJ19 - PR - Republica",
    28: "LJ20 - PR - Rodovia", 29: "LJ21 - PR - Stresser"
}

SERVICE_NAME = "auto-setup-impressora"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"
CONFIG_CACHE  = "/opt/impressora_config.json"  # cache local do último nome/FC

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


def configurar_chromium_impressora_padrao(nome_fila="ZD220"):
    """
    Configura a impressora Zebra como padrão no Chromium via política de sistema.
    Funciona sem precisar abrir o Chromium antes e persiste para todos os usuários.
    """
    import json

    policy_content = {"DefaultPrinterSelection": f'{{"idPattern":"{nome_fila}"}}'}

    # Cria política nos dois caminhos possíveis (varia com a versão do Raspberry Pi OS)
    policy_dirs = [
        "/etc/chromium/policies/managed",
        "/etc/chromium-browser/policies/managed",
    ]

    configurado = False
    for policy_dir in policy_dirs:
        try:
            os.makedirs(policy_dir, exist_ok=True)
            policy_file = os.path.join(policy_dir, "impressora_padrao.json")
            with open(policy_file, "w") as f:
                json.dump(policy_content, f, indent=2)
            print(f"  ✓ Policy criada: {policy_file}")
            configurado = True
        except Exception as e:
            print(f"  ⚠ Não foi possível criar policy em {policy_dir}: {e}")

    # Se o Chromium já foi aberto antes, atualiza o Preferences diretamente também
    prefs_path = "/home/pi/.config/chromium/Default/Preferences"
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path, "r") as f:
                prefs = json.load(f)
            prefs.setdefault("printing", {})["default_destination_selection_rules"] = (
                f'{{"idPattern":"{nome_fila}"}}'
            )
            with open(prefs_path, "w") as f:
                json.dump(prefs, f, separators=(",", ":"))
            subprocess.run(["chown", "pi:pi", prefs_path], capture_output=True)
            print("  ✓ Preferences do Chromium atualizadas")
            configurado = True
        except Exception as e:
            print(f"  ⚠ Não foi possível editar Preferences: {e}")

    return configurado


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
    print("[1/5] Instalando dependências...")
    executar(["apt-get", "update", "-qq"], "apt-get update")
    executar(["apt-get", "install", "-y", "cups", "cups-bsd", "cups-client", "-qq"], "apt-get install cups")
    executar(["systemctl", "enable", "cups", "--quiet"], "enable cups")
    executar(["systemctl", "start", "cups"], "start cups")
    executar(["usermod", "-aG", "lpadmin", "pi"], "usermod lpadmin")
    print("  ✓ CUPS instalado")

    # 2. Dependências Python
    executar(
        ["pip3", "install", "requests", "--break-system-packages", "-q"],
        "pip3 install"
    )
    print("  ✓ Dependências Python instaladas")

    # 3. Serviço systemd
    print("[2/5] Criando serviço systemd...")
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
    print("[3/5] Detectando impressora Zebra...")
    time.sleep(2)
    uri = detectar_zebra_usb()
    if uri:
        print(f"  ✓ Zebra detectada: {uri}")
        cadastrar_impressora_cups(uri)
    else:
        print("  ⚠ Nenhuma Zebra detectada agora. O monitoramento cadastrará ao conectar.")

    # 5. Configurar impressora padrão no Chromium
    print("[4/5] Configurando impressora padrão no Chromium...")
    configurar_chromium_impressora_padrao("ZD220")

    # 6. Iniciar serviço
    print("[5/5] Iniciando serviço...")
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

    mac = get_mac_address() or "não identificado"
    config = buscar_config_firestore(mac) if mac != "não identificado" else None
    nome = config["nome_mesa"] if config else "não encontrado"
    fc   = config["fulfillment_center_id"] if config else "-"
    nao_cadastrado = (nome == NOME_PADRAO)

    print("")
    print("╔══════════════════════════════════════════╗")
    print("║          ✓  Setup concluído!             ║")
    print("╚══════════════════════════════════════════╝")
    print("")
    print(f"  Serviço:     {status}")
    print(f"  MAC address: {mac}")
    print(f"  Nome:        {nome}")
    print(f"  FC:          {FC_NOMES.get(fc, f'ID {fc}') if isinstance(fc, int) else fc}")
    if nao_cadastrado:
        print("")
        print("  ⚠  MAC não encontrado no Firebase!")
        print(f"     Impressora configurada por padrão como {FC_NOMES[FC_PADRAO]}.")
        print("     Cadastre esse MAC com o nome e FC corretos")
        print("     antes de usar a impressora.")
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


def salvar_cache(config):
    """Salva a configuração em arquivo local para uso offline."""
    try:
        import json
        with open(CONFIG_CACHE, "w") as f:
            json.dump(config, f)
    except Exception as e:
        log(f"AVISO: Não foi possível salvar cache: {e}")


def carregar_cache():
    """Carrega a última configuração salva localmente."""
    try:
        import json
        if os.path.exists(CONFIG_CACHE):
            with open(CONFIG_CACHE) as f:
                config = json.load(f)
            log(f"Cache local carregado: {config}")
            return config
    except Exception as e:
        log(f"AVISO: Não foi possível ler cache: {e}")
    return None


def buscar_config_firestore(mac_address):
    try:
        url = (
            f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
            f"/databases/(default)/documents/{FIRESTORE_COLLECTION}/{mac_address}"
            f"?key={FIREBASE_API_KEY}"
        )
        response = requests.get(url, timeout=15)

        if response.status_code == 200:
            fields = response.json().get("fields", {})
            data = {
                "nome_mesa": fields.get("nome_mesa", {}).get("stringValue", NOME_PADRAO),
                "fulfillment_center_id": int(fields.get("fulfillment_center_id", {}).get("integerValue", FC_PADRAO)),
                "kdabra_url": fields.get("kdabra_url", {}).get("stringValue", KDABRA_URL_PADRAO),
            }
            log(f"Firestore: {data}")
            salvar_cache(data)  # salva para uso offline futuro
            return data
        elif response.status_code == 404:
            log(f"AVISO: MAC {mac_address} não encontrado no Firestore. Usando padrão.")
        else:
            log(f"ERRO Firestore HTTP {response.status_code}: {response.text}")

    except Exception as e:
        log(f"ERRO Firestore: {e}")

    # Tenta usar cache local antes de usar padrão
    cache = carregar_cache()
    if cache:
        return cache

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
    """Aguarda o app printer_server subir (qualquer resposta HTTP na porta 2525)."""
    url = f"http://localhost:{PRINTER_SERVER_PORT}/health"
    log(f"Aguardando printer_server ({url})...")
    for i in range(1, MAX_RETRIES + 1):
        try:
            requests.get(url, timeout=5)  # qualquer resposta = app está no ar
            log(f"printer_server app OK (tentativa {i})")
            return True
        except requests.exceptions.ConnectionError:
            pass  # app ainda não subiu
        except Exception:
            return True  # outra exceção = app respondeu de alguma forma
        log(f"  Tentativa {i}/{MAX_RETRIES} — {WAIT_BETWEEN_RETRIES}s...")
        time.sleep(WAIT_BETWEEN_RETRIES)
    log("ERRO: printer_server não iniciou.")
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


def loop_monitoramento(mac, nome_mesa, fc_id, kdabra_url, printer_server_ativo=True):
    log(f"Monitoramento iniciado "
        f"(offline→{CHECK_OFFLINE_SEG}s | online→{CHECK_ONLINE_SEG//60}min | "
        f"desregistra após {TEMPO_OFFLINE_DESREGISTRAR//3600}h)")

    offline_desde = None
    ultima_verificacao_firebase = time.time()

    while True:
        intervalo = CHECK_ONLINE_SEG if printer_server_ativo else CHECK_OFFLINE_SEG
        time.sleep(intervalo)

        log("--- Verificação ---")

        # Re-lê Firebase a cada 30 minutos para pegar mudanças de nome/FC
        if time.time() - ultima_verificacao_firebase >= CHECK_ONLINE_SEG:
            config_novo = buscar_config_firestore(mac)
            ultima_verificacao_firebase = time.time()
            if (config_novo["nome_mesa"] != nome_mesa or
                    config_novo["fulfillment_center_id"] != fc_id or
                    config_novo["kdabra_url"] != kdabra_url):
                log(f"Configuração mudou no Firebase! Atualizando...")
                log(f"  Antes: {nome_mesa} / FC {fc_id}")
                nome_mesa  = config_novo["nome_mesa"]
                fc_id      = config_novo["fulfillment_center_id"]
                kdabra_url = config_novo["kdabra_url"]
                log(f"  Agora: {nome_mesa} / FC {fc_id} ({FC_NOMES.get(fc_id, '')})")
                if printer_server_ativo:
                    aplicar_config(nome_mesa, fc_id, kdabra_url)

        conectada = impressora_fisicamente_conectada()

        if conectada:
            if not printer_server_ativo:
                log("Impressora reconectada. Re-registrando...")
                # Relê Firebase para garantir nome/FC corretos
                config_fresco = buscar_config_firestore(mac)
                nome_mesa  = config_fresco["nome_mesa"]
                fc_id      = config_fresco["fulfillment_center_id"]
                kdabra_url = config_fresco["kdabra_url"]
                ultima_verificacao_firebase = time.time()
                log(f"Config: {nome_mesa} / {FC_NOMES.get(fc_id, fc_id)}")

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

    # Retry progressivo para buscar config do Firebase
    # 30s × 4 tentativas (2min) → 60s × 5 tentativas (5min) → ciclo normal de 30min
    config = None
    usando_cache = False
    tentativas = [(30, 4), (60, 5)]  # (intervalo, quantidade)

    for intervalo, qtd in tentativas:
        if config and config["nome_mesa"] != NOME_PADRAO:
            break
        for i in range(qtd):
            config = buscar_config_firestore(mac)
            if config["nome_mesa"] != NOME_PADRAO:
                log(f"Config obtida do Firebase: {config['nome_mesa']}")
                break
            log(f"Firebase indisponível ou MAC sem cadastro. Tentando em {intervalo}s...")
            time.sleep(intervalo)

    if not config or config["nome_mesa"] == NOME_PADRAO:
        cache = carregar_cache()
        if cache:
            config = cache
            usando_cache = True
            log("Usando configuração do cache local.")
        else:
            config = {"nome_mesa": NOME_PADRAO, "fulfillment_center_id": FC_PADRAO, "kdabra_url": KDABRA_URL_PADRAO}
            log("AVISO: Usando configuração padrão. Cadastre o MAC no Firebase.")

    nome_mesa  = config["nome_mesa"]
    fc_id      = config["fulfillment_center_id"]
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

    impressora_ok = impressora_fisicamente_conectada()

    if impressora_ok:
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
    else:
        log("Impressora não conectada. Monitoramento detectará ao conectar (checa a cada 5s).")

    log("Setup inicial concluído. Entrando em monitoramento contínuo...")
    loop_monitoramento(mac, nome_mesa, fc_id, kdabra_url, printer_server_ativo=impressora_ok)


if __name__ == "__main__":
    main()
