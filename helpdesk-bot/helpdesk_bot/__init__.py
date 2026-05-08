# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""HelpdeskBot: RAMPART showcase package.

Re-exports the public surface so callers can write::

    from helpdesk_bot import HelpdeskAdapter, LocalTicketSurface

without reaching into individual modules. Submodules remain importable
directly for tests and for the README walkthrough.
"""

from helpdesk_bot.adapter import HelpdeskAdapter, HelpdeskSession
from helpdesk_bot.agent import build_agent
from helpdesk_bot.manifest import HELPDESK_MANIFEST
from helpdesk_bot.surface import LocalTicketSurface, TicketStore

__all__ = [
    "HELPDESK_MANIFEST",
    "HelpdeskAdapter",
    "HelpdeskSession",
    "LocalTicketSurface",
    "TicketStore",
    "build_agent",
]
