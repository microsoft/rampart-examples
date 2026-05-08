# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Provider configuration parsed from the environment.

Single source of truth for the env-var matrix:

* ``OPENAI_API_KEY`` (+ optional ``OPENAI_MODEL``) → plain OpenAI.
* ``AZURE_OPENAI_ENDPOINT`` + ``AZURE_OPENAI_API_KEY`` → AOAI key auth.
* ``AZURE_OPENAI_ENDPOINT`` + ``AZURE_OPENAI_USE_AZURE_CREDENTIAL=true`` → AOAI Entra.

``detect_provider`` returns a typed ``ProviderConfig`` (discriminated by
``kind``) or ``None``. Each variant carries every value the agent needs
to construct a chat client, so callers don't read env vars themselves.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

_AZURE_TRUTHY = frozenset({"1", "true", "yes", "on"})

AOAI_NO_CRED_MSG = (
    "AZURE_OPENAI_ENDPOINT is set but no credential is configured. "
    "Set AZURE_OPENAI_API_KEY, or set "
    "AZURE_OPENAI_USE_AZURE_CREDENTIAL=true and install the "
    "'azure' extra (pip install -e '.[azure]') to use Entra ID. "
    "See .env.example for the full provider matrix."
)
NO_PROVIDER_MSG = (
    "No provider configured. Set one of: OPENAI_API_KEY (OpenAI direct), "
    "AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY (Azure OpenAI with API key), "
    "or AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_USE_AZURE_CREDENTIAL=true "
    "(Azure OpenAI with Entra ID). See .env.example for the full provider matrix."
)


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    """Plain OpenAI: ``OPENAI_API_KEY`` (+ optional ``OPENAI_MODEL``)."""

    api_key: str
    model: str
    kind: Literal["openai"] = "openai"


@dataclass(frozen=True, slots=True)
class AzureKeyConfig:
    """Azure OpenAI with an API key."""

    endpoint: str
    api_key: str
    model: str | None
    api_version: str | None
    kind: Literal["azure-openai-key"] = "azure-openai-key"


@dataclass(frozen=True, slots=True)
class AzureEntraConfig:
    """Azure OpenAI with Entra ID (``DefaultAzureCredential``)."""

    endpoint: str
    model: str | None
    api_version: str | None
    kind: Literal["azure-openai-entra"] = "azure-openai-entra"


ProviderConfig = OpenAIConfig | AzureKeyConfig | AzureEntraConfig


def detect_provider() -> ProviderConfig | None:
    """Return the configured provider, or ``None`` if none is set.

    Returns ``None`` both when the environment names no provider AND
    when an Azure endpoint is set without a usable credential. Callers
    that need to distinguish "nothing set" from "AOAI misconfigured"
    should consult ``unconfigured_reason``.
    """
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if endpoint:
        api_version = os.getenv("AZURE_OPENAI_API_VERSION") or None
        model = os.getenv("AZURE_OPENAI_MODEL")
        if _is_azure_credential_enabled():
            return AzureEntraConfig(endpoint=endpoint, model=model, api_version=api_version)
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if api_key:
            return AzureKeyConfig(
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                api_version=api_version,
            )
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return OpenAIConfig(api_key=api_key, model=os.getenv("OPENAI_MODEL", "gpt-4o"))
    return None


def unconfigured_reason() -> str | None:
    """Return a user-facing reason when ``detect_provider()`` is ``None``.

    ``None`` when a provider IS configured. ``AOAI_NO_CRED_MSG`` when
    the AOAI endpoint is set but no credential. Otherwise
    ``NO_PROVIDER_MSG``.
    """
    if detect_provider() is not None:
        return None
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        return AOAI_NO_CRED_MSG
    return NO_PROVIDER_MSG


def _is_azure_credential_enabled() -> bool:
    return os.getenv("AZURE_OPENAI_USE_AZURE_CREDENTIAL", "").strip().lower() in _AZURE_TRUTHY
