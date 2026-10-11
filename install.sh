#!/bin/sh
set -e

GREEN='\033[38;2;0;230;118m'
CYAN='\033[36m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'
BOLD='\033[1m'

echo "${GREEN}${BOLD}"
echo " ███╗   ██╗███████╗██╗  ██╗ ██████╗ "
echo " ████╗  ██║██╔════╝╚██╗██╔╝██╔═══██╗"
echo " ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║"
echo " ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║"
echo " ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝"
echo " ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ "
echo "${RESET}"
echo "${CYAN}${BOLD}INSTALADOR DE NEXO TERMINAL PARA TERMUX / ANDROID${RESET}\n"

# 1. Comprobar Node.js
echo "${YELLOW}▶ Verificando entorno y herramientas...${RESET}"
if ! command -v node >/dev/null 2>&1; then
  echo "${RED}✘ Node.js no está instalado.${RESET}"
  echo "En Termux, ejecuta: pkg update && pkg install nodejs -y"
  exit 1
fi

NODE_VERSION=$(node -v)
echo "${GREEN}✔ Node.js detectado:${RESET} $NODE_VERSION"

# 2. Comprobar Git
if ! command -v git >/dev/null 2>&1; then
  echo "${YELLOW}⚠ Git no está instalado. Instalándolo en Termux es recomendado:${RESET} pkg install git -y"
else
  GIT_VERSION=$(git --version)
  echo "${GREEN}✔ Git detectado:${RESET} $GIT_VERSION"
fi

# 3. Permisos de almacenamiento en Android (Termux)
if [ -d "/data/data/com.termux" ]; then
  echo "${CYAN}ℹ Entorno Termux de Android detectado.${RESET}"
  if [ ! -d "$HOME/storage" ]; then
    echo "${YELLOW}ℹ Tip: Puedes ejecutar 'termux-setup-storage' si deseas autorizar acceso a /sdcard.${RESET}"
  fi
fi

# 4. Instalar dependencias npm
echo "\n${YELLOW}▶ Instalando dependencias de producción...${RESET}"
npm install --omit=dev --no-audit --no-fund

# 5. Permisos de ejecución
chmod +x bin/nexo.js
chmod +x start.sh

# 6. Crear enlace simbólico en Termux si está disponible el prefijo
if [ -d "$PREFIX/bin" ] && [ -w "$PREFIX/bin" ]; then
  ln -sf "$(pwd)/bin/nexo.js" "$PREFIX/bin/nexo"
  echo "${GREEN}✔ Comando global 'nexo' enlazado en $PREFIX/bin/nexo${RESET}"
fi

echo "\n${GREEN}${BOLD}✔ INSTALACIÓN COMPLETADA CON ÉXITO.${RESET}"
echo "Para iniciar NEXO Terminal, ejecuta:"
echo "  ${CYAN}./start.sh${RESET}  o  ${CYAN}node bin/nexo.js start${RESET}\n"
