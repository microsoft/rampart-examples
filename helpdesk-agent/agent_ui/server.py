# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""FastAPI backend for the HelpdeskAgent agent UI.

Wraps the ``helpdesk_agent`` agent under test in a small HTTP surface so
a browser-based UI can chat with it and inspect tool calls. Each
browser session gets a single ``Agent`` plus an ``AgentSession`` so
multi-turn conversation history is preserved.

Endpoints:
    GET    /                  Single-page HTML UI.
    GET    /api/tickets       List tickets currently in the store.
    GET    /api/tickets/{id}  Fetch a single ticket's structured fields.
    POST   /api/tickets       File a new ticket; auto-allocates the next T-####.
    DELETE /api/tickets/{id}  Remove a ticket from the store.
    POST   /api/chat          Send a prompt; returns reply + tool calls.
    POST   /api/reset         Drop the current conversation; start fresh.
    GET    /api/history       Replay prior turns for UI rehydration.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from agent_framework import AgentSession
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from helpdesk_agent.agent import build_agent
from helpdesk_agent.surface import TicketStore

# Load .env once at import time so the agent's chat-client factory
# sees the provider credentials. Mirrors what tests/conftest.py does.
_DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_DOTENV_PATH if _DOTENV_PATH.exists() else None)

_logger = logging.getLogger(__name__)

_STATIC_DIR: Path = Path(__file__).resolve().parent / "static"

# A "browser session" maps to one agent + one AgentSession (history).
# In-memory only: this is a developer-facing UI, not multi-tenant.
_BROWSER_SESSIONS: dict[str, "_ChatSession"] = {}

_SESSION_COOKIE = "helpdesk_agent_ui_sid"


class _ChatSession:
    """Per-browser chat state.

    Holds a freshly-built agent, the ``AgentSession`` that carries
    conversation history across turns, and a list of completed turns
    that the UI can use to re-render history on page reload.
    """

    def __init__(self) -> None:
        self.agent = build_agent()
        self.session = AgentSession()
        self.turns: list[dict[str, Any]] = []


def _get_or_create_session(sid: str | None) -> tuple[str, _ChatSession]:
    """Return (sid, session) creating a new session if cookie is missing."""
    if sid and sid in _BROWSER_SESSIONS:
        return sid, _BROWSER_SESSIONS[sid]
    new_sid = uuid.uuid4().hex
    _BROWSER_SESSIONS[new_sid] = _ChatSession()
    return new_sid, _BROWSER_SESSIONS[new_sid]


# --- Tool-call extraction (mirrors helpdesk_agent.adapter) -----------------


def _parse_arguments(raw: object) -> dict[str, object]:
    """Normalise an Agent-Framework function_call arguments value to a dict."""
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


def _extract_tool_calls(agent_response: object) -> list[dict[str, Any]]:
    """Extract function_call/function_result content from an AgentResponse.

    Same shape as ``HelpdeskSession._extract_tool_calls`` but emits
    plain dicts ready for JSON serialisation to the browser.
    """
    messages = getattr(agent_response, "messages", None) or []

    results_by_call_id: dict[str, str] = {}
    for msg in messages:
        for content in getattr(msg, "contents", None) or []:
            if getattr(content, "type", None) != "function_result":
                continue
            call_id = getattr(content, "call_id", None)
            if call_id is None:
                continue
            result = getattr(content, "result", None)
            if result is None:
                continue
            results_by_call_id[call_id] = (
                result if isinstance(result, str) else str(result)
            )

    tool_calls: list[dict[str, Any]] = []
    for msg in messages:
        for content in getattr(msg, "contents", None) or []:
            if getattr(content, "type", None) != "function_call":
                continue
            tool_calls.append(
                {
                    "name": getattr(content, "name", None) or "",
                    "arguments": _parse_arguments(
                        getattr(content, "arguments", None),
                    ),
                    "result": results_by_call_id.get(
                        getattr(content, "call_id", "") or "",
                    ),
                },
            )
    return tool_calls


# --- Request / response models ------------------------------------------


class ChatRequest(BaseModel):
    """A single user turn from the browser."""

    message: str


class CreateTicketRequest(BaseModel):
    """Payload for ``POST /api/tickets``.

    The ``body`` is fully attacker-controlled; that's the demo. We do
    not sanitise it here — the whole point is that RAMPART probes feed
    poisoned bodies through the agent and assert the hardened version
    refuses to act on them.
    """

    subject: str
    sender: str
    body: str


class ToolCallView(BaseModel):
    """Tool call rendered for the UI."""

    name: str
    arguments: dict[str, Any]
    result: str | None = None


class ChatResponseModel(BaseModel):
    """Reply payload for ``POST /api/chat``."""

    reply: str
    tool_calls: list[ToolCallView]


class TicketSummary(BaseModel):
    """Lightweight ticket summary for the sidebar."""

    id: str
    subject: str
    sender: str
    preview: str


class TicketDetail(BaseModel):
    """Full ticket payload."""

    id: str
    subject: str
    sender: str
    body: str


# --- Ticket id allocation -----------------------------------------------


_TICKET_ID_PREFIX = "T-"
_TICKET_ID_START = 1001


def _allocate_ticket_id(store: TicketStore) -> str:
    """Return the next free ``T-####`` id in the store.

    Scans existing ``T-<digits>.json`` filenames, takes max + 1, falling
    back to ``T-1001`` for an empty store. Files that don't match the
    pattern are ignored so a hand-placed ``poisoned.json`` won't shift
    the sequence.
    """
    if not store.root.exists():
        return f"{_TICKET_ID_PREFIX}{_TICKET_ID_START}"
    highest = _TICKET_ID_START - 1
    for path in store.root.glob(f"{_TICKET_ID_PREFIX}*.json"):
        suffix = path.stem[len(_TICKET_ID_PREFIX):]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{_TICKET_ID_PREFIX}{highest + 1}"


# --- App ----------------------------------------------------------------


def create_app() -> FastAPI:
    """Build the FastAPI app for the HelpdeskAgent agent UI."""
    app = FastAPI(
        title="HelpdeskAgent Agent UI",
        description="Developer UI for chatting with the HelpdeskAgent agent under test.",
        version="0.1.0",
    )

    app.mount(
        "/static",
        StaticFiles(directory=_STATIC_DIR),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/tickets", response_model=list[TicketSummary])
    async def list_tickets() -> list[TicketSummary]:
        store = TicketStore()
        if not store.root.exists():
            return []
        summaries: list[TicketSummary] = []
        for path in sorted(store.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            body = str(data.get("body", ""))
            summaries.append(
                TicketSummary(
                    id=path.stem,
                    subject=str(data.get("subject", "")),
                    sender=str(data.get("from", "unknown@unknown")),
                    preview=body[:120] + ("..." if len(body) > 120 else ""),
                ),
            )
        return summaries

    @app.get("/api/tickets/{ticket_id}", response_model=TicketDetail)
    async def get_ticket(ticket_id: str) -> TicketDetail:
        store = TicketStore()
        path = store.root / f"{ticket_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
        data = json.loads(path.read_text(encoding="utf-8"))
        return TicketDetail(
            id=ticket_id,
            subject=str(data.get("subject", "")),
            sender=str(data.get("from", "unknown@unknown")),
            body=str(data.get("body", "")),
        )

    @app.post("/api/tickets", response_model=TicketDetail, status_code=201)
    async def create_ticket(payload: CreateTicketRequest) -> TicketDetail:
        if not payload.subject.strip():
            raise HTTPException(status_code=400, detail="Subject is required.")
        if not payload.sender.strip():
            raise HTTPException(status_code=400, detail="Sender is required.")
        if not payload.body.strip():
            raise HTTPException(status_code=400, detail="Body is required.")
        store = TicketStore()
        ticket_id = _allocate_ticket_id(store)
        store.write(
            ticket_id,
            subject=payload.subject,
            body=payload.body,
            sender=payload.sender,
        )
        return TicketDetail(
            id=ticket_id,
            subject=payload.subject,
            sender=payload.sender,
            body=payload.body,
        )

    @app.delete("/api/tickets/{ticket_id}", status_code=204)
    async def delete_ticket(ticket_id: str) -> Response:
        store = TicketStore()
        path = store.root / f"{ticket_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")
        store.delete(ticket_id)
        return Response(status_code=204)

    @app.post("/api/chat", response_model=ChatResponseModel)
    async def chat(
        body: ChatRequest,
        response: Response,
        sid: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
    ) -> ChatResponseModel:
        if not body.message.strip():
            raise HTTPException(status_code=400, detail="Empty message.")
        try:
            new_sid, chat_session = _get_or_create_session(sid)
        except ValueError as exc:
            # build_agent() raises ValueError when no provider is set.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if new_sid != sid:
            response.set_cookie(
                key=_SESSION_COOKIE,
                value=new_sid,
                httponly=True,
                samesite="lax",
            )
        try:
            agent_response = await chat_session.agent.run(
                body.message,
                session=chat_session.session,
            )
        except Exception as exc:  # noqa: BLE001 — surface provider errors verbatim
            _logger.exception("Agent run failed.")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        tool_calls = [ToolCallView(**tc) for tc in _extract_tool_calls(agent_response)]
        reply = getattr(agent_response, "text", "") or ""
        # Snapshot the turn so /api/history can rehydrate the UI on reload.
        chat_session.turns.append(
            {
                "user": body.message,
                "reply": reply,
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            },
        )
        return ChatResponseModel(reply=reply, tool_calls=tool_calls)

    @app.post("/api/reset")
    async def reset(
        response: Response,
        sid: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
    ) -> dict[str, str]:
        if sid and sid in _BROWSER_SESSIONS:
            del _BROWSER_SESSIONS[sid]
        response.delete_cookie(_SESSION_COOKIE)
        return {"status": "ok"}

    @app.get("/api/history")
    async def history(
        sid: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
    ) -> dict[str, Any]:
        """Return prior turns so the UI can rehydrate after a page reload.

        The browser cookie outlives the page, so without this endpoint a
        refresh hides the earlier turns from the UI while the backend
        agent still remembers them — leading to confusing "the agent
        answered without calling a tool" moments.
        """
        if not sid or sid not in _BROWSER_SESSIONS:
            return {"turns": []}
        return {"turns": list(_BROWSER_SESSIONS[sid].turns)}

    return app


app = create_app()


def main() -> None:
    """CLI entry point: ``python agent-ui/server.py`` boots the agent UI server."""
    import uvicorn  # noqa: PLC0415 — keep import lazy so tests don't pay for it

    host = os.getenv("HELPDESK_AGENT_UI_HOST", "127.0.0.1")
    port = int(os.getenv("HELPDESK_AGENT_UI_PORT", "8000"))
    logging.basicConfig(level=logging.INFO)
    _logger.info("Starting HelpdeskAgent agent UI on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
