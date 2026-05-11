# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Public-API and manifest smoke tests."""

from __future__ import annotations

from helpdesk_agent import (
    HELPDESK_MANIFEST,
    HelpdeskAdapter,
    HelpdeskSession,
    LocalTicketSurface,
    TicketStore,
    build_agent,
)


class TestPublicAPI:
    """Public symbols of ``helpdesk_agent`` resolve and are callable."""

    def test_public_symbols_resolve(self) -> None:
        """Every public symbol exported from ``helpdesk_agent`` is importable."""
        assert callable(build_agent)
        assert HELPDESK_MANIFEST.name == "HelpdeskAgent"
        assert isinstance(HelpdeskAdapter(), HelpdeskAdapter)
        assert HelpdeskSession is not None
        assert LocalTicketSurface is not None
        assert TicketStore is not None


class TestManifest:
    """``HELPDESK_MANIFEST`` declares the right tools and trust boundary."""

    def test_declares_expected_tools(self) -> None:
        """Both tools are declared with the right parameter names."""
        tool_names = {t.name for t in HELPDESK_MANIFEST.tools}
        assert tool_names == {"get_ticket", "reset_user_password"}

        reset = next(t for t in HELPDESK_MANIFEST.tools if t.name == "reset_user_password")
        assert {"user_email", "send_to"} <= set(reset.parameters)

    def test_marks_ticket_store_writable_by_untrusted(self) -> None:
        """The data-source declaration is what triggers RAMPART's XPIA targeting."""
        sources = {ds.name: ds for ds in HELPDESK_MANIFEST.data_sources}
        assert "TicketStore" in sources
        assert sources["TicketStore"].writable_by_untrusted is True
