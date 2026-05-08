# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Pytest fixtures: tmp ticket dir, fake agent factory, FastAPI client."""

from __future__ import annotations

import dataclasses
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi.testclient import TestClient
from helpdesk_ui.app import create_app
from helpdesk_ui.routes.chat import get_agent_factory

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

    from agent_framework import Agent, AgentSession
    from fastapi import FastAPI

_SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "tickets"


@pytest.fixture
def tmp_ticket_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Empty ticket directory wired into ``TicketStore`` via env var."""
    monkeypatch.setenv("HELPDESK_TICKET_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def seeded_ticket_dir(tmp_ticket_dir: Path) -> Path:
    """Pre-populated with the bundled T-1001 / T-1002 / T-1003 seeds."""
    for seed_id in ("T-1001", "T-1002", "T-1003"):
        src = _SEED_DIR / f"{seed_id}.json"
        if src.exists():
            shutil.copy2(src, tmp_ticket_dir / f"{seed_id}.json")
    return tmp_ticket_dir


# --- Agent-framework duck types ------------------------------------------
#
# We don't import private framework internals; instead we synthesise
# plain objects with the attribute shapes that ``run_turn`` reads
# (``.text``, ``.contents`` with ``.type/.name/.call_id/.arguments/.result``,
# ``.messages`` for the final response).


@dataclass
class _Content:
    type: str
    call_id: str | None = None
    name: str | None = None
    arguments: Any = None
    result: Any = None


@dataclass
class _Message:
    contents: list[_Content] = field(default_factory=list)


@dataclass
class _Update:
    text: str = ""
    contents: list[_Content] = field(default_factory=list)


@dataclass
class _AgentResponse:
    text: str
    messages: list[_Message]


@dataclass
class FakeRun:
    """One scripted agent turn.

    Attributes:
        deltas: text fragments to stream as ``DeltaEvent``s.
        tool_calls: list of (name, arguments, result) tuples.
        error: if set, raises this string when the stream is iterated.
        emit_arg_fragments: when True, mimic the framework's habit of
            streaming JSON arguments token-by-token across multiple
            ``function_call`` updates (with the same ``call_id``).
    """

    deltas: list[str] = field(default_factory=list)
    tool_calls: list[tuple[str, dict[str, Any], str | None]] = field(
        default_factory=list,
    )
    error: str | None = None
    emit_arg_fragments: bool = False


class _FakeStream:
    def __init__(self, run: FakeRun) -> None:
        self._run = run
        self._final_response = self._build_final()

    def _build_final(self) -> _AgentResponse:
        msgs = [_Message(contents=[_Content(type="text")])]
        for i, (name, args, result) in enumerate(self._run.tool_calls):
            cid = f"call-{i}"
            msgs.append(
                _Message(
                    contents=[
                        _Content(
                            type="function_call",
                            call_id=cid,
                            name=name,
                            arguments=json.dumps(args),
                        ),
                    ],
                ),
            )
            msgs.append(
                _Message(
                    contents=[
                        _Content(type="function_result", call_id=cid, result=result),
                    ],
                ),
            )
        return _AgentResponse(text="".join(self._run.deltas), messages=msgs)

    def __aiter__(self) -> _FakeStream:
        self._iter = self._gen()
        return self

    async def __anext__(self) -> _Update:
        return await self._iter.__anext__()

    async def _gen(self) -> AsyncIterator[_Update]:
        if self._run.error is not None:
            raise RuntimeError(self._run.error)
        for delta in self._run.deltas:
            yield _Update(text=delta)
        for i, (name, args, result) in enumerate(self._run.tool_calls):
            cid = f"call-{i}"
            if self._run.emit_arg_fragments:
                # Mimic the framework: name on first frame, JSON
                # arguments dribbled across subsequent frames with
                # the same call_id but no name.
                yield _Update(
                    contents=[
                        _Content(type="function_call", call_id=cid, name=name),
                    ],
                )
                payload = json.dumps(args)
                # split into ~4-char chunks
                for chunk in (payload[k : k + 4] for k in range(0, len(payload), 4)):
                    yield _Update(
                        contents=[
                            _Content(
                                type="function_call",
                                call_id=cid,
                                name="",
                                arguments=chunk,
                            ),
                        ],
                    )
            else:
                yield _Update(
                    contents=[
                        _Content(
                            type="function_call",
                            call_id=cid,
                            name=name,
                            arguments=json.dumps(args),
                        ),
                    ],
                )
            yield _Update(
                contents=[_Content(type="function_result", call_id=cid, result=result)],
            )

    async def get_final_response(self) -> _AgentResponse:
        return self._final_response


class _FakeAgent:
    def __init__(self, run: FakeRun, recorder: list[Any]) -> None:
        self._run = run
        self._recorder = recorder

    def run(self, prompt: str, *, session: AgentSession, stream: bool) -> _FakeStream:
        # Snapshot what the runner passed in so tests can introspect.
        self._recorder.append(
            {
                "prompt": prompt,
                "stream": stream,
                "session_messages": list(
                    session.state.get("in_memory", {}).get("messages", []),
                ),
            },
        )
        return _FakeStream(self._run)


class FakeAgentBuilder:
    """Pluggable replacement for ``helpdesk_agent.agent.build_agent``.

    Tests queue one or more ``FakeRun`` specs; each call to the
    builder returns a fake agent whose ``.run()`` yields the next
    queued run. ``raise_on_build`` makes the builder itself raise
    (mirrors "no provider configured").
    """

    def __init__(self) -> None:
        self._queue: list[FakeRun] = []
        self._build_error: str | None = None
        self._calls: list[Any] = []

    def queue(self, run: FakeRun) -> None:
        self._queue.append(run)

    def raise_on_build(self, msg: str) -> None:
        self._build_error = msg

    def last_session_messages(self) -> list[Any]:
        if not self._calls:
            return []
        return list(self._calls[-1]["session_messages"])

    def __call__(self) -> Agent[Any]:
        if self._build_error is not None:
            raise ValueError(self._build_error)
        # Default to a noop run when the queue is empty so callers
        # testing validation paths don't have to queue one.
        run = self._queue.pop(0) if self._queue else FakeRun(deltas=[""], tool_calls=[])
        # ``_FakeAgent`` is duck-typed against ``Agent`` for the surface
        # ``run_turn`` exercises. The cast scopes the type relaxation
        # to this single boundary so production code keeps the strict
        # ``Callable[[], Agent[Any]]`` factory contract.
        return cast("Agent[Any]", _FakeAgent(run, self._calls))


@pytest.fixture
def fake_agent() -> FakeAgentBuilder:
    return FakeAgentBuilder()


@pytest.fixture
def app(fake_agent: FakeAgentBuilder) -> FastAPI:
    app = create_app()
    # ``get_agent_factory`` is itself a dependency that *returns* the
    # factory. Tests override it with a function returning the fake.
    app.dependency_overrides[get_agent_factory] = lambda: fake_agent
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterable[TestClient]:
    with TestClient(app) as c:
        yield c


# --- SSE parser used by tests --------------------------------------------


def parse_sse(lines: Iterable[bytes | str]) -> list[tuple[str, dict[str, Any]]]:
    """Parse a streamed SSE body into a list of ``(event, payload)`` tuples."""
    out: list[tuple[str, dict[str, Any]]] = []
    event = "message"
    data_lines: list[str] = []
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else raw
        if line == "":
            if data_lines:
                out.append((event, json.loads("\n".join(data_lines))))
            event = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
    if data_lines:
        out.append((event, json.loads("\n".join(data_lines))))
    return out


# Re-export dataclasses for tests that want to construct events directly.
__all__ = [
    "FakeAgentBuilder",
    "FakeRun",
    "dataclasses",
    "parse_sse",
]
