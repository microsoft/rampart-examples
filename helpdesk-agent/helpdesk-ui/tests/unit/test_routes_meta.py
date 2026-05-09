# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the meta routes (``/api/health``, ``/api/tools``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from helpdesk_ui.app import create_app

if TYPE_CHECKING:
    import pytest


def test_health_with_fake_factory(client: TestClient) -> None:
    """Tests pass a fake builder; health reports it as ``provider="fake"``."""
    body = client.get("/api/health").json()
    assert body["agent_configured"] is True
    assert body["provider"] == "fake"
    assert body["model"] is None
    assert "rampart" in body["versions"]


def test_health_with_real_factory_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the default ``build_agent`` is used and no env vars are
    set, health reports ``agent_configured=False``."""
    for key in (
        "OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_USE_AZURE_CREDENTIAL",
    ):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app()) as c:
        body = c.get("/api/health").json()
    assert body["agent_configured"] is False
    assert body["provider"] is None


def test_health_with_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    with TestClient(create_app()) as c:
        body = c.get("/api/health").json()
    assert body["agent_configured"] is True
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"


def test_tools_lists_manifest(client: TestClient) -> None:
    body = client.get("/api/tools").json()
    names = {t["name"] for t in body}
    assert {"get_ticket", "reset_user_password"}.issubset(names)
    for tool in body:
        assert tool["description"]
        assert isinstance(tool["parameters"], dict)
