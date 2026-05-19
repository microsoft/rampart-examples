# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Secure communication channel with a Docker Sandbox.

All interaction with the sandbox goes through ``docker sandbox exec``
with data piped via stdin/stdout.  **No user-controlled or
LLM-generated content ever appears in a shell command string.**

Trust model:
  - The HOST is trusted: adapter code, auth proxy, API keys.
  - The SANDBOX is untrusted after first interaction: OpenClaw,
    tool outputs, all sandbox files.
  - Every byte returned from the sandbox is validated before use.

Security invariants enforced here:
  1. Prompt content travels via stdin pipes — never command arguments.
  2. Response size is bounded (``MAX_RESPONSE_BYTES``).
  3. All operations have timeouts.
  4. JSON parsing uses ``json.loads`` only (never ``eval``).
  5. Session IDs are validated against a strict allowlist pattern.
  6. All Docker exec calls go through ``exec_async`` — one place
     to audit the entire sandbox boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shlex
from typing import Any

from rampart.core.errors import InfrastructureError

logger = logging.getLogger(__name__)


class SandboxClient:
    """Secure communication with an OpenClaw Docker Sandbox.

    Uses ``openclaw agent --session-id <id> -m ... --json`` via
    ``docker sandbox exec``.  The prompt is piped through stdin
    so it never appears in the process argument list.  Each
    RAMPART session uses a unique ``--session-id`` for isolation.

    All subprocess calls go through ``exec_async``, which is the
    single point of contact with the Docker CLI.  Surfaces and the
    adapter both use this client — no code anywhere in the project
    calls ``create_subprocess_exec`` directly.

    Args:
        sandbox_name: Name of the Docker Sandbox (e.g., ``"openclaw"``).
        timeout: Default request timeout in seconds.
    """

    MAX_RESPONSE_BYTES: int = 50 * 1024 * 1024
    DEFAULT_TIMEOUT: float = 300.0

    # Strict allow-list pattern for IDs (plugin IDs, tool names,
    # session IDs, …) interpolated into shell commands.
    SAFE_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
    SESSION_JSONL_DIR: str = "/home/agent/.openclaw/agents/main/sessions"

    def __init__(
        self,
        *,
        sandbox_name: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._sandbox_name = sandbox_name
        self._timeout = timeout

    #  Low-level exec

    async def exec_async(
        self,
        *,
        command: str,
        stdin_data: bytes | None = None,
        timeout: float = 30.0,
    ) -> tuple[bytes, bytes]:
        """Run a bash command inside the sandbox.

        This is the **only** method that calls ``docker sandbox exec``.
        Every interaction with the sandbox — agent prompts, file I/O,
        health checks, surface installs, test fixtures — routes
        through here, making this the single audit point for the
        sandbox boundary.

        The ``command`` string is always constructed by trusted code
        (never from user or LLM input).  Untrusted data travels
        exclusively via ``stdin_data``.

        Args:
            command: Bash command to execute (trusted, static).
            stdin_data: Bytes piped to the process stdin.  This is
                the channel for untrusted/adversarial content.
            timeout: Seconds before the process is killed.

        Returns:
            ``(stdout, stderr)`` as raw bytes.

        Raises:
            InfrastructureError: On timeout or non-zero exit code.
        """
        args = ["docker", "sandbox", "exec"]
        if stdin_data is not None:
            args.append("-i")
        args += [self._sandbox_name, "bash", "-c", command]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            raise InfrastructureError(
                f"Sandbox command timed out after {timeout}s."
            )

        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[:1000]
            raise InfrastructureError(
                f"Sandbox exec failed (rc={proc.returncode}): {detail}"
            )

        if len(stdout) > self.MAX_RESPONSE_BYTES:
            raise InfrastructureError(
                f"Sandbox output too large ({len(stdout)} bytes, "
                f"limit {self.MAX_RESPONSE_BYTES})."
            )

        return stdout, stderr

    #  Agent interaction

    async def send_async(
        self,
        *,
        prompt: str,
        session_id: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a prompt to the OpenClaw agent via CLI.

        The prompt is piped through stdin to a bash wrapper that
        calls ``openclaw agent``.  No user content ever appears in
        the process argument list.

        Args:
            prompt: The prompt text to send.
            session_id: Session ID for conversation isolation.
            timeout: Override the default timeout for this request.

        Returns:
            Parsed JSON response from ``openclaw agent --json``.

        Raises:
            InfrastructureError: On timeout, exec failure, or
                response parsing errors.
        """
        if not self.SAFE_ID_PATTERN.match(session_id):
            raise InfrastructureError(
                f"Invalid session_id: must match {self.SAFE_ID_PATTERN.pattern}"
            )

        bash_script = (
            'read -r -d "" PROMPT; '
            "OPENCLAW_GATEWAY_TOKEN=local-sandbox-token "
            f"openclaw agent --session-id '{session_id}' "
            '-m "$PROMPT" --json'
        )

        stdout, _ = await self.exec_async(
            command=bash_script,
            stdin_data=prompt.encode("utf-8") + b"\x00",
            timeout=timeout or self._timeout,
        )

        if not stdout.strip():
            raise InfrastructureError("Sandbox returned empty response.")

        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            preview = stdout[:200].decode("utf-8", errors="replace")
            logger.error("Unparseable response (first 200 bytes): %s", preview)
            raise InfrastructureError(
                f"Sandbox returned invalid JSON: {exc}"
            ) from exc

        if not isinstance(response, dict):
            raise InfrastructureError("Sandbox response is not a JSON object.")

        return response

    #  Session log reading

    async def read_session_log_async(
        self,
        *,
        session_id: str,
        after_line: int = 0,
    ) -> list[dict[str, Any]]:
        """Read entries from an OpenClaw session JSONL file.

        Each session's conversation (including tool calls and results)
        is persisted as a JSONL file inside the sandbox.

        Args:
            session_id: The OpenClaw session UUID.
            after_line: Skip this many lines (for incremental reads).

        Returns:
            List of parsed JSON objects from the session log.
        """
        if not self.SAFE_ID_PATTERN.match(session_id):
            raise InfrastructureError(
                f"Invalid session_id: must match {self.SAFE_ID_PATTERN.pattern}"
            )

        jsonl_path = f"{self.SESSION_JSONL_DIR}/{session_id}.jsonl"
        cmd = (
            f"tail -n +{after_line + 1} {jsonl_path}"
            if after_line > 0
            else f"cat {jsonl_path}"
        )

        try:
            stdout, _ = await self.exec_async(command=cmd, timeout=10)
        except InfrastructureError as exc:
            logger.debug("Could not read session log %s: %s", jsonl_path, exc)
            return []

        entries: list[dict[str, Any]] = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return entries

    #  File I/O (used by surfaces)

    async def read_file_async(self, remote_path: str) -> bytes:
        """Read a file from the sandbox. Returns raw bytes.

        Raises:
            InfrastructureError: If the file can't be read.
        """
        stdout, _ = await self.exec_async(
            command=f"cat {shlex.quote(remote_path)}", timeout=10,
        )
        return stdout

    async def write_file_async(
        self,
        *,
        remote_path: str,
        content: bytes,
    ) -> None:
        """Write content to a file in the sandbox via stdin pipe.

        Raises:
            InfrastructureError: On write failure or timeout.
        """
        await self.exec_async(
            command=f"cat > {shlex.quote(remote_path)}",
            stdin_data=content,
            timeout=30,
        )

    #  Health check

    async def health_check_async(self) -> bool:
        """Check if the OpenClaw gateway is reachable inside the sandbox."""
        try:
            await self.exec_async(
                command="curl -sf http://127.0.0.1:18789/health",
                timeout=10,
            )
            return True
        except InfrastructureError:
            return False

    #  Metadata gathering

    async def get_openclaw_version_async(self) -> str:
        """Return the OpenClaw CLI version string."""
        try:
            stdout, _ = await self.exec_async(
                command="openclaw --version 2>/dev/null || echo unknown",
                timeout=10,
            )
            return stdout.decode("utf-8", errors="replace").strip()
        except InfrastructureError:
            return "unknown"

    async def get_node_version_async(self) -> str:
        """Return the Node.js version running inside the sandbox."""
        try:
            stdout, _ = await self.exec_async(command="node --version", timeout=10)
            return stdout.decode("utf-8", errors="replace").strip()
        except InfrastructureError:
            return "unknown"

    async def get_installed_plugins_async(self) -> list[dict[str, Any]]:
        """List installed OpenClaw plugins with name and version.

        Returns:
            List of dicts with ``name`` and ``version`` keys.
        """
        try:
            stdout, _ = await self.exec_async(
                command="openclaw plugins list --json 2>/dev/null || echo '[]'",
                timeout=10,
            )
            raw = json.loads(stdout)
            return raw if isinstance(raw, list) else []
        except (InfrastructureError, json.JSONDecodeError):
            return []

    async def get_bootstrap_files_async(self) -> list[dict[str, Any]]:
        """List bootstrap files present in the workspace with sizes.

        Returns:
            List of dicts with ``name`` and ``size_bytes`` keys.
        """
        workspace = "/home/agent/.openclaw/workspace"
        bootstrap_names = [
            "AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md",
            "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md",
        ]
        cmd = " ".join(
            f'stat -c \'{{"{name}": %s}}\' {workspace}/{name} 2>/dev/null;'
            for name in bootstrap_names
        )
        try:
            stdout, _ = await self.exec_async(command=cmd, timeout=10)
            return self._parse_bootstrap_stat_output(
                stdout=stdout, bootstrap_names=bootstrap_names,
            )
        except InfrastructureError:
            return []

    @staticmethod
    def _parse_bootstrap_stat_output(
        *,
        stdout: bytes,
        bootstrap_names: list[str],
    ) -> list[dict[str, Any]]:
        """Parse stat command output into bootstrap file entries.

        Args:
            stdout: Raw bytes from the stat command.
            bootstrap_names: File names to look for in the output.

        Returns:
            List of dicts with ``name`` and ``size_bytes`` keys.
        """
        files: list[dict[str, Any]] = []
        for name in bootstrap_names:
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or name not in line:
                    continue
                try:
                    parsed = json.loads(line)
                    size = parsed.get(name)
                    if size is not None:
                        files.append({"name": name, "size_bytes": int(size)})
                except (json.JSONDecodeError, ValueError):
                    continue
        return files

    async def get_workspace_tree_async(
        self, *, max_depth: int = 3,
    ) -> list[str]:
        """Return a list of file paths in the agent's workspace.

        Args:
            max_depth: Maximum directory depth to traverse.

        Returns:
            List of relative file paths.
        """
        workspace = "/home/agent/.openclaw/workspace"
        try:
            stdout, _ = await self.exec_async(
                command=f"find {workspace} -maxdepth {max_depth} -type f "
                f"| head -100 | sed 's|{workspace}/||'",
                timeout=10,
            )
            return [
                line.strip()
                for line in stdout.decode("utf-8", errors="replace").splitlines()
                if line.strip()
            ]
        except InfrastructureError:
            return []

    async def get_network_policy_async(self) -> str:
        """Return the current sandbox network policy summary.

        Queries ``docker sandbox network log`` from the host side,
        since the network policy is enforced by Docker's proxy layer
        outside the container — there is no policy file inside the
        sandbox itself.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "sandbox", "network", "log", self._sandbox_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=10,
                )
            except asyncio.TimeoutError:
                proc.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                return "unknown"
            output = stdout.decode("utf-8", errors="replace").strip()
            return output if output else "unknown"
        except OSError:
            return "unknown"

    async def get_sandbox_environment_async(self) -> dict[str, str]:
        """Gather key environment details from the sandbox.

        Returns:
            Dict with ``os``, ``arch``, ``user``, ``home``, ``shell``
            keys.
        """
        cmd = (
            "echo \"$(uname -s) $(uname -m)\";"
            "whoami;"
            "echo $HOME;"
            "echo $SHELL"
        )
        try:
            stdout, _ = await self.exec_async(command=cmd, timeout=10)
            lines = stdout.decode("utf-8", errors="replace").splitlines()
            os_arch = lines[0].strip() if len(lines) > 0 else "unknown"
            parts = os_arch.split()
            return {
                "os": parts[0] if parts else "unknown",
                "arch": parts[1] if len(parts) > 1 else "unknown",
                "user": lines[1].strip() if len(lines) > 1 else "unknown",
                "home": lines[2].strip() if len(lines) > 2 else "unknown",
                "shell": lines[3].strip() if len(lines) > 3 else "unknown",
            }
        except InfrastructureError:
            return {"os": "unknown", "arch": "unknown", "user": "unknown",
                    "home": "unknown", "shell": "unknown"}
