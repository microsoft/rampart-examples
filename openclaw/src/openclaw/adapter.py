# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""OpenClaw adapter for RAMPART.

Implements the ``AgentAdapter`` and ``Session`` protocols by
communicating with an OpenClaw instance running inside a
network-isolated Docker Sandbox.

All interaction is routed through ``SandboxClient``, which pipes
data via stdin/stdout of ``docker sandbox exec``.  Prompts are
sent via the ``openclaw agent`` CLI, which connects to the
gateway over WebSocket internally.

Tool call observability comes from OpenClaw's session JSONL files,
which record every tool invocation (name, arguments) and its
result (output, exit code, duration).  After each agent turn,
the adapter reads new entries from the session log and extracts
``ToolCall`` objects.  This gives us ``TOOL_ONLY`` observability.

Security model:
  - The sandbox is untrusted.  Every response is validated.
  - API keys never enter the sandbox (auth proxy injects them
    on the host side).
  - The gateway token is sandbox-internal and never leaves it.
  - Prompt content travels only through stdin pipes, never as
    process arguments.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Self

from openclaw.sandbox import SandboxClient
from rampart.core.errors import InfrastructureError
from rampart.core.manifest import AppManifest, ToolDeclaration
from rampart.core.types import (
    ObservabilityLevel,
    Request,
    Response,
    ToolCall,
)

logger = logging.getLogger(__name__)

# Substrings that indicate the underlying model call failed even though
# OpenClaw still wraps the turn as ``status: ok`` (e.g. the auth-proxy
# bridge dropped the request, or the upstream provider returned a 5xx).
# When matched, ``Response.metadata[LLM_FAILURE_METADATA_KEY]`` is set so
# evaluators can score the turn as ``UNDETERMINED`` instead of treating an
# empty turn as a benign defended outcome.
LLM_FAILURE_METADATA_KEY = "llm_request_failed"
_LLM_FAILURE_MARKERS: tuple[str, ...] = (
    "LLM request failed",
    "network connection error",
)


def _detect_llm_failure(*, text: str) -> str | None:
    """Return the failure-marker substring if ``text`` looks like an
    in-band LLM error, else ``None``.
    """
    for marker in _LLM_FAILURE_MARKERS:
        if marker in text:
            return marker
    return None


def _index_tool_results(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index tool result entries by their toolCallId for pairing.

    Args:
        entries: Parsed JSONL entries from the session file.

    Returns:
        Mapping of toolCallId to the tool result message.
    """
    results_by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        msg = entry.get("message", {})
        if msg.get("role") == "toolResult":
            call_id = msg.get("toolCallId", "")
            if call_id:
                results_by_id[call_id] = msg
    return results_by_id


def _extract_result_text(result_msg: dict[str, Any]) -> str | None:
    """Extract concatenated text from a tool result message.

    Args:
        result_msg: A ``toolResult`` message dict.

    Returns:
        Joined text content, or ``None`` if no text parts found.
    """
    parts = [
        part.get("text", "")
        for part in result_msg.get("content", [])
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    return "\n".join(parts) if parts else None


def _extract_tool_calls_from_session_log(
    entries: list[dict[str, Any]],
) -> list[ToolCall]:
    """Extract tool calls from OpenClaw session JSONL entries.

    OpenClaw records each tool invocation as two entries:
      1. ``role: "assistant"`` with ``content: [{type: "toolCall", ...}]``
      2. ``role: "toolResult"`` with execution output and status

    We pair them by ``toolCallId`` to build complete ToolCall objects
    with both arguments and results.

    Args:
        entries: Parsed JSONL entries from the session file.

    Returns:
        List of ToolCall objects with names, arguments, and results.
    """
    results_by_id = _index_tool_results(entries)

    calls: list[ToolCall] = []
    for entry in entries:
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if not isinstance(block, dict) or block.get("type") != "toolCall":
                continue
            name = block.get("name", "")
            if not name:
                continue
            call_id = block.get("id", "")
            result_entry = results_by_id.get(call_id)
            result_text = _extract_result_text(result_entry) if result_entry else None
            args = block.get("arguments", {})
            calls.append(
                ToolCall(
                    name=name,
                    arguments=args if isinstance(args, dict) else {},
                    result=result_text,
                )
            )

    return calls


def _extract_text(raw: dict[str, Any]) -> str:
    """Extract the agent's text response.

    Args:
        raw: The full JSON response from ``openclaw agent --json``.

    Returns:
        The response text, or empty string if not found.
    """
    result = raw.get("result", {})
    payloads = result.get("payloads", [])
    parts = []
    for payload in payloads:
        text = payload.get("text", "")
        if text:
            parts.append(text)
    return "\n".join(parts)


class OpenClawSession:
    """A single interaction session with OpenClaw.

    Each session uses a unique session ID so that multi-turn
    conversations are isolated.  After each turn, the session
    reads the JSONL log from the sandbox to extract tool calls.

    Implements the RAMPART ``Session`` protocol.
    """

    # Gateway restarts are expected between trials (plugin install/
    # uninstall rewrites openclaw.json which triggers a file-watcher
    # restart).  Poll instead of failing on the first miss.
    _HEALTH_POLL_ATTEMPTS: int = 15
    _HEALTH_POLL_INTERVAL: float = 2.0

    def __init__(
        self,
        *,
        client: SandboxClient,
        session_id: str | None = None,
    ) -> None:
        self._client = client
        self._session_id = session_id or uuid.uuid4().hex[:16]
        self._openclaw_session_id: str | None = None
        self._log_lines_seen: int = 0
        self._sandbox_metadata: dict[str, Any] = {}

    async def send_async(self, request: Request) -> Response:
        """Send a prompt to OpenClaw and return its response.

        After the agent responds, reads the session JSONL to extract
        tool calls that occurred during this turn.

        Args:
            request: The prompt to send.

        Returns:
            Response with text and tool calls from this turn.

        Raises:
            InfrastructureError: On communication or parsing failures.
        """
        if not request.prompt:
            msg = "OpenClaw requires a text prompt."
            raise InfrastructureError(msg)

        raw = await self._client.send_async(
            prompt=request.prompt,
            session_id=self._session_id,
        )

        self._validate_agent_status(raw=raw)
        text = _extract_text(raw)

        meta = raw.get("result", {}).get("meta", {})
        agent_meta = meta.get("agentMeta", {})

        if not self._openclaw_session_id:
            self._openclaw_session_id = agent_meta.get("sessionId", "")

        tool_calls = await self._read_new_tool_calls_async()

        response_metadata = self._build_response_metadata(
            raw=raw,
            agent_meta=agent_meta,
            meta=meta,
            tool_calls=tool_calls,
        )
        llm_failure = _detect_llm_failure(text=text)
        if llm_failure is not None:
            logger.warning(
                "OpenClaw response indicates upstream LLM failure (%r); "
                "flagging turn as infra-failure for evaluator.",
                llm_failure,
            )
            response_metadata[LLM_FAILURE_METADATA_KEY] = llm_failure

        return Response(
            text=text,
            tool_calls=tool_calls,
            metadata=response_metadata,
        )

    @staticmethod
    def _validate_agent_status(*, raw: dict[str, Any]) -> None:
        """Raise if the agent response indicates a non-ok status.

        Args:
            raw: The full JSON response from the agent.

        Raises:
            InfrastructureError: If status is not ``"ok"``.
        """
        status = raw.get("status", "")
        if status != "ok":
            summary = raw.get("summary", "unknown error")
            msg = f"OpenClaw agent returned status '{status}': {summary}"
            raise InfrastructureError(msg)

    async def _read_new_tool_calls_async(self) -> list[ToolCall]:
        """Read new tool calls from the session JSONL log.

        Returns:
            Tool calls extracted from entries added since the last read.
        """
        if not self._openclaw_session_id:
            return []

        new_entries = await self._client.read_session_log_async(
            session_id=self._openclaw_session_id,
            after_line=self._log_lines_seen,
        )
        tool_calls = _extract_tool_calls_from_session_log(new_entries)
        self._log_lines_seen += len(new_entries)
        return tool_calls

    def _build_response_metadata(
        self,
        *,
        raw: dict[str, Any],
        agent_meta: dict[str, Any],
        meta: dict[str, Any],
        tool_calls: list[ToolCall],
    ) -> dict[str, Any]:
        """Build the metadata dict for a Response.

        Args:
            raw: The full JSON response from the agent.
            agent_meta: Agent-specific metadata from the response.
            meta: Top-level metadata from the response.
            tool_calls: Tool calls extracted for this turn.

        Returns:
            Metadata dict to attach to the Response.
        """
        return {
            "run_id": raw.get("runId", ""),
            "model": agent_meta.get("model", ""),
            "provider": agent_meta.get("provider", ""),
            "duration_ms": meta.get("durationMs", 0),
            "usage": agent_meta.get("lastCallUsage", {}),
            "openclaw_session_id": self._openclaw_session_id,
            "tool_call_sequence": [tc.name for tc in tool_calls],
            **self._sandbox_metadata,
        }

    async def __aenter__(self) -> Self:
        """Enter the session — wait for the gateway and collect sandbox metadata."""
        for _ in range(self._HEALTH_POLL_ATTEMPTS):
            if await self._client.health_check_async():
                break
            await asyncio.sleep(self._HEALTH_POLL_INTERVAL)
        else:
            msg = "OpenClaw gateway is not reachable inside the sandbox. Is the sandbox running?"
            raise InfrastructureError(msg)

        # Gather sandbox metadata once per session for report enrichment.
        self._sandbox_metadata = await self._collect_sandbox_metadata_async()

        logger.info("OpenClaw session started (session_id=%s).", self._session_id)
        return self

    async def _collect_sandbox_metadata_async(self) -> dict[str, Any]:
        """Collect environment metadata from the sandbox.

        Runs once on session entry to capture:
          - OpenClaw + Node.js versions
          - Sandbox environment (OS, arch, user)
          - Installed plugins (attack surface)
          - Bootstrap files present
          - Workspace file listing
          - Network policy

        Returns:
            Metadata dict to merge into every response.
        """
        (
            openclaw_version,
            node_version,
            plugins,
            bootstrap_files,
            workspace_files,
            network_policy,
            sandbox_env,
        ) = await asyncio.gather(
            self._client.get_openclaw_version_async(),
            self._client.get_node_version_async(),
            self._client.get_installed_plugins_async(),
            self._client.get_bootstrap_files_async(),
            self._client.get_workspace_tree_async(),
            self._client.get_network_policy_async(),
            self._client.get_sandbox_environment_async(),
        )
        return {
            "openclaw_version": openclaw_version,
            "node_version": node_version,
            "sandbox_environment": sandbox_env,
            "network_policy": network_policy,
            "installed_plugins": plugins,
            "bootstrap_files": bootstrap_files,
            "workspace_files": workspace_files,
        }

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit the session."""
        logger.info(
            "OpenClaw session closed (session_id=%s, openclaw_session_id=%s, lines_seen=%d).",
            self._session_id,
            self._openclaw_session_id,
            self._log_lines_seen,
        )


class OpenClawAdapter:
    """Factory for OpenClaw sessions and source of agent metadata.

    Communicates with an OpenClaw instance inside a Docker Sandbox
    via ``SandboxClient``.

    Args:
        sandbox_name: Name of the Docker Sandbox running OpenClaw.
        manifest: Agent capability declaration.  Defaults to the
            standard OpenClaw coding-agent tools.
        timeout: Request timeout in seconds.
    """

    DEFAULT_MANIFEST: AppManifest = AppManifest(
        name="OpenClaw",
        description="Agentic coding assistant running in a sandboxed environment.",
        tools=[
            ToolDeclaration(
                name="exec",
                description="Execute a shell command.",
                parameters={"command": {"type": "string"}},
            ),
            ToolDeclaration(
                name="read",
                description="Read a file from the filesystem.",
                parameters={"path": {"type": "string"}},
            ),
            ToolDeclaration(
                name="write",
                description="Write content to a file.",
                parameters={"path": {"type": "string"}, "content": {"type": "string"}},
            ),
            ToolDeclaration(
                name="edit",
                description="Apply edits to an existing file.",
                parameters={"path": {"type": "string"}},
            ),
            ToolDeclaration(
                name="apply_patch",
                description="Apply a unified diff patch.",
                parameters={"patch": {"type": "string"}},
            ),
        ],
    )

    def __init__(
        self,
        *,
        sandbox_name: str = "openclaw",
        manifest: AppManifest | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._client = SandboxClient(sandbox_name=sandbox_name, timeout=timeout)
        self._manifest = manifest or self.DEFAULT_MANIFEST

    async def create_session_async(self) -> OpenClawSession:
        """Create a fresh session with independent conversation state.

        Returns:
            A new ``OpenClawSession`` ready for interaction.
        """
        return OpenClawSession(client=self._client)

    @property
    def manifest(self) -> AppManifest:
        """The agent's declared capabilities."""
        return self._manifest

    @property
    def sandbox_client(self) -> SandboxClient:
        """The underlying ``SandboxClient`` for this adapter.

        Exposed so callers (e.g. injection surfaces) can route their
        own sandbox commands through the same audited boundary as the
        adapter itself.
        """
        return self._client

    @property
    def observability_profile(self) -> ObservabilityLevel:
        """What this adapter can reliably observe.

        TOOL_ONLY: we see tool call names, arguments, and results
        from the session JSONL file, but cannot observe host-level
        side effects (e.g., partial file writes that failed) from
        outside the sandbox.
        """
        return ObservabilityLevel.TOOL_ONLY
