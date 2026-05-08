# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Streaming chat route. Thin shell over ``helpdesk_ui.agent_runner``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, status
from fastapi.params import Depends
from fastapi.responses import StreamingResponse
from helpdesk_agent.agent import build_agent

from helpdesk_ui.agent_runner import AgentFactory, _event_to_sse, run_turn
from helpdesk_ui.schemas import ChatRequest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

router = APIRouter()


def get_agent_factory() -> AgentFactory:
    """Dependency to retrieve the agent factory.

    By default, this is the real
    factory that builds a functioning agent; tests override it with a fake.
    """
    return build_agent


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    agent_factory: Annotated[AgentFactory, Depends(get_agent_factory)],
) -> StreamingResponse:
    """Stream one agent turn as Server-Sent Events.

    Validation only (400 on a bad last-message shape); all agent
    behaviour, tool-call dedup, and error surfacing live in
    ``run_turn``. Failures during the stream are emitted in-band as
    ``error`` events; the HTTP status is fixed at 200 once streaming
    begins.
    """
    last = req.messages[-1]
    if last.role != "user" or not last.content.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Last message must be a non-empty user turn.",
        )

    async def event_stream() -> AsyncGenerator[str, None]:
        async for event in run_turn(req.messages, agent_factory=agent_factory):
            yield _event_to_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
