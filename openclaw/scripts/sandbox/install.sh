#!/usr/bin/env bash
# Install OpenClaw and dependencies inside a Docker Sandbox.
# No arguments or environment variables needed.
set -euo pipefail

echo "[1/3] Installing Node.js 22..."
sudo npm install -g n
sudo n 22
hash -r

# ``jq`` is required by the integration-test conftest to prune stale
# ``plugins.load.paths`` entries from ``openclaw.json`` at session start.
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends jq

echo "[2/3] Installing OpenClaw..."
# Pinned to a specific version for reproducible builds.
# To update: check https://www.npmjs.com/package/openclaw for the latest release.
sudo npm install -g openclaw@2026.4.15

echo "[3/3] Running OpenClaw initial setup..."
openclaw setup --skip-interactive 2>/dev/null || true

echo "Install complete."
