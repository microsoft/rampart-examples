# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Health and tool-metadata routes.

Side-effect free: neither route imports ``openai`` or instantiates
an agent. ``/api/health`` reads the env-var matrix via
``helpdesk_agent.providers.detect_provider``.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from helpdesk_agent.agent import build_agent
from helpdesk_agent.manifest import HELPDESK_MANIFEST
from helpdesk_agent.providers import detect_provider
from pydantic import BaseModel

from helpdesk_ui.agent_runner import AgentFactory
from helpdesk_ui.routes.chat import get_agent_factory

router = APIRouter()

ProviderId = Literal["openai", "azure-openai-key", "azure-openai-entra", "fake"]


class HealthResponse(BaseModel):
    """Minimal health readout for the UI provider pill."""

    agent_configured: bool
    provider: ProviderId | None
    model: str | None
    versions: dict[str, str]


class ToolInfo(BaseModel):
    """Manifest-derived tool metadata for inline tooltips."""

    name: str
    description: str
    parameters: dict[str, str]


def _safe_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


@router.get("/health", response_model=HealthResponse)
async def health(
    agent_factory: Annotated[AgentFactory, Depends(get_agent_factory)],
) -> HealthResponse:
    """Return the current agent configuration.

    When tests inject a fake ``agent_factory`` we report
    ``provider="fake"`` and skip the env-var sniff so snapshots stay
    deterministic.
    """
    if agent_factory is not build_agent:
        return HealthResponse(
            agent_configured=True,
            provider="fake",
            model=None,
            versions=_versions(),
        )
    cfg = detect_provider()
    return HealthResponse(
        agent_configured=cfg is not None,
        provider=cfg.kind if cfg else None,
        model=cfg.model if cfg else None,
        versions=_versions(),
    )


@router.get("/tools", response_model=list[ToolInfo])
async def tools() -> list[ToolInfo]:
    """Return the agent's declared tools and their descriptions."""
    return [
        ToolInfo(
            name=t.name,
            description=t.description,
            parameters=dict(t.parameters),
        )
        for t in HELPDESK_MANIFEST.tools
    ]


def _versions() -> dict[str, str]:
    return {
        "rampart": _safe_version("rampart"),
        "agent_framework": _safe_version("agent-framework-core"),
        "helpdesk_agent": _safe_version("helpdesk-agent"),
    }
