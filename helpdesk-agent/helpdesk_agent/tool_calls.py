# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Shared helpers for parsing Agent-Framework content fields.

The Agent-Framework ``Content`` model is a tagged union; each consumer
that wants a usable Python dict for tool-call ``arguments`` ends up
writing the same coercion. ``parse_arguments`` is the canonical version.

Lives at the agent layer because both ``helpdesk_agent.adapter`` (the
RAMPART adapter) and ``helpdesk_ui.agent_runner`` (the demo web UI)
need it. Extracting just this helper keeps the dependency graph
one-directional and avoids inventing a third ``ToolCall`` shape.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def parse_arguments(raw: str | Mapping[str, Any] | None) -> dict[str, object]:
    """Coerce Agent-Framework ``arguments`` into a plain ``dict``.

    The framework hands us either a JSON string (chat-completions
    style) or a mapping (responses style). Anything exotic is wrapped
    under a ``raw`` key so consumers see *something* rather than
    silently dropping the value.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()}
    if isinstance(raw, str):
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    return {"raw": str(raw)}
