#!/bin/bash
# Double-click: serve the PRODUCTION build (dist/) the way nginx will, on http://localhost:4173
#   http://localhost:4173/                                         -> checkout.mastertherapy.example
#   http://localhost:4173/?site=checkout.harborwellness.example    -> Harbor Wellness
#   http://localhost:4173/?site=checkout.glowhealth.example        -> Glow Health
cd "$(dirname "$0")" || exit 1
if ! command -v npm >/dev/null 2>&1; then
  export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
  [ -x /opt/homebrew/bin/npm ] && export PATH="/opt/homebrew/bin:$PATH"
fi
[ -d node_modules ] || npm install --no-audit --no-fund
echo "== Building production bundle =="
npm run package || { echo "Build failed. Press Enter to close."; read; exit 1; }
echo
echo "== Demo running: http://localhost:4173  (Ctrl+C to stop) =="
(sleep 3; open "http://localhost:4173/") &
npx vite preview --port 4173 --strictPort
echo; echo "== Stopped. Press Enter to close. =="; read
