# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""HelpdeskAgent: RAMPART showcase package.

Re-exports the public surface so callers can write::

    from helpdesk_agent import HelpdeskAdapter, LocalTicketSurface

without reaching into individual modules. Submodules remain importable
directly for tests and for the README walkthrough.
"""

from helpdesk_agent.adapter import HelpdeskAdapter, HelpdeskSession
from helpdesk_agent.agent import build_agent
from helpdesk_agent.manifest import HELPDESK_MANIFEST
from helpdesk_agent.surface import LocalTicketSurface, TicketStore

__all__ = [
    "HELPDESK_MANIFEST",
    "HelpdeskAdapter",
    "HelpdeskSession",
    "LocalTicketSurface",
    "TicketStore",
    "build_agent",
]
