#!/bin/sh
set -e

GREEN='\033[38;2;0;230;118m'
CYAN='\033[36m'
YELLOW='\033[33m'
RESET='\033[0m'
BOLD='\033[1m'

PORT=${PORT:-3000}
HOST="0.0.0.0"

echo "${GREEN}${BOLD}"
echo "Iniciando NEXO Terminal en el puerto $PORT..."
echo "${RESET}"

# Abrir navegador en Termux o Linux si está disponible
(
  sleep 1.5
  if command -v termux-open-url >/dev/null 2>&1; then
    termux-open-url "http://localhost:$PORT"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:$PORT" >/dev/null 2>&1 || true
  fi
) &

exec node src/server.js
