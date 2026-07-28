#!/bin/bash
# ============================================================
# setup_impressora_accon.sh
# Configura impressoras térmicas + QZ Tray para portal Accon
# Raspbian (Raspberry Pi OS) - ARM64
# Uso: sudo bash setup_impressora_accon.sh
# ============================================================

QZ_DIR="/opt/qz-tray"
QZ_USER="pi"
QZ_HOME="/home/pi"
TOTAL=6

# Cores
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
info() { echo -e "${BLUE}  →${NC} $1"; }
err()  { echo -e "${RED}  ✗ ERRO:${NC} $1"; exit 1; }
step() { echo -e "\n${BLUE}[$1/$TOTAL]${NC} $2"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Setup Impressora - Portal Accon        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Verificar root
[ "$EUID" -ne 0 ] && err "Execute com sudo: sudo bash $0"

# ─── [1] Verificar QZ Tray ────────────────────────────────
step 1 "Verificando QZ Tray..."
if [ ! -f "$QZ_DIR/qz-tray" ]; then
    err "QZ Tray não encontrado em $QZ_DIR\n  Instale primeiro via: https://qz.io/download"
fi
ok "QZ Tray encontrado em $QZ_DIR"

# ─── [2] Dependências do sistema ──────────────────────────
step 2 "Instalando dependências..."
info "Atualizando pacotes..."
apt-get update -qq
apt-get install -y cups cups-bsd cups-client -qq
ok "CUPS e lpr instalados"

systemctl enable cups --quiet 2>/dev/null
systemctl start cups
ok "CUPS iniciado"

usermod -aG lpadmin "$QZ_USER" 2>/dev/null || true

# ─── [3] Detectar e adicionar impressoras ─────────────────
step 3 "Detectando impressoras USB..."
sleep 3  # aguardar CUPS iniciar

USB_DEVICES=$(lpinfo -v 2>/dev/null | grep "usb://" || true)

if [ -z "$USB_DEVICES" ]; then
    warn "Nenhuma impressora USB detectada agora."
    warn "Se a impressora já está no CUPS, ignore este aviso."
    warn "Caso contrário: conecte a impressora e execute o script novamente."
else
    ADDED=0
    while IFS= read -r linha; do
        URI=$(echo "$linha" | awk '{print $2}')

        # Extrair fabricante e modelo do URI
        FABRICANTE=$(python3 -c "
from urllib.parse import unquote
u = '$URI'
try:
    print(unquote(u.split('//')[1].split('/')[0]))
except:
    print('USB')
" 2>/dev/null || echo "USB")

        MODELO=$(python3 -c "
from urllib.parse import unquote
u = '$URI'
try:
    print(unquote(u.split('//')[1].split('/')[1].split('?')[0]))
except:
    print('Printer')
" 2>/dev/null || echo "Printer")

        # Nome normalizado sem espaços
        NOME=$(echo "${FABRICANTE}_${MODELO}" | tr ' ' '_' | tr -cd '[:alnum:]_-')

        info "Encontrada: $FABRICANTE $MODELO"
        info "  URI: $URI"

        # Verificar se já existe no CUPS
        if lpstat -p "$NOME" &>/dev/null; then
            warn "  $NOME já está no CUPS, pulando."
        else
            if lpadmin -p "$NOME" -E -v "$URI" -m raw 2>/dev/null; then
                ok "  Adicionada: $NOME (fila raw - ESC/POS / ZPL direto)"
                ADDED=$((ADDED+1))
            else
                warn "  Não foi possível adicionar $NOME automaticamente."
                warn "  Adicione manualmente em: http://localhost:631"
            fi
        fi
    done <<< "$USB_DEVICES"

    [ "$ADDED" -gt 0 ] && ok "$ADDED impressora(s) adicionada(s) ao CUPS"
fi

echo ""
echo "  Impressoras no CUPS:"
lpstat -p 2>/dev/null | sed 's/^/    /' || echo "    (nenhuma ainda)"

# ─── [4] Certificado Accon ────────────────────────────────
step 4 "Configurando certificado do portal Accon..."
mkdir -p "$QZ_HOME/.qz"
chown "$QZ_USER:$QZ_USER" "$QZ_HOME/.qz"

# IMPORTANTE: formato tab-separado é obrigatório.
# O QZ Tray ignora silenciosamente linhas sem tab (bug do existsInAnyFile).
printf '4afa7750d7e1ffd23bed461c06c36d58fe71c59f\t*.accon.ai\tAccon\t2025-11-24 12:44:30\t2026-12-06 20:55:26\tfalse\n' \
    > "$QZ_HOME/.qz/allowed.dat"
chown "$QZ_USER:$QZ_USER" "$QZ_HOME/.qz/allowed.dat"

# Limpar blocked.dat para não bloquear o certificado
printf '#%s\n' "$(date)" > "$QZ_HOME/.qz/blocked.dat"
chown "$QZ_USER:$QZ_USER" "$QZ_HOME/.qz/blocked.dat"

ok "Certificado Accon aprovado (válido até dez/2026)"
info "Fingerprint: 4afa7750d7e1ffd23bed461c06c36d58fe71c59f"

# ─── [5] Serviço systemd ──────────────────────────────────
step 5 "Configurando inicialização automática no boot..."
cat > /etc/systemd/system/qz-tray.service << EOF
[Unit]
Description=QZ Tray - Servidor de Impressao
After=network.target cups.service

[Service]
User=$QZ_USER
ExecStart=$QZ_DIR/qz-tray
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable qz-tray --quiet
ok "Serviço systemd criado e habilitado no boot"

# ─── [6] Iniciar QZ Tray ──────────────────────────────────
step 6 "Iniciando QZ Tray..."

# Matar instâncias anteriores (manual ou de sessão anterior)
pkill -f qz-tray 2>/dev/null || true
sleep 2

systemctl start qz-tray
sleep 6

if systemctl is-active --quiet qz-tray; then
    ok "QZ Tray rodando nas portas 8181 (WSS) e 8182 (WS)"
else
    echo ""
    warn "QZ Tray não está ativo. Log:"
    journalctl -u qz-tray -n 20 --no-pager | sed 's/^/    /'
    err "Falha ao iniciar QZ Tray. Verifique o log acima."
fi

# ─── Resumo ───────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║          ✓  Setup concluído!             ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Status dos serviços:"
printf "    %-10s %s\n" "QZ Tray:" "$(systemctl is-active qz-tray)"
printf "    %-10s %s\n" "CUPS:"    "$(systemctl is-active cups)"
echo ""
echo "  Impressoras disponíveis:"
lpstat -p 2>/dev/null | awk '{print "    " $2}' || echo "    (verifique com: lpstat -p)"
echo ""
echo "  Próximo passo:"
echo "    1. Acesse portal.accon.ai → Configurações → Impressoras"
echo "    2. Selecione a impressora detectada"
echo "    3. Clique em Testar"
echo ""
echo "  Para monitorar impressões:"
echo "    sudo tail -f /var/log/cups/access_log"
echo ""
