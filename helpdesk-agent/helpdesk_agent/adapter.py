# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""HelpdeskAdapter: bridges Microsoft Agent Framework to RAMPART.

Implements the two RAMPART protocols the framework needs to interact
with the agent:

* ``AgentAdapter``: supplies the manifest, declares observability, and
  manufactures fresh sessions.
* ``Session``: sends a single ``Request`` to the agent, normalises the
  Agent-Framework ``AgentResponse`` into RAMPART's ``Response`` (text
  plus structured ``ToolCall`` records).

The adapter declares ``TOOL_AND_SIDE_EFFECTS`` observability because
Agent Framework surfaces every tool call (and its result) as
``function_call`` / ``function_result`` content items on the response
messages. We extract those directly; no log scraping required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from rampart import (
    AppManifest,
    ObservabilityLevel,
    Request,
    Response,
    ToolCall,
)

from helpdesk_agent.agent import build_agent
from helpdesk_agent.manifest import HELPDESK_MANIFEST
from helpdesk_agent.tool_calls import parse_arguments

if TYPE_CHECKING:
    import types

    from agent_framework import Agent, AgentResponse


class HelpdeskSession:
    """A single interaction session with a freshly-built HelpdeskAgent."""

    def __init__(self, agent: Agent[None]) -> None:
        """Bind the session to a specific Agent instance."""
        self._agent = agent

    async def send_async(self, request: Request) -> Response:
        """Send one prompt + attachments to the agent and observe its tools.

        Inline attachments are appended to the prompt text inside an
        ``[attached document]`` block.
        """
        prompt = self._render_prompt(request)
        agent_response = await self._agent.run(prompt)
        tool_calls = self._extract_tool_calls(agent_response)

        metadata: dict[str, object] = {}
        if agent_response.response_id is not None:
            metadata["response_id"] = agent_response.response_id

        return Response(
            text=agent_response.text,
            tool_calls=tool_calls,
            metadata=metadata,
        )

    @staticmethod
    def _render_prompt(request: Request) -> str:
        """Combine the prompt and any inline attachments into one string."""
        parts: list[str] = []
        if request.prompt:
            parts.append(request.prompt)
        # The framing is intentional: it mimics how a chat surface
        # presents an attached document to the model.
        parts.extend(
            f"\n\n[attached document: {a.id}]\n{a.content}\n[end attachment]"
            for a in request.attachments
        )
        return "\n".join(parts)

    @staticmethod
    def _extract_tool_calls(agent_response: AgentResponse) -> list[ToolCall]:
        """Pull ``function_call``/``function_result`` content into ``ToolCall``s.

        Two passes over the aggregated ``AgentResponse``: build a
        ``call_id -> result`` map, then walk the calls and assemble
        ``ToolCall`` records. Non-string results are stringified so
        evaluators can distinguish "tool returned exotic payload" from
        "result not present" (``None``).
        """
        results_by_call_id: dict[str, str] = {}
        for msg in agent_response.messages:
            for content in msg.contents:
                if content.type != "function_result":
                    continue
                call_id = content.call_id
                result = content.result
                if call_id is None or result is None:
                    continue
                results_by_call_id[call_id] = result if isinstance(result, str) else str(result)

        tool_calls: list[ToolCall] = []
        for msg in agent_response.messages:
            for content in msg.contents:
                if content.type != "function_call":
                    continue
                tool_calls.append(
                    ToolCall(
                        name=content.name or "",
                        arguments=parse_arguments(content.arguments),
                        result=results_by_call_id.get(content.call_id or ""),
                    ),
                )
        return tool_calls

    async def __aenter__(self) -> Self:
        """Enter the session context. No async setup needed."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the session context. The agent is single-use; nothing to release."""


class HelpdeskAdapter:
    """Factory for HelpdeskAgent sessions and source of the manifest."""

    @property
    def manifest(self) -> AppManifest:
        """Return the agent's declared capabilities (tools, data sources)."""
        return HELPDESK_MANIFEST

    @property
    def observability_profile(self) -> ObservabilityLevel:
        """Agent Framework surfaces tool calls + results, not just text."""
        return ObservabilityLevel.TOOL_AND_SIDE_EFFECTS

    async def create_session_async(self) -> HelpdeskSession:
        """Build a fresh agent so each test starts from clean state."""
        return HelpdeskSession(agent=build_agent())
