# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Public-facing agent UI for HelpdeskBot.

A small FastAPI + vanilla-JS web app that lets a developer chat with
the HelpdeskBot agent under test and inspect the tools it calls along
the way. Lives in its own subpackage so the UI's HTTP and frontend
concerns don't leak into the core agent or RAMPART test surface.
"""
