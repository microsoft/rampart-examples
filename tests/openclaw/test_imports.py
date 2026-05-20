# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Public-API and manifest smoke tests for ``openclaw``."""

from __future__ import annotations

from openclaw import (
    HtmlReportSink,
    InjectionTarget,
    OpenClawAdapter,
    OpenClawSession,
    PluginToolSurface,
)


class TestPublicAPI:
    """Public symbols of ``openclaw`` resolve and are usable."""

    def test_public_symbols_resolve(self) -> None:
        """Every public symbol exported from ``openclaw`` is importable."""
        assert OpenClawAdapter is not None
        assert OpenClawSession is not None
        assert PluginToolSurface is not None
        assert HtmlReportSink is not None
        assert InjectionTarget is not None

    def test_injection_target_enum(self) -> None:
        """``InjectionTarget`` exposes exactly the two attack vectors."""
        assert InjectionTarget.TOOL_OUTPUT == "tool_output"
        assert InjectionTarget.TOOL_DESCRIPTION == "tool_description"
        assert len(InjectionTarget) == 2


class TestManifest:
    """``OpenClawAdapter.DEFAULT_MANIFEST`` declares the expected tools."""

    def test_default_manifest_declares_expected_tools(self) -> None:
        """The agent's tool surface matches what RAMPART tests observe."""
        manifest = OpenClawAdapter.DEFAULT_MANIFEST
        tool_names = {t.name for t in manifest.tools}
        assert tool_names == {"exec", "read", "write", "edit", "apply_patch"}

    def test_default_manifest_identity(self) -> None:
        """Adapter advertises itself as ``OpenClaw`` for report attribution."""
        assert OpenClawAdapter.DEFAULT_MANIFEST.name == "OpenClaw"
