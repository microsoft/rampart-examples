# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""RAMPART-OpenClaw: sandboxed agent testing with auth proxy."""

from openclaw.adapter import OpenClawAdapter, OpenClawSession
from openclaw.html_report import HtmlReportSink
from openclaw.surface import (
    InjectionTarget,
    PluginToolSurface,
)

__all__ = [
    "HtmlReportSink",
    "InjectionTarget",
    "OpenClawAdapter",
    "OpenClawSession",
    "PluginToolSurface",
]
