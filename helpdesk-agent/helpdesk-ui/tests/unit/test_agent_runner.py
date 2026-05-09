# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the agent runner: events, dedup, errors, replay, narrowing."""

from __future__ import annotations

import pytest
from helpdesk_ui.agent_runner import (
    DeltaEvent,
    ErrorEvent,
    FinalEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnEvent,
    _replay_session,
    run_turn,
)
from helpdesk_ui.schemas import ChatMessage

from tests.conftest import FakeAgentBuilder, FakeRun


async def test_run_turn_simple(fake_agent: FakeAgentBuilder) -> None:
    fake_agent.queue(FakeRun(deltas=["a", "b"], tool_calls=[]))
    events = [
        e
        async for e in run_turn(
            [ChatMessage(role="user", content="x")],
            agent_factory=fake_agent,
        )
    ]
    assert [e.kind for e in events] == ["delta", "delta", "final"]
    final = events[-1]
    assert isinstance(final, FinalEvent)
    assert final.reply == "ab"


async def test_run_turn_tool_dedup(fake_agent: FakeAgentBuilder) -> None:
    fake_agent.queue(
        FakeRun(
            deltas=[],
            tool_calls=[("t", {"k": "v"}, "ok")],
            emit_arg_fragments=True,
        ),
    )
    events = [
        e
        async for e in run_turn(
            [ChatMessage(role="user", content="x")],
            agent_factory=fake_agent,
        )
    ]
    kinds = [e.kind for e in events]
    assert kinds.count("tool_call") == 1
    assert "tool_result" in kinds
    assert kinds[-1] == "final"


async def test_run_turn_error_yielded_not_raised(
    fake_agent: FakeAgentBuilder,
) -> None:
    fake_agent.raise_on_build("No provider configured")
    events = [
        e
        async for e in run_turn(
            [ChatMessage(role="user", content="x")],
            agent_factory=fake_agent,
        )
    ]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "provider" in events[0].detail.lower()


async def test_run_turn_stream_failure_yielded(
    fake_agent: FakeAgentBuilder,
) -> None:
    fake_agent.queue(FakeRun(deltas=["partial"], tool_calls=[], error="boom"))
    events = [
        e
        async for e in run_turn(
            [ChatMessage(role="user", content="x")],
            agent_factory=fake_agent,
        )
    ]
    # A partial delta may arrive before the failure; the terminal event must be ErrorEvent.
    assert isinstance(events[-1], ErrorEvent)
    assert "boom" in events[-1].detail


def test_replay_session_skips_last_message() -> None:
    history = [
        ChatMessage(role="user", content="a"),
        ChatMessage(role="assistant", content="b"),
        ChatMessage(role="user", content="c"),
    ]
    session = _replay_session(history)
    # Provider state is namespaced by source_id (default "in_memory").
    seeded = session.state["in_memory"]["messages"]
    assert len(seeded) == 2
    assert seeded[0].text == "a"
    assert seeded[1].text == "b"


def test_replay_session_single_message() -> None:
    session = _replay_session([ChatMessage(role="user", content="solo")])
    assert "in_memory" not in session.state


def test_turn_event_is_discriminated_union() -> None:
    """``match`` narrowing on the union must narrow correctly."""
    e: TurnEvent = DeltaEvent(text="hi")
    match e:
        case DeltaEvent(text=t):
            assert t == "hi"
        case _:
            pytest.fail("did not narrow")

    # And every variant has a unique ``kind`` discriminant.
    assert {
        DeltaEvent(text="").kind,
        ToolCallEvent(call_id="c", name="t").kind,
        ToolResultEvent(call_id="c", name="t", arguments={}, result=None).kind,
        FinalEvent(reply="").kind,
        ErrorEvent(detail="").kind,
    } == {"delta", "tool_call", "tool_result", "final", "error"}
