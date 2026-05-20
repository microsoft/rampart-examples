# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Configure OpenClaw to route LLM requests through the auth-proxy bridge.

Auto-discovers available routes from the auth-proxy health endpoint
and configures OpenClaw providers accordingly.

Environment variables:
    BRIDGE_URL   - Bridge URL (default: http://127.0.0.1:54321)
    PROVIDERS    - Comma-separated provider filter (default: all discovered routes)
    MODELS_B64   - Base64-encoded JSON mapping provider names to model arrays
                   Example: {"openai": [{"id": "gpt-5.1", "name": "GPT 5.1"}]}
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

# Map provider names to OpenClaw API types.
# Add entries here to support new providers.
DEFAULT_API_TYPE = "openai-completions"

API_TYPE_MAP = {
    "openai": DEFAULT_API_TYPE,
    "azure": DEFAULT_API_TYPE,
    "groq": DEFAULT_API_TYPE,
    "together": DEFAULT_API_TYPE,
    "anthropic": "anthropic-messages",
}

DEFAULT_BRIDGE_URL = "http://127.0.0.1:54321"
OPENCLAW_CONFIG_PATH = "~/.openclaw/openclaw.json"
OPENCLAW_GATEWAY_PORT = 18789


def discover_routes(bridge_url):
    """Query the auth-proxy health endpoint for available routes."""
    url = f"{bridge_url}/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("routes", [])
    except Exception:
        return []


def load_models_override():
    """Load model overrides from MODELS_B64 environment variable."""
    b64 = os.environ.get("MODELS_B64", "")
    if not b64:
        return {}
    try:
        raw = base64.b64decode(b64).decode("utf-8")
        return json.loads(raw)
    except Exception:
        return {}


def main() -> None:
    bridge_url = os.environ.get("BRIDGE_URL", DEFAULT_BRIDGE_URL)
    providers_env = os.environ.get("PROVIDERS", "").strip()
    provider_filter = (
        {p.strip() for p in providers_env.split(",") if p.strip()} if providers_env else None
    )
    models_override = load_models_override()

    # Discover routes from auth-proxy
    routes = discover_routes(bridge_url)
    if not routes:
        sys.exit(1)

    # Load existing OpenClaw config
    config_path = os.path.expanduser(OPENCLAW_CONFIG_PATH)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}

    cfg["models"] = cfg.get("models", {})
    cfg["models"]["mode"] = "merge"
    cfg["models"]["providers"] = cfg["models"].get("providers", {})

    # Configure each discovered route as an OpenClaw provider
    configured = []
    for route in routes:
        name = route["name"]
        prefix = route["prefix"]

        if provider_filter and name not in provider_filter:
            continue

        api_type = API_TYPE_MAP.get(name, DEFAULT_API_TYPE)
        models = models_override.get(name, [])

        cfg["models"]["providers"][name] = {
            "baseUrl": bridge_url + prefix,
            "apiKey": "proxy-managed",
            "api": api_type,
            "models": models,
        }
        configured.append(name)

    if not configured:
        sys.exit(1)

    # Set default model from the first provider that has models
    for name in configured:
        models = cfg["models"]["providers"][name].get("models", [])
        if models:
            cfg.setdefault("agents", {}).setdefault("defaults", {})["model"] = {
                "primary": f"{name}/{models[0]['id']}"
            }
            break

    cfg["gateway"] = {"mode": "local", "port": OPENCLAW_GATEWAY_PORT}

    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)

    # Print summary
    for name in configured:
        provider = cfg["models"]["providers"][name]
        models = provider.get("models", [])
        ", ".join(m["id"] for m in models) if models else "(none)"


if __name__ == "__main__":
    main()
