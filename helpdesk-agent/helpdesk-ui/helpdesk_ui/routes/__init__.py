# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""HTTP routes for the helpdesk-ui demo."""

from __future__ import annotations

from fastapi import APIRouter

from helpdesk_ui.routes import chat, meta, tickets

api_router = APIRouter(prefix="/api")
api_router.include_router(tickets.router)
api_router.include_router(chat.router)
api_router.include_router(meta.router)
