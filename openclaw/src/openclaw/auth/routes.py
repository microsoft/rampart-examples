# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Provider routes: mapping local path prefixes to remote endpoints with auth.

Also handles loading routes from config files and environment variables.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openclaw.auth.injectors import (
    ApiKeyHeaderAuth,
    AsyncAuthInjector,
    AuthInjector,
    AzureTokenAuth,
    BearerTokenAuth,
    CompositeAuth,
    StaticHeaderAuth,
)

try:
    from azure.identity.aio import DefaultAzureCredential as _DefaultAzureCredential
except ImportError:  # azure-identity is an optional dependency
    _DefaultAzureCredential = None  # type: ignore[assignment,misc]

logger = logging.getLogger("auth_proxy")


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """Maps a local path prefix to a remote endpoint with auth injection."""

    name: str
    path_prefix: str
    target_base_url: str
    auth: AuthInjector | AsyncAuthInjector
    extra_headers: dict[str, str] = field(default_factory=dict)


# Config file management

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "auth_proxy"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

_PROVIDER_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "openai": ("/openai", "https://api.openai.com", "bearer"),
    "anthropic": ("/anthropic", "https://api.anthropic.com", "anthropic"),
    "groq": ("/groq", "https://api.groq.com", "bearer"),
    "together": ("/together", "https://api.together.xyz", "bearer"),
    "azure": ("/azure", "", "azure_ad"),
}

CONFIG_TEMPLATE: dict[str, Any] = {
    "_comment": (
        "Auth proxy config. Keys are read from this file -- not from env vars. "
        "Ensure this file is chmod 600. For Azure AD auth, just set the "
        "base_url and auth='azure_ad'; no api_key needed (uses az login)."
    ),
    "providers": {
        "openai": {
            "enabled": False,
            "api_key": "sk-YOUR-KEY-HERE",
            "base_url": "https://api.openai.com",
            "auth": "bearer",
        },
        "anthropic": {
            "enabled": False,
            "api_key": "sk-ant-YOUR-KEY-HERE",
            "base_url": "https://api.anthropic.com",
            "auth": "anthropic",
        },
        "azure": {
            "enabled": True,
            "base_url": "https://YOUR-RESOURCE.openai.azure.com",
            "auth": "azure_ad",
            "scope": "https://cognitiveservices.azure.com/.default",
            "_comment": "Uses az login -- no api_key needed.",
        },
        "groq": {
            "enabled": False,
            "api_key": "gsk_YOUR-KEY-HERE",
            "base_url": "https://api.groq.com",
            "auth": "bearer",
        },
    },
}


def _check_config_permissions(path: Path) -> None:
    """Warn if the config file is readable by group or others."""
    if not path.exists() or sys.platform == "win32":
        return
    mode = path.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        logger.warning(
            "Config file %s is readable by group/others (mode %o). "
            "Run: chmod 600 %s",
            path,
            stat.S_IMODE(mode),
            path,
        )


def init_config(config_path: Path | None = None) -> Path:
    """Create a template config file with locked-down permissions."""
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        logger.info("Config already exists at %s — not overwriting.", path)
        return path

    with open(path, "w") as f:
        json.dump(CONFIG_TEMPLATE, f, indent=2)

    if sys.platform != "win32":
        path.chmod(0o600)

    logger.info("Created config at %s (mode 600)", path)
    return path


def _build_auth_for_provider(
    *,
    name: str,
    provider_cfg: dict[str, Any],
) -> AuthInjector | AsyncAuthInjector:
    """Build the appropriate auth injector from a provider config block."""
    auth_type = provider_cfg.get("auth", "bearer")

    if auth_type == "azure_ad":
        if _DefaultAzureCredential is None:
            raise ImportError(
                f"Provider '{name}' uses azure_ad auth but azure-identity "
                "is not installed. Run: pip install azure-identity azure-core"
            )
        scope = provider_cfg.get(
            "scope", "https://cognitiveservices.azure.com/.default"
        )
        return AzureTokenAuth(
            credential=_DefaultAzureCredential(), scope=scope
        )

    if auth_type == "anthropic":
        api_key = provider_cfg.get("api_key", "")
        if not api_key:
            raise ValueError(f"Provider '{name}': auth=anthropic requires api_key")
        return CompositeAuth((
            ApiKeyHeaderAuth(api_key, header="x-api-key"),
            StaticHeaderAuth(
                "anthropic-version",
                provider_cfg.get("anthropic_version", "2023-06-01"),
            ),
        ))

    if auth_type == "api_key_header":
        api_key = provider_cfg.get("api_key", "")
        header = provider_cfg.get("header", "api-key")
        if not api_key:
            raise ValueError(f"Provider '{name}': auth=api_key_header requires api_key")
        return StaticHeaderAuth(header, api_key)

    # Default: bearer token
    api_key = provider_cfg.get("api_key", "")
    if not api_key:
        raise ValueError(f"Provider '{name}': auth=bearer requires api_key")
    return BearerTokenAuth(api_key)


def routes_from_config(config_path: Path | None = None) -> list[ProviderRoute]:
    """Build routes from a config file."""
    path = config_path or DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.warning("No config file at %s", path)
        return []

    _check_config_permissions(path)

    try:
        with open(path) as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in config file %s: %s", path, exc)
        return []

    if not isinstance(config, dict):
        logger.error("Config file %s: expected a JSON object at top level", path)
        return []

    providers = config.get("providers", {})
    routes: list[ProviderRoute] = []

    for name, provider_cfg in providers.items():
        if not provider_cfg.get("enabled", True):
            logger.debug("Skipping disabled provider: %s", name)
            continue

        base_url = provider_cfg.get("base_url", "")
        if not base_url:
            if name in _PROVIDER_DEFAULTS:
                base_url = _PROVIDER_DEFAULTS[name][1]
            if not base_url:
                logger.warning("Provider '%s': no base_url, skipping.", name)
                continue

        path_prefix = provider_cfg.get(
            "path_prefix",
            _PROVIDER_DEFAULTS.get(name, (f"/{name}",))[0],
        )

        try:
            auth = _build_auth_for_provider(name=name, provider_cfg=provider_cfg)
        except (ValueError, ImportError) as exc:
            logger.warning("Provider '%s': %s — skipping.", name, exc)
            continue

        extra_headers = provider_cfg.get("extra_headers", {})

        routes.append(
            ProviderRoute(
                name=name,
                path_prefix=path_prefix,
                target_base_url=base_url,
                auth=auth,
                extra_headers=extra_headers,
            )
        )
        logger.info(
            "  %s → %s (%s auth)", path_prefix, base_url,
            provider_cfg.get("auth", "bearer"),
        )

    return routes


def routes_from_env() -> list[ProviderRoute]:
    """Fallback: build routes from environment variables."""
    routes: list[ProviderRoute] = []
    logger.info("Reading provider credentials from environment variables")

    if key := os.environ.get("OPENAI_API_KEY"):
        routes.append(ProviderRoute(
            name="openai", path_prefix="/openai",
            target_base_url="https://api.openai.com",
            auth=BearerTokenAuth(key)))

    if key := os.environ.get("ANTHROPIC_API_KEY"):
        routes.append(ProviderRoute(
            name="anthropic", path_prefix="/anthropic",
            target_base_url="https://api.anthropic.com",
            auth=CompositeAuth((
                ApiKeyHeaderAuth(key, header="x-api-key"),
                StaticHeaderAuth("anthropic-version", "2023-06-01")))))

    if key := os.environ.get("GROQ_API_KEY"):
        routes.append(ProviderRoute(
            name="groq", path_prefix="/groq",
            target_base_url="https://api.groq.com",
            auth=BearerTokenAuth(key)))

    if key := os.environ.get("TOGETHER_API_KEY"):
        routes.append(ProviderRoute(
            name="together", path_prefix="/together",
            target_base_url="https://api.together.xyz",
            auth=BearerTokenAuth(key)))

    if base := os.environ.get("AZURE_OPENAI_ENDPOINT"):
        if _DefaultAzureCredential is None:
            logger.warning("AZURE_OPENAI_ENDPOINT set but azure-identity not installed.")
        else:
            scope = os.environ.get(
                "AZURE_OPENAI_SCOPE",
                "https://cognitiveservices.azure.com/.default",
            )
            routes.append(ProviderRoute(
                name="azure-openai-aad", path_prefix="/azure",
                target_base_url=base,
                auth=AzureTokenAuth(
                    credential=_DefaultAzureCredential(), scope=scope)))

    return routes
