# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Schema alias round-trips."""

from __future__ import annotations

from helpdesk_ui.schemas import ChatMessage, TicketCreate, TicketSummary, ToolCall


def test_ticket_summary_alias_round_trip() -> None:
    t = TicketSummary(
        id="T-1",
        subject="s",
        sender="a@b.com",
        preview="p",
        mtime_ns=0,
    )
    dumped = t.model_dump(by_alias=True)
    assert dumped["from"] == "a@b.com"
    again = TicketSummary.model_validate(dumped)
    assert again.sender == "a@b.com"


def test_ticket_create_accepts_both_aliases() -> None:
    a = TicketCreate.model_validate(
        {"subject": "x", "from": "a@b.com", "body": "y"},
    )
    b = TicketCreate.model_validate(
        {"subject": "x", "sender": "a@b.com", "body": "y"},
    )
    assert a.sender == b.sender == "a@b.com"


def test_chat_message_round_trip() -> None:
    msg = ChatMessage(
        role="assistant",
        content="hi",
        tool_calls=[ToolCall(name="t", arguments={"k": 1}, result="ok")],
    )
    again = ChatMessage.model_validate(msg.model_dump())
    assert again.tool_calls is not None
    assert again.tool_calls[0].name == "t"


def test_user_message_no_tool_calls_default() -> None:
    msg = ChatMessage(role="user", content="hi")
    assert msg.tool_calls is None
