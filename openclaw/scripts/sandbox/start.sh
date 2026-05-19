#!/usr/bin/env bash
# Start the auth-proxy bridge, configure OpenClaw, and launch the TUI.
#
# Environment variables:
#   BRIDGE_PORT      - Local bridge port (default: 54321)
#   AUTH_PROXY_PORT  - Host auth-proxy port (default: 12435)
#   PROVIDERS        - Comma-separated provider filter (default: all)
#   MODELS_B64       - Base64-encoded JSON model overrides (optional)
set -euo pipefail

BRIDGE_PORT="${BRIDGE_PORT:-54321}"
AUTH_PROXY_PORT="${AUTH_PROXY_PORT:-12435}"

# Start the bridge

echo "Starting auth-proxy bridge..."
AUTH_PROXY_PORT="$AUTH_PROXY_PORT" BRIDGE_PORT="$BRIDGE_PORT" \
    node ~/auth-proxy-bridge.js > /tmp/bridge.log 2>&1 &
BRIDGE_PID=$!

echo -n "Waiting for bridge"
for i in $(seq 1 15); do
    if curl -s "http://127.0.0.1:${BRIDGE_PORT}/health" > /dev/null 2>&1; then
        echo " ready! (${i}s)"
        break
    fi
    if ! kill -0 "${BRIDGE_PID}" 2>/dev/null; then
        echo ""
        echo "ERROR: Bridge crashed. Log:"
        cat /tmp/bridge.log
        exit 1
    fi
    echo -n "."
    sleep 1
done

if ! curl -s "http://127.0.0.1:${BRIDGE_PORT}/health" > /dev/null 2>&1; then
    echo ""
    echo "ERROR: Bridge failed to connect to auth-proxy on host:${AUTH_PROXY_PORT}"
    echo "       Is auth-proxy running? Start it with: auth-proxy serve"
    echo "       Bridge log:"
    cat /tmp/bridge.log
    exit 1
fi

echo "Auth proxy routes:"
curl -s "http://127.0.0.1:${BRIDGE_PORT}/health" | python3 -m json.tool 2>/dev/null || true

# Configure OpenClaw

BRIDGE_URL="http://127.0.0.1:${BRIDGE_PORT}" \
    PROVIDERS="${PROVIDERS:-}" \
    MODELS_B64="${MODELS_B64:-}" \
    python3 ~/configure-openclaw.py

echo ""
echo "=================================="
echo "  Bridge: 127.0.0.1:${BRIDGE_PORT}"
echo "  Auth proxy: host:${AUTH_PROXY_PORT}"
echo "=================================="
echo ""

# Start OpenClaw gateway

export OPENCLAW_GATEWAY_TOKEN="local-sandbox-token"
echo "Starting OpenClaw gateway..."
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    openclaw gateway > /tmp/openclaw-gateway.log 2>&1 &
GATEWAY_PID=$!

echo -n "Waiting for gateway"
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:18789/health > /dev/null 2>&1; then
        echo " ready! (${i}s)"
        break
    fi
    if ! kill -0 "${GATEWAY_PID}" 2>/dev/null; then
        echo ""
        echo "ERROR: Gateway crashed. Log:"
        cat /tmp/openclaw-gateway.log
        exit 1
    fi
    echo -n "."
    sleep 1
done

# Launch TUI

exec openclaw tui
