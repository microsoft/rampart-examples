# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Single-turn streaming runner for the helpdesk-agent web chat."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from agent_framework import (
    Agent,
    AgentResponse,
    AgentSession,
    Content,
    InMemoryHistoryProvider,
    Message,
)
from helpdesk_agent.tool_calls import parse_arguments

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from helpdesk_ui.schemas import ChatMessage

from helpdesk_ui.schemas import ToolCall

_logger = logging.getLogger(__name__)

AgentFactory = Callable[[], Agent[Any]]


@dataclass(frozen=True, slots=True, kw_only=True)
class DeltaEvent:
    """Streamed text fragment."""

    text: str
    kind: Literal["delta"] = "delta"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCallEvent:
    """Agent invoked a tool; emitted once per ``call_id`` on first sight."""

    call_id: str
    name: str
    kind: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolResultEvent:
    """Tool returned. Carries parsed args + result so the UI can render atomically."""

    call_id: str
    name: str
    arguments: dict[str, object]
    result: str | None
    kind: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True, slots=True, kw_only=True)
class FinalEvent:
    """Terminal success: canonical reply + tool-call list."""

    reply: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    kind: Literal["final"] = "final"


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorEvent:
    """Terminal failure surfaced inline as a red bubble."""

    detail: str
    kind: Literal["error"] = "error"


TurnEvent = DeltaEvent | ToolCallEvent | ToolResultEvent | FinalEvent | ErrorEvent


# --- Public API --------------------------------------------------------


async def run_turn(
    history: Sequence[ChatMessage],
    *,
    agent_factory: AgentFactory,
) -> AsyncIterator[TurnEvent]:
    """Run one agent turn against ``history``.

    Yields ``TurnEvent`` instances. Always terminates with exactly one
    of ``FinalEvent`` or ``ErrorEvent``; never raises. Caller is
    responsible for the ``role == "user"`` invariant on the last
    message of ``history``.
    """
    try:
        agent = agent_factory()
    except ValueError as exc:
        # build_agent() raises ValueError when no provider is set.
        yield ErrorEvent(detail=str(exc))
        return
    except Exception as exc:
        _logger.exception("agent_factory() failed")
        yield ErrorEvent(detail=str(exc))
        return
    session = _replay_session(history)
    prompt = history[-1].content

    seen_calls: dict[str, str] = {}  # call_id -> name
    args_buffer: dict[str, str] = {}  # call_id -> accumulated JSON arg text
    agent_response: AgentResponse | None = None
    try:
        stream = agent.run(prompt, session=session, stream=True)
        async for update in stream:
            text = update.text or ""
            if text:
                yield DeltaEvent(text=text)
            for content in update.contents:
                event = _event_from_content(content, seen_calls, args_buffer)
                if event is not None:
                    yield event

        agent_response = await stream.get_final_response()
    except Exception as exc:
        _logger.exception("agent stream failed")
        yield ErrorEvent(detail=str(exc))
        return

    reply = (agent_response.text or "").strip() if agent_response else ""
    tool_calls = extract_tool_calls(agent_response) if agent_response else []
    yield FinalEvent(reply=reply, tool_calls=tool_calls)


def _event_from_content(
    content: Content,
    seen_calls: dict[str, str],
    args_buffer: dict[str, str],
) -> TurnEvent | None:
    """Map one streaming content item to at most one ``TurnEvent``."""
    call_id = content.call_id or ""
    if content.type == "function_call" and call_id:
        _accumulate_args(content, call_id, args_buffer)
        name = content.name or ""
        if call_id not in seen_calls and name:
            seen_calls[call_id] = name
            return ToolCallEvent(call_id=call_id, name=name)
        return None
    if content.type == "function_result" and call_id:
        name = seen_calls.get(call_id) or (content.name or "")
        result = _stringify_result(content.result)
        return ToolResultEvent(
            call_id=call_id,
            name=name,
            arguments=parse_arguments(args_buffer.get(call_id, "")),
            result=result,
        )
    return None


def _accumulate_args(
    content: Content,
    call_id: str,
    args_buffer: dict[str, str],
) -> None:
    """Append a streamed arg fragment to ``args_buffer[call_id]``."""
    raw = content.arguments
    if raw is None or raw == "":
        return
    if isinstance(raw, str):
        args_buffer[call_id] = args_buffer.get(call_id, "") + raw
        return
    try:
        args_buffer[call_id] = json.dumps(raw)
    except (TypeError, ValueError):
        args_buffer[call_id] = str(raw)


def _stringify_result(raw: object) -> str | None:
    """Coerce a tool result to ``str | None`` for the wire format."""
    if raw is None:
        return None
    return raw if isinstance(raw, str) else str(raw)


# --- SSE serialisation -------------------------------------------------


def _event_to_sse(event: TurnEvent) -> str:
    """Serialise one ``TurnEvent`` to a single SSE frame."""
    payload: dict[str, Any]
    match event:
        case DeltaEvent(text=text):
            payload = {"text": text}
        case ToolCallEvent(call_id=call_id, name=name):
            payload = {"call_id": call_id, "name": name}
        case ToolResultEvent(
            call_id=call_id,
            name=name,
            arguments=arguments,
            result=result,
        ):
            payload = {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "result": result,
            }
        case FinalEvent(reply=reply, tool_calls=tool_calls):
            payload = {
                "reply": reply,
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            }
        case ErrorEvent(detail=detail):
            payload = {"detail": detail}
    return f"event: {event.kind}\ndata: {json.dumps(payload)}\n\n"


# --- History replay ----------------------------------------------------


def _replay_session(history: Sequence[ChatMessage]) -> AgentSession:
    """Seed prior turns into a fresh ``AgentSession`` for ``InMemoryHistoryProvider``.

    The provider reads from ``state[provider.source_id]["messages"]``
    (default ``source_id == "in_memory"``). Seeding ``state["messages"]``
    directly does NOT work — provider state is namespaced by ``source_id``.
    """
    session = AgentSession()
    if len(history) <= 1:
        return session
    messages: list[Message] = [Message(m.role, [m.content]) for m in history[:-1]]
    session.state[InMemoryHistoryProvider.DEFAULT_SOURCE_ID] = {"messages": messages}
    return session


# --- Tool-call extraction ----------------------------------------------


def extract_tool_calls(agent_response: AgentResponse) -> list[ToolCall]:
    """Pull ``function_call``/``function_result`` content into ``ToolCall``s.

    Two passes over the aggregated response: build a
    ``call_id -> result`` map, then walk the calls and assemble
    ``ToolCall`` records.
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
