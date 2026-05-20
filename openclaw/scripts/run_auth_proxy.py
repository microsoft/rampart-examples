# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Convenience script to start the auth proxy server.

Usage:
    python scripts/run_auth_proxy.py
    python scripts/run_auth_proxy.py --port 12435 --verbose
    python scripts/run_auth_proxy.py --config /path/to/config.json --log-bodies --request-log proxy.jsonl
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly without pip install -e .
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from openclaw.auth.cli import main

if __name__ == "__main__":
    main()
