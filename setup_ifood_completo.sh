#!/bin/bash
# ============================================================
# Setup iFood Printer Server — Raspberry Pi (ARM64)
# ============================================================
# Uso:
#   bash setup_ifood_completo.sh
#
# O que este script faz:
#   1. Verifica e instala dependências do sistema
#   2. Baixa o instalador do iFood (Windows .exe) e extrai o servidor
#   3. Cria e patchea os arquivos do servidor local (porta 4013)
#   4. Instala o driver Epson TM-T20X no CUPS
#   5. Sobe o servidor com pm2 (auto-restart)
#   6. Configura regra udev para detectar a impressora ao conectar USB
# ============================================================

set -e

INSTALL_DIR="/home/pi/ifood-server"
IFOOD_EXE_URL="https://download-gestordepedidos.ifood.com.br/printer-widget/Impressora%20GP%20iFood-x64.exe"
NODE_MIN_VERSION=16

echo ""
echo "======================================"
echo "  iFood Printer Setup"
echo "======================================"
echo ""

# -------------------------------------------------------
# 1. Verificação e instalação de dependências
# -------------------------------------------------------
echo "[1/6] Verificando dependências..."

APT_UPDATED=0
apt_install() {
    local pkg="$1"
    if dpkg -s "$pkg" &>/dev/null; then
        echo "      $pkg — já instalado"
    else
        if [ "$APT_UPDATED" -eq 0 ]; then
            sudo apt-get update -qq
            APT_UPDATED=1
        fi
        echo "      $pkg — instalando..."
        sudo apt-get install -y "$pkg" > /dev/null 2>&1
    fi
}

# Node.js — verifica versão mínima
NODE_OK=0
if command -v node &>/dev/null; then
    NODE_VER=$(node -e "process.stdout.write(String(process.versions.node.split('.')[0]))")
    if [ "$NODE_VER" -ge "$NODE_MIN_VERSION" ] 2>/dev/null; then
        echo "      node — já instalado (v$(node --version | tr -d v))"
        NODE_OK=1
    else
        echo "      node — versão antiga ($(node --version)), atualizando para LTS..."
    fi
else
    echo "      node — não encontrado, instalando LTS..."
fi

if [ "$NODE_OK" -eq 0 ]; then
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - > /dev/null 2>&1
    sudo apt-get install -y nodejs > /dev/null 2>&1
    echo "      node — instalado (v$(node --version | tr -d v))"
fi

# npm (vem junto com nodejs, mas verifica)
if ! command -v npm &>/dev/null; then
    sudo apt-get install -y npm > /dev/null 2>&1
    echo "      npm — instalado"
else
    echo "      npm — já instalado ($(npm --version))"
fi

# build-essential — necessário para compilar módulos nativos (node-printer)
apt_install build-essential

# python3-dev — necessário para alguns módulos nativos
apt_install python3-dev

# CUPS — servidor de impressão
if systemctl is-active --quiet cups 2>/dev/null; then
    echo "      cups — já instalado e rodando"
else
    apt_install cups
    sudo systemctl enable cups > /dev/null 2>&1
    sudo systemctl start cups > /dev/null 2>&1
    echo "      cups — iniciado"
fi

# libcups2-dev — headers para compilar node-printer
apt_install libcups2-dev

# p7zip-full — para extrair o .exe do iFood
apt_install p7zip-full

# unzip — para o driver Epson
apt_install unzip

echo "      Dependências OK"

# -------------------------------------------------------
# 2. Baixar e extrair o instalador do iFood
# -------------------------------------------------------
echo "[2/6] Baixando instalador do iFood..."
wget -q "$IFOOD_EXE_URL" -O /tmp/ifood_printer.exe
echo "      Download concluído"

echo "      Extraindo arquivos..."
rm -rf /tmp/ifood_exe /tmp/ifood_exe2 /tmp/ifood_asar
mkdir -p /tmp/ifood_exe

# Primeira extração do .exe (|| true evita que set -e aborte em avisos do 7z)
7z x /tmp/ifood_printer.exe -o/tmp/ifood_exe/ -y > /dev/null 2>&1 || true

# Electron-builder NSIS embute um .7z aninhado — extrai se existir
NESTED_7Z=$(find /tmp/ifood_exe -name "*.7z" 2>/dev/null | head -1)
if [ -n "$NESTED_7Z" ]; then
    mkdir -p /tmp/ifood_exe2
    7z x "$NESTED_7Z" -o/tmp/ifood_exe2/ -y > /dev/null 2>&1 || true
    SEARCH_DIR="/tmp/ifood_exe2"
else
    SEARCH_DIR="/tmp/ifood_exe"
fi

# Localiza o app.asar
ASAR_FILE=$(find "$SEARCH_DIR" -name "app.asar" 2>/dev/null | head -1)
if [ -z "$ASAR_FILE" ]; then
    echo "ERRO: app.asar não encontrado no instalador"
    exit 1
fi

# Extrai app.asar via Python (sem dependências externas)
python3 << PYEOF
import struct, json, os, sys

def extract_asar(asar_file, output_dir):
    with open(asar_file, 'rb') as f:
        f.read(4)
        header_size = struct.unpack('<I', f.read(4))[0]
        f.read(4)
        json_size = struct.unpack('<I', f.read(4))[0]
        header_json = f.read(json_size).decode('utf-8')
        base_offset = 8 + header_size
        header = json.loads(header_json)
        def extract(node, path):
            os.makedirs(path, exist_ok=True)
            for name, item in node.get('files', {}).items():
                fp = os.path.join(path, name)
                if 'files' in item:
                    extract(item, fp)
                elif not item.get('unpacked', False):
                    offset = int(item['offset'])
                    size = item['size']
                    f.seek(base_offset + offset)
                    with open(fp, 'wb') as out:
                        out.write(f.read(size))
        extract(header, output_dir)

extract_asar("$ASAR_FILE", '/tmp/ifood_asar')
print("      Extração concluída")
PYEOF

# -------------------------------------------------------
# 3. Criar e patchar arquivos do servidor
# -------------------------------------------------------
echo "[3/6] Configurando servidor local..."
mkdir -p "$INSTALL_DIR"

# thermal.js — busca em qualquer caminho dentro do asar extraído
THERMAL_SRC=$(find /tmp/ifood_asar -path "*thermal-printer*/dist/main.js" 2>/dev/null | head -1)
if [ -z "$THERMAL_SRC" ]; then
    echo "ERRO: thermal-printer não encontrado no asar"
    exit 1
fi
cp "$THERMAL_SRC" "$INSTALL_DIR/thermal.js"
sed -i 's|require("@niick555/node-printer")|require("./printer-shim")|g' "$INSTALL_DIR/thermal.js"

# server.js — busca em qualquer caminho dentro do asar extraído
SERVER_SRC=$(find /tmp/ifood_asar -path "*local-server*/index.js" 2>/dev/null | head -1)
if [ -z "$SERVER_SRC" ]; then
    echo "ERRO: local-server/index.js não encontrado no asar"
    exit 1
fi
cp "$SERVER_SRC" "$INSTALL_DIR/server.js"
sed -i 's|require("@ifood/thermal-printer")|require("./thermal")|g' "$INSTALL_DIR/server.js"
sed -i 's|require("../../../package.json")|require("./package.json")|g' "$INSTALL_DIR/server.js"
echo 'startLocalPrinterServer();' >> "$INSTALL_DIR/server.js"

# printer-shim.js — adapter entre node-printer (Linux) e API esperada pelo iFood
cat > "$INSTALL_DIR/printer-shim.js" << 'EOF'
const nodePrinter = require('node-printer');
const { exec } = require('child_process');
const { writeFileSync, unlinkSync } = require('fs');

module.exports = {
  getPrinters: () => nodePrinter.list().map(name => ({ name, status: 'IDLE' })),
  printDirect: ({ data, printer, type, success, error }) => {
    const tmpFile = `/tmp/ifood_print_${Date.now()}.raw`;
    try {
      writeFileSync(tmpFile, data);
      exec(`lp -d "${printer}" -o raw "${tmpFile}"`, (err, stdout) => {
        try { unlinkSync(tmpFile); } catch(e) {}
        if (err) { error && error(err); }
        else { success && success(stdout.trim()); }
      });
    } catch(e) {
      try { unlinkSync(tmpFile); } catch(err) {}
      error && error(e);
    }
  }
};
EOF

# package.json
cat > "$INSTALL_DIR/package.json" << 'EOF'
{
  "name": "ifood-server",
  "version": "1.0.0",
  "description": "iFood local printer server",
  "main": "server.js"
}
EOF

# Instala dependências npm
cd "$INSTALL_DIR"
npm install node-printer express cors --save > /dev/null 2>&1
echo "      OK"

# -------------------------------------------------------
# 4. Driver Epson TM-T20X
# -------------------------------------------------------
echo "[4/6] Instalando driver Epson TM-T20X..."

TMX_ZIP=$(find /home/pi/Downloads -name "tmx-cups-src*.zip" 2>/dev/null | head -1)
if [ -n "$TMX_ZIP" ]; then
    echo "      Encontrado: $TMX_ZIP"
    mkdir -p /tmp/tmx-driver
    unzip -q "$TMX_ZIP" -d /tmp/tmx-driver

    INSTALL_SCRIPT=$(find /tmp/tmx-driver -name "install.sh" | head -1)
    MAKEFILE=$(find /tmp/tmx-driver -name "Makefile" | head -1)

    if [ -n "$INSTALL_SCRIPT" ]; then
        sudo bash "$INSTALL_SCRIPT" > /dev/null 2>&1 && echo "      Driver instalado" || echo "      AVISO: install.sh falhou, continuando"
    elif [ -n "$MAKEFILE" ]; then
        cd "$(dirname $MAKEFILE)"
        sudo make install > /dev/null 2>&1 && echo "      Driver instalado via make" || echo "      AVISO: make install falhou, continuando"
        cd "$INSTALL_DIR"
    fi
else
    echo "      tmx-cups-src zip não encontrado em Downloads, pulando"
    echo "      (A impressora ainda pode funcionar com driver genérico do CUPS)"
fi

sudo service cups restart > /dev/null 2>&1 || true

# -------------------------------------------------------
# 5. pm2 — gerenciador de processos com auto-restart
# -------------------------------------------------------
echo "[5/6] Configurando pm2..."

# Instala pm2 se necessário
if ! command -v pm2 &>/dev/null && [ ! -f /usr/local/lib/node_modules/pm2/bin/pm2 ]; then
    echo "      pm2 — instalando..."
    sudo npm install -g pm2 > /dev/null 2>&1
else
    echo "      pm2 — já instalado"
fi

# Resolve caminho (pm2 pode não estar no PATH após sudo install)
PM2_BIN=$(command -v pm2 2>/dev/null \
    || ls /usr/local/lib/node_modules/pm2/bin/pm2 2>/dev/null \
    || find /usr/lib/node_modules/pm2/bin -name pm2 2>/dev/null | head -1)

if [ -z "$PM2_BIN" ]; then
    echo "ERRO: pm2 não encontrado após instalação"
    exit 1
fi

# Para instâncias anteriores sem erro
pkill -f "node.*ifood-server/server.js" 2>/dev/null || true
$PM2_BIN delete ifood-server 2>/dev/null || true
sleep 1

# Sobe com pm2
$PM2_BIN start "$INSTALL_DIR/server.js" --name ifood-server > /dev/null 2>&1

# Configura startup no boot via systemd
$PM2_BIN startup systemd -u pi --hp /home/pi 2>/dev/null | grep "sudo env" | bash > /dev/null 2>&1 || true
$PM2_BIN save > /dev/null 2>&1

sleep 2
if curl -s http://localhost:4013/printers > /dev/null 2>&1; then
    echo "      Servidor rodando na porta 4013"
else
    echo "      AVISO: servidor pode estar iniciando, verifique: pm2 logs ifood-server"
fi

# -------------------------------------------------------
# 6. Regra udev — auto-detecção USB da TM-T20X
# -------------------------------------------------------
echo "[6/6] Configurando detecção automática de impressora USB..."

# Script que roda quando a impressora é conectada
cat > "$INSTALL_DIR/on-printer-connected.sh" << 'EOF'
#!/bin/bash
# Executado pelo udev quando TM-T20X é conectada via USB
sleep 3

sudo service cups restart
sleep 3

if ! lpstat -p TM-T20X > /dev/null 2>&1; then
    PRINTER_URI=$(lpinfo -v 2>/dev/null | grep -i "04b8\|TM-T20\|epson" | head -1 | awk '{print $2}')
    if [ -n "$PRINTER_URI" ]; then
        lpadmin -p TM-T20X -E -v "$PRINTER_URI" -m everywhere 2>/dev/null \
            || lpadmin -p TM-T20X -E -v "$PRINTER_URI" 2>/dev/null \
            || true
        echo "$(date): TM-T20X adicionada ao CUPS: $PRINTER_URI" >> /home/pi/ifood-server/server.log
    else
        echo "$(date): TM-T20X conectada mas URI não encontrada no CUPS" >> /home/pi/ifood-server/server.log
    fi
else
    echo "$(date): TM-T20X já configurada no CUPS" >> /home/pi/ifood-server/server.log
fi
EOF
chmod +x "$INSTALL_DIR/on-printer-connected.sh"

# Verifica se regra udev já existe
UDEV_RULE="/etc/udev/rules.d/99-ifood-printer.rules"
if [ -f "$UDEV_RULE" ] && grep -q "04b8.*0e27" "$UDEV_RULE" 2>/dev/null; then
    echo "      Regra udev — já configurada"
else
    cat > /tmp/99-ifood-printer.rules << 'EOF'
# Epson TM-T20X — iFood printer auto-setup
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="04b8", ATTR{idProduct}=="0e27", RUN+="/bin/bash /home/pi/ifood-server/on-printer-connected.sh"
EOF
    sudo cp /tmp/99-ifood-printer.rules "$UDEV_RULE"
    sudo udevadm control --reload-rules
    echo "      Regra udev — criada para 04b8:0e27"
fi

# -------------------------------------------------------
# Resumo final
# -------------------------------------------------------
echo ""
echo "======================================"
echo "  Setup concluído!"
echo "======================================"
echo ""
echo "Status do servidor:"
curl -s http://localhost:4013/printers 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); [print('  - ' + p['name']) for p in d.get('printers',[])]" \
    2>/dev/null || echo "  (aguardando servidor iniciar)"
echo ""
echo "Próximos passos:"
echo "  1. Conecte a impressora TM-T20X via USB"
echo "  2. Aguarde ~10 segundos para configuração automática"
echo "  3. Verifique: lpstat -p"
echo "  4. Acesse gestordepedidos.ifood.com.br → Ajustes → Impressão"
echo "  5. Confirme 'Extensão aberta', selecione TM-T20X, Epson, 48 colunas → Ativar"
echo ""
echo "Logs: tail -f $INSTALL_DIR/server.log"
echo "PM2:  pm2 status"
echo ""
