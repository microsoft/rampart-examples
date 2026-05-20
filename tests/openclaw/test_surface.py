# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Public ``PluginToolSurface`` contract smoke tests (no sandbox required)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from openclaw import InjectionTarget, PluginToolSurface
from rampart import Payload


class TestPluginToolSurface:
    """Public constructor + ``inject()`` contract."""

    def test_valid_ids_construct_cleanly(self) -> None:
        """A valid plugin_id/tool_name pair is accepted."""
        surface = PluginToolSurface(
            client=MagicMock(),
            plugin_id="smoke-plugin",
            tool_name="search",
            tool_description="desc",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        assert surface.plugin_id == "smoke-plugin"
        assert surface.tool_name == "search"

    def test_invalid_plugin_id_rejected(self) -> None:
        """Shell-unsafe characters in plugin_id raise ValueError."""
        with pytest.raises(ValueError, match="plugin_id"):
            PluginToolSurface(
                client=MagicMock(),
                plugin_id="bad id!",
                tool_name="search",
                tool_description="desc",
                injection_target=InjectionTarget.TOOL_OUTPUT,
            )

    def test_invalid_tool_name_rejected(self) -> None:
        """Shell-unsafe characters in tool_name raise ValueError."""
        with pytest.raises(ValueError, match="tool_name"):
            PluginToolSurface(
                client=MagicMock(),
                plugin_id="smoke",
                tool_name="bad tool!",
                tool_description="desc",
                injection_target=InjectionTarget.TOOL_OUTPUT,
            )

    def test_inject_returns_handle_with_protocol_attrs(self) -> None:
        """``inject()`` returns a handle exposing the InjectionHandle contract."""
        surface = PluginToolSurface(
            client=MagicMock(),
            plugin_id="smoke",
            tool_name="search",
            tool_description="desc",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        handle = surface.inject(payload=Payload(content="x", id="payload-1"))
        assert handle.payload_id == "payload-1"
        assert handle.surface_name == "PluginTool(search:tool_output)"
        assert hasattr(handle, "__aenter__")
        assert hasattr(handle, "__aexit__")
        assert callable(handle.wait_until_ready)
