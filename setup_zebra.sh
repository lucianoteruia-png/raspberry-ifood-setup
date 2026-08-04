#!/bin/bash
# setup_zebra.sh
# Configura a Raspberry Pi como servidor de impressão Zebra (Kdabra)

GITHUB_RAW="https://raw.githubusercontent.com/lucianoteruia-png/raspberry-ifood-setup/main"
INSTALL_PATH="/opt/auto_setup_impressora.py"

echo ""
echo "Instalando dependências Python..."
pip3 install requests --break-system-packages -q \
    || pip3 install requests -q

echo "Baixando script..."
curl -fsSL "$GITHUB_RAW/auto_setup_impressora.py" -o "$INSTALL_PATH" \
    || { echo "ERRO: Falha ao baixar. Verifique a conexão."; exit 1; }

chmod +x "$INSTALL_PATH"
echo "Iniciando setup..."
sudo python3 "$INSTALL_PATH"
