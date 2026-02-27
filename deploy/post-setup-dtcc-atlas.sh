#!/usr/bin/env bash
set -euo pipefail

# Post-setup script for dtcc-atlas
# Installs Node.js, builds the Svelte frontend, and copies to static dir.

# Install Node.js 22 LTS via nodesource
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
fi
echo "[OK] Node.js $(node --version) installed"

# Build frontend
cd ~/${APP_NAME}/frontend
npm install
npm run build

echo "[OK] Frontend built"
