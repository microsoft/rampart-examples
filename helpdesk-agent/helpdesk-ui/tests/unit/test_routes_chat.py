# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the streaming chat route."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.conftest import FakeAgentBuilder, FakeRun, parse_sse

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def _post_stream(
    client: TestClient,
    messages: list[dict[str, Any]],
) -> tuple[int, list[tuple[str, dict[str, Any]]]]:
    with client.stream("POST", "/api/chat/stream", json={"messages": messages}) as r:
        events = parse_sse(r.iter_lines())
        return r.status_code, events


def test_validation_empty_messages(client: TestClient) -> None:
    assert client.post("/api/chat/stream", json={"messages": []}).status_code == 422


def test_validation_last_must_be_user(client: TestClient) -> None:
    r = client.post(
        "/api/chat/stream",
        json={"messages": [{"role": "assistant", "content": "hi", "tool_calls": []}]},
    )
    assert r.status_code == 400


def test_validation_blank_user_content(client: TestClient) -> None:
    r = client.post(
        "/api/chat/stream",
        json={"messages": [{"role": "user", "content": "   "}]},
    )
    assert r.status_code == 400


def test_no_non_streaming_endpoint(client: TestClient) -> None:
    r = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "x"}]},
    )
    # 404 (truly missing) or 405 (matched the GET-only SPA fallback) — both
    # mean "no /api/chat endpoint".
    assert r.status_code in (404, 405)


def test_stream_simple_reply(
    client: TestClient,
    fake_agent: FakeAgentBuilder,
) -> None:
    fake_agent.queue(FakeRun(deltas=["Hi", " there"], tool_calls=[]))
    status, events = _post_stream(
        client,
        [{"role": "user", "content": "hello"}],
    )
    assert status == 200
    kinds = [e[0] for e in events]
    assert kinds == ["delta", "delta", "final"]
    assert events[-1][1]["reply"] == "Hi there"
    assert events[-1][1]["tool_calls"] == []


def test_stream_with_tool_call(
    client: TestClient,
    fake_agent: FakeAgentBuilder,
) -> None:
    fake_agent.queue(
        FakeRun(
            deltas=["The subject is Login fail."],
            tool_calls=[
                ("get_ticket", {"ticket_id": "T-1001"}, "Subject: Login fail"),
            ],
        ),
    )
    _, events = _post_stream(
        client,
        [{"role": "user", "content": "look up T-1001"}],
    )
    kinds = [e[0] for e in events]
    assert kinds.count("tool_call") == 1
    assert "tool_result" in kinds
    assert kinds[-1] == "final"
    final = events[-1][1]
    assert final["tool_calls"][0]["arguments"] == {"ticket_id": "T-1001"}
    assert final["tool_calls"][0]["result"] == "Subject: Login fail"


def test_stream_tool_result_carries_args(
    client: TestClient,
    fake_agent: FakeAgentBuilder,
) -> None:
    """Args accumulated from streamed fragments arrive on ``tool_result``."""
    fake_agent.queue(
        FakeRun(
            deltas=[],
            tool_calls=[("get_ticket", {"ticket_id": "T-1001"}, "OK")],
            emit_arg_fragments=True,
        ),
    )
    _, events = _post_stream(client, [{"role": "user", "content": "x"}])
    kinds = [e[0] for e in events]
    assert kinds.count("tool_call") == 1
    result_events = [e for e in events if e[0] == "tool_result"]
    assert len(result_events) == 1
    payload = result_events[0][1]
    assert payload["name"] == "get_ticket"
    assert payload["arguments"] == {"ticket_id": "T-1001"}
    assert payload["result"] == "OK"


def test_stream_dedupes_tool_call_arg_fragments(
    client: TestClient,
    fake_agent: FakeAgentBuilder,
) -> None:
    fake_agent.queue(
        FakeRun(
            deltas=[],
            tool_calls=[("get_ticket", {"ticket_id": "T-1001"}, "OK")],
            emit_arg_fragments=True,
        ),
    )
    _, events = _post_stream(client, [{"role": "user", "content": "x"}])
    tool_calls = [e for e in events if e[0] == "tool_call"]
    assert len(tool_calls) == 1


def test_stream_provider_not_configured_emits_error_event(
    client: TestClient,
    fake_agent: FakeAgentBuilder,
) -> None:
    fake_agent.raise_on_build("No provider configured. Set OPENAI_API_KEY...")
    status, events = _post_stream(client, [{"role": "user", "content": "x"}])
    assert status == 200
    assert events[-1][0] == "error"
    assert "provider" in events[-1][1]["detail"].lower()


def test_stream_history_replays_into_session(
    client: TestClient,
    fake_agent: FakeAgentBuilder,
) -> None:
    fake_agent.queue(FakeRun(deltas=["ack"], tool_calls=[]))
    client.post(
        "/api/chat/stream",
        json={
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "reply 1", "tool_calls": []},
                {"role": "user", "content": "second"},
            ],
        },
    )
    seen = fake_agent.last_session_messages()
    assert len(seen) == 2  # the two prior turns; the new prompt isn't replayed


def test_chat_request_body_over_limit_returns_413(client: TestClient) -> None:
    huge = "x" * (300 * 1024)
    r = client.post(
        "/api/chat/stream",
        json={"messages": [{"role": "user", "content": huge}]},
    )
    assert r.status_code == 413
