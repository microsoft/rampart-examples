# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Web demo app for HelpdeskAgent.

A small FastAPI + React app that visualises the *manual* path through
the helpdesk agent for Demo 2 (incident replication). The Python
package lives at ``helpdesk_ui``; the React frontend lives next to it
at ``helpdesk-agent/helpdesk-ui/frontend/`` and builds into
``frontend/dist/`` (Vite's default output).

Heavy imports (``fastapi``, ``uvicorn``) are intentionally not made at
package import time. Use ``helpdesk_ui.app.create_app`` or ``run``
from a workspace venv that has ``helpdesk-ui`` installed (``uv sync``
or ``pip install -e helpdesk-agent/helpdesk-ui``).
"""
