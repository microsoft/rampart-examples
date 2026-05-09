# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Pydantic schemas for the helpdesk-ui HTTP surface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

_SENDER_ALIAS = AliasChoices("sender", "from")


class TicketSummary(BaseModel):
    """Lightweight ticket record for inbox listings."""

    id: str
    subject: str
    sender: str = Field(validation_alias=_SENDER_ALIAS, serialization_alias="from")
    preview: str
    mtime_ns: int


class TicketDetail(BaseModel):
    """Full ticket envelope as the agent ingests it."""

    id: str
    subject: str
    sender: str = Field(validation_alias=_SENDER_ALIAS, serialization_alias="from")
    body: str
    mtime_ns: int
    rendered: str
    """Plain-text envelope produced by ``TicketStore.read``."""


class TicketCreate(BaseModel):
    """Inbound payload for ``POST /api/tickets``."""

    subject: str = Field(min_length=1, max_length=200)
    sender: str = Field(
        min_length=3,
        max_length=200,
        validation_alias=_SENDER_ALIAS,
        serialization_alias="from",
    )
    body: str = Field(min_length=1, max_length=10_000)


class ToolCall(BaseModel):
    """One agent tool invocation, as surfaced to the UI."""

    name: str
    arguments: dict[str, Any]
    result: str | None = None


class ChatMessage(BaseModel):
    """One prior turn replayed to the agent for THIS request.

    ``tool_calls`` is None for user messages and a (possibly empty)
    list for assistant messages.
    """

    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[ToolCall] | None = None


class ChatRequest(BaseModel):
    """Conversation prior to and including the new user message.

    The last message MUST have ``role == "user"``; this is enforced
    by the route handler (400 on violation).
    """

    messages: Sequence[ChatMessage] = Field(min_length=1)


ChatRequest.model_rebuild()
