# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Auth-injecting reverse proxy for sandboxed AI agents.

Submodules:
    injectors  — Auth injection protocols and built-in implementations.
    routes     — ProviderRoute, config loading, and env-var fallback.
    server     — The AuthProxy aiohttp server and request logger.
    cli        — Command-line entry point (``auth-proxy`` script).
"""

from openclaw.auth.injectors import (
    ApiKeyHeaderAuth,
    AsyncAuthInjector,
    AsyncCompositeAuth,
    AuthInjector,
    AzureTokenAuth,
    BearerTokenAuth,
    CompositeAuth,
    EnvVarAuth,
    StaticHeaderAuth,
)
from openclaw.auth.routes import ProviderRoute, routes_from_config, routes_from_env
from openclaw.auth.server import AuthProxy, JsonlRequestLogger, RequestLogger

__all__ = [
    "ApiKeyHeaderAuth",
    "AsyncAuthInjector",
    "AsyncCompositeAuth",
    "AuthInjector",
    "AuthProxy",
    "AzureTokenAuth",
    "BearerTokenAuth",
    "CompositeAuth",
    "EnvVarAuth",
    "JsonlRequestLogger",
    "ProviderRoute",
    "RequestLogger",
    "StaticHeaderAuth",
    "routes_from_config",
    "routes_from_env",
]
