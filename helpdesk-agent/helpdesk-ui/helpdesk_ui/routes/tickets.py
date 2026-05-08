# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Ticket CRUD routes."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status
from helpdesk_agent.surface import TicketStore

from helpdesk_ui.schemas import TicketCreate, TicketDetail, TicketSummary

if TYPE_CHECKING:
    from pathlib import Path

router = APIRouter()

_TICKET_ID_PATTERN = re.compile(r"^T-(\d+)$")
_PREVIEW_LEN = 140
_FIRST_RUNTIME_ID = 1003
"""Starting id when the ticket dir is empty (test isolation)."""

_SAMPLE_TICKET_ID = "T-1003"


def _store() -> TicketStore:
    return TicketStore()


def _next_ticket_id(root: Path) -> str:
    highest = _FIRST_RUNTIME_ID - 1
    if root.exists():
        for path in root.glob("T-*.json"):
            match = _TICKET_ID_PATTERN.match(path.stem)
            if match is not None:
                highest = max(highest, int(match.group(1)))
    return f"T-{highest + 1}"


def _read_summary(root: Path, ticket_id: str) -> TicketSummary | None:
    path = root / f"{ticket_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stat = path.stat()
    except (OSError, json.JSONDecodeError):
        return None
    body = str(data.get("body", ""))
    preview = body.replace("\n", " ").strip()
    if len(preview) > _PREVIEW_LEN:
        preview = preview[: _PREVIEW_LEN - 3] + "..."
    return TicketSummary(
        id=ticket_id,
        subject=str(data.get("subject", "")),
        sender=str(data.get("from", "unknown@unknown")),
        preview=preview,
        mtime_ns=stat.st_mtime_ns,
    )


def _read_detail(root: Path, ticket_id: str) -> TicketDetail:
    path = root / f"{ticket_id}.json"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Ticket {ticket_id} not found.")
    data = json.loads(path.read_text(encoding="utf-8"))
    stat = path.stat()
    return TicketDetail(
        id=ticket_id,
        subject=str(data.get("subject", "")),
        sender=str(data.get("from", "unknown@unknown")),
        body=str(data.get("body", "")),
        mtime_ns=stat.st_mtime_ns,
        rendered=TicketStore(root=root).read(ticket_id),
    )


@router.get("/tickets", response_model=list[TicketSummary])
async def list_tickets() -> list[TicketSummary]:
    """List all tickets in the inbox, newest first by mtime."""
    store = _store()
    if not store.root.exists():
        return []
    summaries: list[TicketSummary] = []
    for path in store.root.glob("T-*.json"):
        summary = _read_summary(store.root, path.stem)
        if summary is not None:
            summaries.append(summary)
    summaries.sort(key=lambda t: t.mtime_ns, reverse=True)
    return summaries


@router.get("/tickets/sample", response_model=TicketDetail)
async def sample_ticket() -> TicketDetail:
    """Return the seeded sample ticket (T-1003).

    Used by the new-ticket form's "Load sample ticket" button. Returns
    404 in test envs that haven't seeded T-1003; the frontend hides
    the button on 404.
    """
    return _read_detail(_store().root, _SAMPLE_TICKET_ID)


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: str) -> TicketDetail:
    """Return one ticket's full envelope."""
    if not _TICKET_ID_PATTERN.match(ticket_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid ticket id.")
    return _read_detail(_store().root, ticket_id)


@router.post(
    "/tickets",
    response_model=TicketDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket(payload: TicketCreate) -> TicketDetail:
    """File a new ticket; allocates the next ``T-####`` id."""
    store = _store()
    ticket_id = _next_ticket_id(store.root)
    store.write(ticket_id, subject=payload.subject, body=payload.body, sender=payload.sender)
    return _read_detail(store.root, ticket_id)


@router.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(ticket_id: str) -> None:
    """Delete a ticket. Idempotent on missing files."""
    if not _TICKET_ID_PATTERN.match(ticket_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid ticket id.")
    _store().delete(ticket_id)
