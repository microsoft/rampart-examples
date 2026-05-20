# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Auth injection protocols and built-in implementations.

Each injector is a callable that modifies a headers dict in-place,
adding the appropriate authentication header(s) for a provider.
"""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

try:
    from azure.identity.aio import get_bearer_token_provider as _imported_token_provider

    _get_bearer_token_provider: Any = _imported_token_provider
except ImportError:  # azure-identity is an optional dependency
    _get_bearer_token_provider = None


@runtime_checkable
class AuthInjector(Protocol):
    """Protocol for sync auth injection."""

    def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]: ...


@runtime_checkable
class AsyncAuthInjector(Protocol):
    """Protocol for async auth injection (e.g., AzureTokenAuth)."""

    def __call__(
        self, headers: dict[str, str], method: str, url: str
    ) -> Awaitable[dict[str, str]]: ...


@dataclass(frozen=True, slots=True)
class BearerTokenAuth:
    """Injects ``Authorization: Bearer <token>``. Works for OpenAI, Together, Groq, etc."""

    token: str
    header: str = "Authorization"

    def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]:
        headers[self.header] = f"Bearer {self.token}"
        return headers


@dataclass(frozen=True, slots=True)
class ApiKeyHeaderAuth:
    """Injects a raw API key into a named header. Works for Anthropic (x-api-key), etc."""

    key: str
    header: str = "x-api-key"

    def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]:
        headers[self.header] = self.key
        return headers


@dataclass(frozen=True, slots=True)
class CompositeAuth:
    """Chains multiple sync injectors."""

    injectors: tuple[AuthInjector, ...]

    def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]:
        for injector in self.injectors:
            headers = injector(headers, method, url)
        return headers


@dataclass(frozen=True, slots=True)
class StaticHeaderAuth:
    """Injects a fixed header value. Useful for version headers, org IDs, etc."""

    header: str
    value: str

    def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]:
        headers[self.header] = self.value
        return headers


class EnvVarAuth:
    """Resolves an API key from an environment variable at request time.

    The environment variable is looked up on every request, not at
    construction time.  This allows key rotation without restarting
    the proxy.  The variable must be set and non-empty at the time
    of each request or a ``RuntimeError`` is raised.
    """

    def __init__(
        self,
        *,
        env_var: str,
        header: str = "Authorization",
        prefix: str = "Bearer",
    ) -> None:
        self.env_var = env_var
        self.header = header
        self.prefix = prefix

    def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]:
        value = os.environ.get(self.env_var)
        if not value:
            msg = f"Auth env var {self.env_var!r} is not set or empty"
            raise RuntimeError(msg)
        headers[self.header] = f"{self.prefix} {value}" if self.prefix else value
        return headers


class AzureTokenAuth:
    """Async auth injector for Azure AD token-based authentication.

    Uses DefaultAzureCredential from azure.identity.aio (via ``az login``)
    to acquire and automatically refresh Bearer tokens.
    """

    def __init__(
        self,
        *,
        credential: Any | None = None,
        scope: str = "https://cognitiveservices.azure.com/.default",
        token_provider: Callable[[], Awaitable[str]] | None = None,
        header: str = "Authorization",
    ) -> None:
        if token_provider is not None:
            self._token_provider = token_provider
        elif credential is not None:
            if _get_bearer_token_provider is None:
                msg = (
                    "azure-identity is required for AzureTokenAuth. "
                    "Install with: pip install azure-identity azure-core"
                )
                raise ImportError(msg)
            self._token_provider = _get_bearer_token_provider(credential, scope)
        else:
            msg = "Provide either 'credential' or 'token_provider'"
            raise ValueError(msg)
        self._header = header

    async def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]:
        token = await self._token_provider()
        headers[self._header] = f"Bearer {token}"
        return headers


class AsyncCompositeAuth:
    """Chains multiple injectors where one or more may be async."""

    def __init__(self, *, injectors: tuple[Any, ...]) -> None:
        self._injectors = injectors

    async def __call__(self, headers: dict[str, str], method: str, url: str) -> dict[str, str]:
        for injector in self._injectors:
            result = injector(headers, method, url)
            if inspect.isawaitable(result):
                headers = await result
            else:
                headers = result
        return headers
