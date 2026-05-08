# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Shared helpers for the helpdesk_agent smoke suite."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agent_framework import AgentResponse

# Path to the helpdesk_agent demo directory. Resolved from this file
# so the constant is correct regardless of pytest's invocation cwd.
HELPDESK_AGENT_DIR = (Path(__file__).parents[2] / "helpdesk-agent").resolve()


def fake_response(messages: Iterable[object], text: str = "") -> AgentResponse:
    """Build a stand-in for ``AgentResponse`` with the attrs the adapter inspects.

    The return is duck-typed (``SimpleNamespace``) but cast to
    ``AgentResponse`` so call sites in the smoke tests get the real
    type — production code's strict annotation stays useful and the
    cast localises the "this is a test fixture" lie to one line.
    """
    ns = SimpleNamespace(messages=list(messages), text=text, response_id="resp_smoke")
    return cast("AgentResponse", ns)


def content(**kwargs: object) -> SimpleNamespace:
    """Build a stand-in ``Content`` object whose attributes the adapter reads."""
    return SimpleNamespace(**kwargs)
