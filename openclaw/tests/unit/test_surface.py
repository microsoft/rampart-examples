# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Unit tests for injection surfaces.

Tests the plugin template generator, ``PluginToolSurface`` validation,
and protocol compliance without requiring a live sandbox.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from openclaw.surface import (
    InjectionTarget,
    PluginToolSurface,
    _generate_plugin_files,
)
from rampart.core.types import Payload


class TestGeneratePluginFiles:
    """Tests for ``_generate_plugin_files`` template output."""

    def test_tool_output_produces_valid_json_files(self) -> None:
        """package.json and manifest are valid JSON."""
        files = _generate_plugin_files(
            plugin_id="test-plugin",
            tool_name="test_tool",
            tool_description="A test tool",
            payload="do something adversarial",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        pkg = json.loads(files["package.json"])
        assert pkg["name"] == "test-plugin"
        assert pkg["openclaw"]["extensions"] == ["./index.ts"]
        assert "compat" in pkg["openclaw"]
        assert "build" in pkg["openclaw"]

        manifest = json.loads(files["openclaw.plugin.json"])
        assert manifest["id"] == "test-plugin"
        assert "configSchema" in manifest
        assert manifest["activation"]["onStartup"] is True

    def test_tool_description_produces_valid_json_files(self) -> None:
        """package.json and manifest are valid JSON in description mode."""
        files = _generate_plugin_files(
            plugin_id="desc-plugin",
            tool_name="desc_tool",
            tool_description="A desc tool",
            payload="adversarial in description",
            injection_target=InjectionTarget.TOOL_DESCRIPTION,
        )
        pkg = json.loads(files["package.json"])
        assert pkg["name"] == "desc-plugin"

        manifest = json.loads(files["openclaw.plugin.json"])
        assert manifest["id"] == "desc-plugin"

    def test_tool_output_embeds_payload_in_execute(self) -> None:
        """Payload appears in the execute body for TOOL_OUTPUT."""
        files = _generate_plugin_files(
            plugin_id="p1",
            tool_name="t1",
            tool_description="desc",
            payload="INJECT_THIS",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        index = files["index.ts"].decode("utf-8")
        assert "INJECT_THIS" in index
        assert "execute" in index

    def test_tool_description_embeds_payload_in_description(self) -> None:
        """Payload appears in the description field for TOOL_DESCRIPTION."""
        files = _generate_plugin_files(
            plugin_id="p2",
            tool_name="t2",
            tool_description="benign desc",
            payload="INJECT_IN_DESC",
            injection_target=InjectionTarget.TOOL_DESCRIPTION,
        )
        index = files["index.ts"].decode("utf-8")
        assert "INJECT_IN_DESC" in index
        assert "benign desc" in index

    def test_tool_description_execute_returns_benign(self) -> None:
        """TOOL_DESCRIPTION mode returns benign output from execute."""
        files = _generate_plugin_files(
            plugin_id="p3",
            tool_name="t3",
            tool_description="desc",
            payload="adversarial",
            injection_target=InjectionTarget.TOOL_DESCRIPTION,
        )
        index = files["index.ts"].decode("utf-8")
        assert "No issues found" in index

    def test_payload_with_special_chars_is_escaped(self) -> None:
        """Quotes, newlines, and backticks in payload are properly escaped."""
        payload = 'Line1\nLine2\t"quoted"\n`backtick`\n\\backslash'
        files = _generate_plugin_files(
            plugin_id="p4",
            tool_name="t4",
            tool_description="desc",
            payload=payload,
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        index = files["index.ts"].decode("utf-8")
        # The file should be syntactically valid TS — no unescaped
        # characters breaking the string literal.  The payload is
        # JSON-encoded so each special char appears as its escape
        # sequence in the rendered file.
        assert "\\n" in index
        assert "\\t" in index
        assert '\\"quoted\\"' in index
        assert "\\\\backslash" in index
        # Raw newline/tab from the payload must NOT appear unescaped
        # inside the string literal.
        assert "Line1\nLine2" not in index

    def test_all_three_files_present(self) -> None:
        """Generator returns exactly three files."""
        files = _generate_plugin_files(
            plugin_id="p5",
            tool_name="t5",
            tool_description="desc",
            payload="test",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        assert set(files.keys()) == {
            "package.json",
            "openclaw.plugin.json",
            "index.ts",
        }

    def test_index_imports_plugin_sdk(self) -> None:
        """index.ts imports from openclaw/plugin-sdk/plugin-entry."""
        files = _generate_plugin_files(
            plugin_id="p6",
            tool_name="t6",
            tool_description="desc",
            payload="test",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        index = files["index.ts"].decode("utf-8")
        assert "openclaw/plugin-sdk/plugin-entry" in index
        assert "definePluginEntry" in index

    def test_entry_point_has_description(self) -> None:
        """DefinePluginEntry includes a description field."""
        files = _generate_plugin_files(
            plugin_id="p6b",
            tool_name="t6b",
            tool_description="My tool description",
            payload="test",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        index = files["index.ts"].decode("utf-8")
        assert "description:" in index
        assert "My tool description" in index

    def test_tool_name_in_register_call(self) -> None:
        """Tool name appears in registerTool call."""
        files = _generate_plugin_files(
            plugin_id="p7",
            tool_name="my_custom_tool",
            tool_description="desc",
            payload="test",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        index = files["index.ts"].decode("utf-8")
        assert "my_custom_tool" in index


class TestPluginToolSurfaceValidation:
    """Tests for ``PluginToolSurface`` constructor validation."""

    def test_valid_plugin_id_accepted(self) -> None:
        """Valid plugin_id does not raise."""
        client = MagicMock()
        surface = PluginToolSurface(
            client=client,
            plugin_id="xpia-probe-test",
            tool_name="test_tool",
            tool_description="A tool",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        assert surface.plugin_id == "xpia-probe-test"

    def test_invalid_plugin_id_raises_value_error(self) -> None:
        """Invalid plugin_id raises ValueError."""
        client = MagicMock()
        with pytest.raises(ValueError, match="plugin_id"):
            PluginToolSurface(
                client=client,
                plugin_id="bad plugin id!",
                tool_name="test_tool",
                tool_description="A tool",
                injection_target=InjectionTarget.TOOL_OUTPUT,
            )

    def test_invalid_tool_name_raises_value_error(self) -> None:
        """Invalid tool_name raises ValueError."""
        client = MagicMock()
        with pytest.raises(ValueError, match="tool_name"):
            PluginToolSurface(
                client=client,
                plugin_id="valid-id",
                tool_name="bad tool name!",
                tool_description="A tool",
                injection_target=InjectionTarget.TOOL_OUTPUT,
            )

    def test_empty_plugin_id_raises_value_error(self) -> None:
        """Empty plugin_id raises ValueError."""
        client = MagicMock()
        with pytest.raises(ValueError, match="plugin_id"):
            PluginToolSurface(
                client=client,
                plugin_id="",
                tool_name="test_tool",
                tool_description="A tool",
                injection_target=InjectionTarget.TOOL_OUTPUT,
            )

    def test_inject_returns_injection_handle(self) -> None:
        """inject() returns an object with InjectionHandle properties."""
        client = MagicMock()
        surface = PluginToolSurface(
            client=client,
            plugin_id="test-id",
            tool_name="test_tool",
            tool_description="A tool",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        payload = Payload(content="test", id="test-001")
        handle = surface.inject(payload=payload)

        assert handle.payload_id == "test-001"
        assert handle.surface_name == "PluginTool(test_tool:tool_output)"


class TestPluginToolSurfaceProtocolCompliance:
    """Tests that surfaces satisfy RAMPART protocol contracts."""

    def test_surface_has_inject_method(self) -> None:
        """PluginToolSurface has inject(*, payload) method."""
        client = MagicMock()
        surface = PluginToolSurface(
            client=client,
            plugin_id="proto-test",
            tool_name="test_tool",
            tool_description="A tool",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        assert hasattr(surface, "inject")
        assert callable(surface.inject)

    def test_injection_handle_has_required_properties(self) -> None:
        """InjectionHandle has all required protocol properties."""
        client = MagicMock()
        surface = PluginToolSurface(
            client=client,
            plugin_id="proto-test",
            tool_name="test_tool",
            tool_description="A tool",
            injection_target=InjectionTarget.TOOL_DESCRIPTION,
        )
        payload = Payload(content="test", id="proto-001")
        handle = surface.inject(payload=payload)

        assert hasattr(handle, "payload_id")
        assert hasattr(handle, "surface_name")
        assert hasattr(handle, "wait_until_ready")
        assert callable(handle.wait_until_ready)
        assert hasattr(handle, "__aenter__")
        assert hasattr(handle, "__aexit__")

    def test_surface_name_includes_injection_target(self) -> None:
        """surface_name reflects both tool name and injection target."""
        client = MagicMock()
        surface = PluginToolSurface(
            client=client,
            plugin_id="name-test",
            tool_name="my_tool",
            tool_description="A tool",
            injection_target=InjectionTarget.TOOL_DESCRIPTION,
        )
        payload = Payload(content="test", id="name-001")
        handle = surface.inject(payload=payload)

        assert handle.surface_name == "PluginTool(my_tool:tool_description)"


class TestWaitUntilReady:
    """Tests for wait_until_ready behavior."""

    async def test_plugin_tool_wait_polls_gateway_and_tool(self) -> None:
        """_PluginToolInjection.wait_until_ready polls gateway then tool."""
        client = MagicMock()
        client.health_check_async = AsyncMock(return_value=True)
        client.exec_async = AsyncMock(
            return_value=(b'{"tools":["test_tool"]}', b""),
        )
        surface = PluginToolSurface(
            client=client,
            plugin_id="wait-test",
            tool_name="test_tool",
            tool_description="A tool",
            injection_target=InjectionTarget.TOOL_OUTPUT,
        )
        handle = surface.inject(payload=Payload(content="test", id="w-002"))

        await handle.wait_until_ready()

        client.health_check_async.assert_awaited()
        client.exec_async.assert_awaited()


class TestInjectionTargetEnum:
    """Tests for the InjectionTarget enum."""

    def test_tool_output_value(self) -> None:
        assert InjectionTarget.TOOL_OUTPUT == "tool_output"

    def test_tool_description_value(self) -> None:
        assert InjectionTarget.TOOL_DESCRIPTION == "tool_description"

    def test_enum_has_exactly_two_members(self) -> None:
        assert len(InjectionTarget) == 2
