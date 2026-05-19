# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Command-line entry point for the auth proxy.

Registered as ``auth-proxy`` in pyproject.toml. Supports:
    auth-proxy init-config   — Create a template config file
    auth-proxy serve         — Start the proxy (default)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from openclaw.auth.routes import (
    DEFAULT_CONFIG_PATH,
    init_config,
    routes_from_config,
    routes_from_env,
)
from openclaw.auth.server import AuthProxy, JsonlRequestLogger

logger = logging.getLogger("auth_proxy")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 12435


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auth-injecting reverse proxy for sandboxed AI agents"
    )
    sub = parser.add_subparsers(dest="command")

    # init-config
    init_parser = sub.add_parser(
        "init-config",
        help="Create a template config file at ~/.config/auth_proxy/config.json",
    )
    init_parser.add_argument(
        "--config", type=Path, default=None,
        help=f"Config path (default: {DEFAULT_CONFIG_PATH})",
    )

    # serve
    serve_parser = sub.add_parser("serve", help="Start the auth proxy")
    serve_parser.add_argument("--host", default=_DEFAULT_HOST)
    serve_parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    serve_parser.add_argument(
        "--config", type=Path, default=None,
        help=f"Config file path (default: {DEFAULT_CONFIG_PATH})",
    )
    serve_parser.add_argument(
        "--log-bodies", action="store_true",
        help="Capture request/response bodies in the request log",
    )
    serve_parser.add_argument(
        "--request-log", default=None,
        help="Path for JSONL request log (enables logging)",
    )
    serve_parser.add_argument(
        "-v", "--verbose", action="store_true", help="DEBUG-level logging"
    )

    args = parser.parse_args()

    # Default to 'serve' if no subcommand given.
    if args.command is None:
        args.command = "serve"
        args.host = _DEFAULT_HOST
        args.port = _DEFAULT_PORT
        args.config = None
        args.log_bodies = False
        args.request_log = None
        args.verbose = False

    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.command == "init-config":
        path = init_config(args.config)
        print(f"Config file: {path}")
        print("Edit it with your API keys, then run: auth-proxy serve")
        return

    # serve
    config_path = args.config or DEFAULT_CONFIG_PATH

    if config_path.exists():
        logger.info("Loading config from %s", config_path)
        routes = routes_from_config(config_path)
    else:
        logger.info(
            "No config file at %s — falling back to env vars. "
            "Run 'auth-proxy init-config' to create one.",
            config_path,
        )
        routes = routes_from_env()

    if not routes:
        logger.error(
            "No routes configured. Either:\n"
            "  1. Run: auth-proxy init-config\n"
            "     Then edit %s with your keys.\n"
            "  2. Set env vars: OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "AZURE_OPENAI_ENDPOINT, etc.",
            config_path,
        )
        sys.exit(1)

    req_logger = JsonlRequestLogger(path=args.request_log) if args.request_log else None

    proxy = AuthProxy(
        routes=routes,
        host=args.host,
        port=args.port,
        request_logger=req_logger,
        log_bodies=args.log_bodies,
    )
    proxy.run()


if __name__ == "__main__":
    main()
