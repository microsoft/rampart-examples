# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Auth-proxy config loading smoke tests (no network, no Azure login)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from openclaw.auth.injectors import BearerTokenAuth
from openclaw.auth.routes import init_config, routes_from_config

if TYPE_CHECKING:
    from pathlib import Path


class TestInitConfig:
    """``init_config`` writes a usable template."""

    def test_creates_template_with_providers_section(self, tmp_path: Path) -> None:
        """The generated file is valid JSON with a ``providers`` table."""
        path = tmp_path / "config.json"
        result = init_config(path)
        assert result == path
        assert path.exists()
        config = json.loads(path.read_text(encoding="utf-8"))
        assert "providers" in config

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Re-running init_config is a no-op to protect user-edited configs."""
        path = tmp_path / "config.json"
        path.write_text('{"providers": {"keep": "me"}}', encoding="utf-8")
        init_config(path)
        assert json.loads(path.read_text(encoding="utf-8")) == {"providers": {"keep": "me"}}


class TestRoutesFromConfig:
    """``routes_from_config`` round-trips a bearer-auth provider."""

    def test_bearer_route_round_trip(self, tmp_path: Path) -> None:
        """A bearer provider produces one route with BearerTokenAuth."""
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(
                {
                    "providers": {
                        "openai": {
                            "enabled": True,
                            "api_key": "sk-test",
                            "base_url": "https://api.openai.com/v1",
                            "auth": "bearer",
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        routes = routes_from_config(path)
        assert len(routes) == 1
        route = routes[0]
        assert route.name == "openai"
        assert route.target_base_url == "https://api.openai.com/v1"
        assert isinstance(route.auth, BearerTokenAuth)

    def test_disabled_provider_skipped(self, tmp_path: Path) -> None:
        """Providers with ``enabled: false`` produce no routes."""
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(
                {
                    "providers": {
                        "openai": {
                            "enabled": False,
                            "api_key": "sk-test",
                            "base_url": "https://api.openai.com/v1",
                            "auth": "bearer",
                        },
                    },
                },
            ),
            encoding="utf-8",
        )
        assert routes_from_config(path) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """A non-existent config path returns an empty route list (not an error)."""
        assert routes_from_config(tmp_path / "does-not-exist.json") == []
