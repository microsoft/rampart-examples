# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Shared helpers for the helpdesk_agent smoke suite."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Path to the helpdesk_agent demo directory. Resolved from this file
# so the constant is correct regardless of pytest's invocation cwd.
HELPDESK_AGENT_DIR = (Path(__file__).parents[2] / "helpdesk-agent").resolve()


def fake_response(messages: Iterable[object], text: str = "") -> SimpleNamespace:
    """Build a stand-in for ``AgentResponse`` with the attrs the adapter inspects."""
    return SimpleNamespace(messages=list(messages), text=text, response_id="resp_smoke")


def content(**kwargs: object) -> SimpleNamespace:
    """Build a stand-in ``Content`` object whose attributes the adapter reads."""
    return SimpleNamespace(**kwargs)
