#!/data/data/com.termux/files/usr/bin/bash
# ============================================================================
# NEXO TERMINAL — Instalador para Termux (Android ARM64, sin root)
# Uso:  bash install.sh
# ============================================================================
set -euo pipefail

VERDE='\033[0;32m'; ROJO='\033[0;31m'; AMARILLO='\033[0;33m'; CIAN='\033[0;36m'; SIN='\033[0m'
ok()   { echo -e "${VERDE}✔${SIN} $1"; }
warn() { echo -e "${AMARILLO}⚠${SIN} $1"; }
err()  { echo -e "${ROJO}✖${SIN} $1"; }
info() { echo -e "${CIAN}ℹ${SIN} $1"; }

echo
echo "  NEXO TERMINAL — instalador para Termux"
echo "  Tu IA · Tu Terminal · Tu Proyecto"
echo

# 1) Comprobar entorno -------------------------------------------------------
if [ -n "${PREFIX:-}" ] && echo "$PREFIX" | grep -q "com.termux"; then
    ok "Entorno Termux detectado ($PREFIX)."
else
    warn "No parece Termux; el instalador continuará de todos modos (Linux/macOS)."
fi

command -v python >/dev/null 2>&1 || { err "python no encontrado. Ejecuta: pkg install python"; exit 1; }
ok "Python: $(python --version 2>&1)"

# 2) Dependencias del sistema -------------------------------------------------
info "Actualizando paquetes (pkg update)…"
pkg update -y >/dev/null 2>&1 || warn "pkg update falló; se continúa igualmente."

NEED=""
command -v git >/dev/null 2>&1 || NEED="$NEED git"
if [ -n "$NEED" ]; then
    info "Instalando dependencias del sistema:$NEED"
    pkg install -y $NEED
fi
command -v git >/dev/null 2>&1 && ok "git disponible." || warn "git NO disponible: /git no funcionará hasta 'pkg install git'."

if command -v gh >/dev/null 2>&1; then
    ok "GitHub CLI (gh) disponible."
else
    warn "gh no instalado (opcional, para /github). Instala con: pkg install gh"
fi

# 3) Dependencias de Python (todas puras, sin compilación) --------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
info "Instalando dependencias de Python (rich, prompt_toolkit, httpx)…"
python -m pip install --upgrade pip >/dev/null 2>&1 || true
python -m pip install -r requirements.txt

# 4) Instalar NEXO (punto de entrada 'nexo') ----------------------------------
info "Instalando NEXO TERMINAL…"
python -m pip install .
ok "Paquete instalado."

# 5) Configuración inicial -----------------------------------------------------
NEXO_DIR="${NEXO_HOME:-$HOME/.nexo}"
mkdir -p "$NEXO_DIR"
if [ ! -f "$NEXO_DIR/config.json" ]; then
    cp config.example.json "$NEXO_DIR/config.json" 2>/dev/null || true
    if [ -f "$NEXO_DIR/config.json" ]; then
        ok "Configuración inicial creada en $NEXO_DIR/config.json (edítala o usa /provider add)."
    else
        warn "No se pudo copiar config.example.json; crea la configuración con 'nexo init-config'."
    fi
else
    info "Ya existe $NEXO_DIR/config.json; se respeta."
fi

# 6) Diagnóstico ----------------------------------------------------------------
echo
info "Ejecutando diagnóstico (nexo doctor)…"
nexo doctor || warn "El diagnóstico reportó avisos: revisa la salida anterior."

echo
ok "Instalación completada."
echo
echo "  Ejecuta:            nexo"
echo "  Configura un proveedor dentro de NEXO:"
echo "    /provider add ollama-local ollama http://127.0.0.1:11434 llama3.2"
echo "    /provider add nube openai https://api.openai.com/v1 gpt-4o-mini"
echo "    /provider key nube        (guarda la API key de forma protegida)"
echo "    /provider use nube"
echo
echo "  Documentación: README.md y docs/TROUBLESHOOTING.md"
echo "  NEXO TERMINAL: TU IA, TU TERMINAL, TU PROYECTO."
