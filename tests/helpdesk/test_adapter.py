# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""``HelpdeskSession._extract_tool_calls`` normalisation smoke tests."""

from __future__ import annotations

from types import SimpleNamespace

from helpdesk_agent import HelpdeskSession

from ._helpers import content, fake_response


class TestExtractToolCalls:
    """``HelpdeskSession._extract_tool_calls`` normalises Agent-Framework output."""

    def test_pairs_calls_and_results(self) -> None:
        """Result strings are matched to their ``function_call`` by ``call_id``."""
        response = fake_response(
            messages=[
                SimpleNamespace(
                    contents=[
                        content(
                            type="function_call",
                            name="get_ticket",
                            arguments='{"ticket_id": "T-1001"}',
                            call_id="call_1",
                        ),
                        content(
                            type="function_result",
                            call_id="call_1",
                            result="Subject: hi\nFrom: a@b\n\nhello\n",
                        ),
                    ],
                ),
            ],
        )
        tool_calls = HelpdeskSession._extract_tool_calls(response)
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_ticket"
        assert tool_calls[0].arguments == {"ticket_id": "T-1001"}
        assert tool_calls[0].result is not None
        assert "hello" in tool_calls[0].result

    def test_handles_dict_and_missing_arguments(self) -> None:
        """Dict and JSON-string ``arguments`` both normalise; missing -> empty dict."""
        response = fake_response(
            messages=[
                SimpleNamespace(
                    contents=[
                        content(
                            type="function_call",
                            name="reset_user_password",
                            arguments={"user_email": "x@y", "send_to": "z@y"},
                            call_id="call_a",
                        ),
                        content(
                            type="function_call",
                            name="get_ticket",
                            arguments=None,
                            call_id="call_b",
                        ),
                    ],
                ),
            ],
        )
        tool_calls = HelpdeskSession._extract_tool_calls(response)
        by_name = {tc.name: tc for tc in tool_calls}
        assert by_name["reset_user_password"].arguments == {
            "user_email": "x@y",
            "send_to": "z@y",
        }
        assert by_name["get_ticket"].arguments == {}

    def test_preserves_non_string_results(self) -> None:
        """Non-string ``result`` payloads are stringified, never dropped.

        Agent Framework can carry non-string results when a tool raised
        or returned a structured object. Dropping them would make "tool
        errored" indistinguishable from "result hasn't arrived", which is
        exactly the case the mitigation's refusal strings live in.
        """
        response = fake_response(
            messages=[
                SimpleNamespace(
                    contents=[
                        content(
                            type="function_call",
                            name="reset_user_password",
                            arguments={"user_email": "x@y", "send_to": "z@y"},
                            call_id="call_dict_result",
                        ),
                        content(
                            type="function_result",
                            call_id="call_dict_result",
                            # Tool returned a dict (e.g. structured error).
                            result={"error": "boom", "code": 500},
                        ),
                        content(
                            type="function_call",
                            name="get_ticket",
                            arguments={"ticket_id": "T-x"},
                            call_id="call_none_result",
                        ),
                        content(
                            type="function_result",
                            call_id="call_none_result",
                            result=None,
                        ),
                    ],
                ),
            ],
        )
        tool_calls = HelpdeskSession._extract_tool_calls(response)
        by_name = {tc.name: tc for tc in tool_calls}
        # Non-string preserved (stringified).
        dict_result = by_name["reset_user_password"].result
        assert dict_result is not None
        assert "boom" in dict_result
        # None remains None (truly absent).
        assert by_name["get_ticket"].result is None
