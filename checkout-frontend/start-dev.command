#!/bin/bash
# Double-click to run the checkout locally (macOS).
cd "$(dirname "$0")" || exit 1
if ! command -v npm >/dev/null 2>&1; then
  export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  [ -x /opt/homebrew/bin/npm ] && export PATH="/opt/homebrew/bin:$PATH"
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js is not installed. Install it from https://nodejs.org (LTS), then run this again."; read; exit 1
fi
echo "node $(node -v)"
[ -d node_modules ] || npm install --no-audit --no-fund
(sleep 4; open "http://localhost:5173/") &
npm run dev
echo; echo "== Stopped. Press Enter to close. =="; read
