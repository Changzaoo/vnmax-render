#!/usr/bin/env bash
# Prepara uma máquina Ubuntu 22.04/24.04 (VM por hora ou Google Colab) para
# renderizar os documentários dos países. Idempotente: rodar de novo só confere.
#
#   bash bootstrap.sh            usuário comum com sudo (VM) ou root (Colab)
#
# Instala: Node 22 (o hyperframes 0.8.143 exige node >= 22), as bibliotecas do
# Chrome headless, ffmpeg, fontes, python3; o hyperframes na versão FIXA do
# D:\vnmax-videos\package.json (0.8.143) em ~/vnmax-render/ e o Chrome que ele usa.
set -euo pipefail

HF_VERSAO="${HF_VERSAO:-0.8.143}"
NODE_MAIOR=22
BASE="${VNMAX_BASE:-$HOME/vnmax-render}"
export DEBIAN_FRONTEND=noninteractive

if [ "$(id -u)" = "0" ]; then SUDO=""; else SUDO="sudo"; fi
diz() { printf '\n== %s\n' "$*"; }

# ── pacotes do sistema ────────────────────────────────────────────────────
diz "pacotes do sistema (ffmpeg, bibliotecas do Chrome, fontes)"
. /etc/os-release
echo "sistema: $PRETTY_NAME"
PACOTES="ca-certificates curl gnupg xz-utils zstd rsync python3 ffmpeg
  libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2
  libxshmfence1 libx11-xcb1 libxcb1 libxext6 libxss1 libdbus-1-3 libasound2
  fonts-liberation fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji fontconfig"
# Ubuntu 24.04 renomeou várias bibliotecas com o sufixo t64 (libasound2t64,
# libcups2t64, libatk1.0-0t64…): usa o nome novo quando ele existe
[ -n "$(ls /var/lib/apt/lists/ 2>/dev/null | grep -v lock)" ] || $SUDO apt-get update -qq
FALTAM=""
for p in $PACOTES; do
  if apt-cache show "${p}t64" >/dev/null 2>&1; then p="${p}t64"; fi
  dpkg -s "$p" >/dev/null 2>&1 || FALTAM="$FALTAM $p"
done
if [ -n "$FALTAM" ]; then
  $SUDO apt-get update -qq
  # shellcheck disable=SC2086
  $SUDO apt-get install -y -qq --no-install-recommends $FALTAM
else
  echo "todos já instalados"
fi

# ── Node ──────────────────────────────────────────────────────────────────
diz "Node $NODE_MAIOR"
ATUAL=$(node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/' || echo 0)
if [ "${ATUAL:-0}" -lt "$NODE_MAIOR" ]; then
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAIOR}.x" -o /tmp/nodesource_setup.sh
  $SUDO bash /tmp/nodesource_setup.sh
  $SUDO apt-get install -y -qq nodejs
fi
hash -r
node -v; npm -v

# ── hyperframes na versão fixa ──────────────────────────────────────────────
diz "hyperframes $HF_VERSAO em $BASE"
mkdir -p "$BASE"/{pacotes,trabalho,saida,tmp,logs}
cd "$BASE"
if [ ! -f package.json ]; then
  cat > package.json <<JSON
{
  "name": "vnmax-render",
  "private": true,
  "dependencies": { "hyperframes": "$HF_VERSAO" }
}
JSON
fi
INSTALADA=$(node -p "try{require('./node_modules/hyperframes/package.json').version}catch(e){''}" 2>/dev/null || true)
if [ "$INSTALADA" != "$HF_VERSAO" ]; then
  npm install --no-audit --no-fund --save-exact "hyperframes@$HF_VERSAO"
fi
export HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1 HYPERFRAMES_NO_UPDATE_CHECK=1

diz "Chrome do hyperframes"
./node_modules/.bin/hyperframes browser ensure
./node_modules/.bin/hyperframes doctor || echo "(doctor apontou algo acima — confira; o render costuma funcionar mesmo assim)"

# ── scripts ao lado ───────────────────────────────────────────────────────
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$AQUI/render_remoto.py" ] && [ "$AQUI" != "$BASE" ]; then
  cp -f "$AQUI/render_remoto.py" "$BASE/"
fi

diz "pronto"
echo "núcleos: $(nproc)   memória: $(free -g | awk '/Mem:/{print $2" GB"}')   disco livre em $BASE: $(df -h "$BASE" | awk 'NR==2{print $4}')"
echo "ffmpeg: $(ffmpeg -version | head -1)"
echo "próximo: python3 $BASE/render_remoto.py $BASE/pacotes/<ISO>.tar.gz"
