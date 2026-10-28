#!/usr/bin/env bash
#
# Instalador do MR. ROBOT
# - instala dependencias (python, requests, ollama, ferramentas de recon)
# - instala o agente em ~/.mrrobot
# - cria o comando global 'mrrobot' que roda na pasta atual
# - configura atualizacao periodica (modelos, templates, e o proprio script via git se houver)
#
# Uso:  bash install.sh
#
set -euo pipefail

VERDE="\033[92m"; AMARELO="\033[93m"; VERMELHO="\033[91m"; DIM="\033[2m"; RST="\033[0m"
log()  { echo -e "${VERDE}[+]${RST} $1"; }
warn() { echo -e "${AMARELO}[!]${RST} $1"; }
err()  { echo -e "${VERMELHO}[x]${RST} $1"; }

DEST="$HOME/.mrrobot"
BIN="$HOME/.local/bin"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="https://github.com/XenomorphSk/MRROBOT.git"
REPO_DIR="$DEST/repo"

echo -e "${VERMELHO}"
echo "  instalando MR. ROBOT..."
echo -e "${RST}"

# ---------------------------------------------------------------------------
# 1. dependencias de sistema
# ---------------------------------------------------------------------------
log "verificando dependencias de sistema"
sudo apt-get update -qq || warn "apt update falhou (sem rede?), seguindo"

PACOTES="python3 python3-pip python3-requests nmap"
for p in $PACOTES; do
    if ! dpkg -s "$p" >/dev/null 2>&1; then
        warn "instalando $p"
        sudo apt-get install -y -qq "$p" || warn "nao consegui instalar $p"
    fi
done

# ferramentas de recon opcionais (nao quebra se faltar rede)
for t in whatweb gobuster nikto nuclei sqlmap; do
    command -v "$t" >/dev/null 2>&1 || warn "opcional ausente: $t (instale depois com apt install $t)"
done

# ---------------------------------------------------------------------------
# 2. Ollama (cerebro)
# ---------------------------------------------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
    log "instalando Ollama"
    curl -fsSL https://ollama.com/install.sh | sh || warn "instalacao do Ollama falhou"
else
    log "Ollama ja instalado"
fi

# ---------------------------------------------------------------------------
# 3. instala o agente em ~/.mrrobot (clona do GitHub)
# ---------------------------------------------------------------------------
log "instalando o agente em $DEST"
mkdir -p "$DEST" "$BIN"

if ! command -v git >/dev/null 2>&1; then
    sudo apt-get install -y -qq git || err "git nao instalado e sem rede"
fi

if [ -d "$REPO_DIR/.git" ]; then
    log "repo ja existe, atualizando"
    git -C "$REPO_DIR" pull --ff-only || warn "git pull falhou (sem rede?), usando o que ja tem"
else
    log "clonando $REPO_URL"
    if git clone --depth 1 "$REPO_URL" "$REPO_DIR"; then
        log "repo clonado"
    else
        warn "clone falhou (sem rede?). Tentando usar copia local"
        [ -f "$SRC_DIR/mr_robot.py" ] && mkdir -p "$REPO_DIR" && cp "$SRC_DIR/mr_robot.py" "$REPO_DIR/"
    fi
fi

# instala o script a partir do repo
if [ -f "$REPO_DIR/mr_robot.py" ]; then
    cp "$REPO_DIR/mr_robot.py" "$DEST/mr_robot.py"
else
    err "mr_robot.py nao encontrado. Verifique o repo ou a rede."
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. comando global 'mrrobot' que roda na PASTA ATUAL
# ---------------------------------------------------------------------------
log "criando o comando 'mrrobot'"
cat > "$BIN/mrrobot" <<'WRAPPER'
#!/usr/bin/env bash
# roda o MR. ROBOT usando o diretorio atual como workdir (igual ao claude code)
export MRROBOT_WORKDIR="$(pwd)"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"
exec python3 "$HOME/.mrrobot/mr_robot.py" "$@"
WRAPPER
chmod +x "$BIN/mrrobot"

# garante que ~/.local/bin esta no PATH
SHELL_RC="$HOME/.zshrc"; [ -n "${BASH_VERSION:-}" ] && SHELL_RC="$HOME/.bashrc"
if ! echo "$PATH" | grep -q "$BIN"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
    warn "adicionei ~/.local/bin ao PATH em $SHELL_RC (abra um novo terminal ou rode: source $SHELL_RC)"
fi

# ---------------------------------------------------------------------------
# 5. script de atualizacao
# ---------------------------------------------------------------------------
log "instalando o atualizador"
cat > "$DEST/update.sh" <<'UPDATE'
#!/usr/bin/env bash
# Atualiza o que e do MR. ROBOT. NAO aplica apt upgrade sozinho: so avisa.
set -uo pipefail
DEST="$HOME/.mrrobot"
LOG="$DEST/update.log"
echo "=== update $(date '+%Y-%m-%d %H:%M') ===" >> "$LOG"

# 1. o proprio script, via git pull do repo oficial
REPO_DIR="$DEST/repo"
if [ -d "$REPO_DIR/.git" ]; then
    if git -C "$REPO_DIR" pull --ff-only >> "$LOG" 2>&1; then
        cp "$REPO_DIR/mr_robot.py" "$DEST/mr_robot.py"
        echo "script atualizado via git" >> "$LOG"
    else
        echo "git pull falhou (sem rede?)" >> "$LOG"
    fi
fi

# 2. templates do nuclei (vuln novas saem toda hora)
command -v nuclei >/dev/null 2>&1 && nuclei -update-templates >> "$LOG" 2>&1

# 3. modelos do ollama ja baixados (pega novas versoes do mesmo tag)
if command -v ollama >/dev/null 2>&1; then
    ollama list 2>/dev/null | awk 'NR>1{print $1}' | while read -r m; do
        [ -n "$m" ] && ollama pull "$m" >> "$LOG" 2>&1
    done
fi

# 4. checa updates de sistema SEM aplicar (seguranca: nao quebra pentest em andamento)
PEND=$(apt list --upgradable 2>/dev/null | grep -c upgradable || true)
if [ "$PEND" -gt 0 ]; then
    echo "AVISO: $PEND pacotes de sistema com update disponivel. Rode 'sudo apt upgrade' quando quiser." >> "$LOG"
fi
echo "update concluido" >> "$LOG"
UPDATE
chmod +x "$DEST/update.sh"

# ---------------------------------------------------------------------------
# 6. agenda a atualizacao periodica (systemd timer, com fallback pra cron)
# ---------------------------------------------------------------------------
log "agendando atualizacao periodica (semanal)"
if command -v systemctl >/dev/null 2>&1; then
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/mrrobot-update.service" <<EOF
[Unit]
Description=Atualizacao do MR. ROBOT
[Service]
Type=oneshot
ExecStart=$DEST/update.sh
EOF
    cat > "$HOME/.config/systemd/user/mrrobot-update.timer" <<EOF
[Unit]
Description=Atualizacao semanal do MR. ROBOT
[Timer]
OnCalendar=weekly
Persistent=true
[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now mrrobot-update.timer 2>/dev/null \
        && log "timer systemd ativo (roda semanalmente)" \
        || warn "nao consegui ativar o timer (systemd --user indisponivel). Use o cron abaixo."
else
    (crontab -l 2>/dev/null | grep -v mrrobot/update.sh; echo "0 9 * * 1 $DEST/update.sh") | crontab - \
        && log "cron semanal instalado (segunda 9h)"
fi

echo
log "pronto. abra um novo terminal e rode:  ${AMARELO}mrrobot${RST}"
echo -e "${DIM}   em qualquer pasta, ele gera arquivos ali mesmo.${RST}"
echo -e "${DIM}   modo pentest:  mrrobot --pentest${RST}"
echo -e "${DIM}   atualizar na mao:  ~/.mrrobot/update.sh${RST}"
