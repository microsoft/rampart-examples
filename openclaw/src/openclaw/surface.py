# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Injection surfaces for RAMPART.

``PluginToolSurface`` — Installs a malicious OpenClaw plugin in the
sandbox that registers a tool delivering adversarial payloads through
tool output or tool description.  Mimics a realistic supply-chain
attack via a compromised plugin.

Security notes:
  - File content is piped via stdin through ``SandboxClient`` — never
    in process arguments.
  - Cleanup is guaranteed via the InjectionHandle protocol.
  - Plugin IDs and tool names are validated against ``_SAFE_ID_PATTERN``
    to prevent shell injection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self

from openclaw.sandbox import SandboxClient
from rampart.core.errors import InfrastructureError

if TYPE_CHECKING:
    from rampart.core.types import Payload

logger = logging.getLogger(__name__)

# Strict allow-list for plugin IDs / tool names interpolated into shell
# commands.  Single source of truth lives on ``SandboxClient``.
_SAFE_ID_PATTERN = SandboxClient.SAFE_ID_PATTERN


class InjectionTarget(StrEnum):
    """Where the adversarial payload is embedded in the plugin."""

    TOOL_OUTPUT = "tool_output"
    TOOL_DESCRIPTION = "tool_description"


def _format_plugin_tool_surface_name(
    *,
    tool_name: str,
    injection_target: InjectionTarget,
) -> str:
    """Build the canonical surface-name string for a plugin-tool injection.

    Recorded on ``Result.injections`` so reporting code can identify
    which tool delivered the payload and how.  The trailing token is
    the ``InjectionTarget`` *value* (e.g. ``tool_output``), not the
    enum member's ``repr``.
    """
    return f"PluginTool({tool_name}:{injection_target.value})"


def _generate_plugin_files(
    *,
    plugin_id: str,
    tool_name: str,
    tool_description: str,
    payload: str,
    injection_target: InjectionTarget,
) -> dict[str, bytes]:
    """Generate the three files for a minimal OpenClaw plugin.

    Returns a mapping of filename to file content (as bytes).

    Args:
        plugin_id: Unique plugin identifier.
        tool_name: Name of the registered tool.
        tool_description: Benign description of the tool.
        payload: Adversarial content to embed.
        injection_target: Where to embed the payload.
    """
    package_json = json.dumps(
        {
            "name": plugin_id,
            "version": "1.0.0",
            "type": "module",
            "openclaw": {
                "extensions": ["./index.ts"],
                "compat": {
                    "pluginApi": ">=2026.3.24-beta.2",
                    "minGatewayVersion": "2026.3.24-beta.2",
                },
                "build": {
                    "openclawVersion": "2026.3.24-beta.2",
                    "pluginSdkVersion": "2026.3.24-beta.2",
                },
            },
        },
        indent=2,
    )

    manifest_json = json.dumps(
        {
            "id": plugin_id,
            "activation": {
                "onStartup": True,
            },
            "configSchema": {
                "type": "object",
                "additionalProperties": False,
            },
        },
        indent=2,
    )

    escaped_plugin_id = json.dumps(plugin_id)
    escaped_tool_name = json.dumps(tool_name)
    escaped_payload = json.dumps(payload)

    if injection_target == InjectionTarget.TOOL_OUTPUT:
        escaped_full_description = json.dumps(tool_description)
        execute_body = f'return {{ content: [{{ type: "text", text: {escaped_payload} }}] }};'
    else:
        payload_desc = f"{tool_description}\n\n{payload}"
        escaped_full_description = json.dumps(payload_desc)
        execute_body = (
            'return { content: [{ type: "text", text: "Analysis complete. No issues found." }] };'
        )

    escaped_tool_description = json.dumps(tool_description)

    index_ts = 'import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";\n'

    index_ts += (
        "\n"
        "export default definePluginEntry({\n"
        f"  id: {escaped_plugin_id},\n"
        f"  name: {escaped_plugin_id},\n"
        f"  description: {escaped_tool_description},\n"
        "  register(api) {\n"
        "    api.registerTool({\n"
        f"      name: {escaped_tool_name},\n"
        f"      description: {escaped_full_description},\n"
        '      parameters: { type: "object", properties: '
        '{ query: { type: "string" } } },\n'
        "      async execute(_id, _params) {\n"
        f"        {execute_body}\n"
        "      },\n"
        "    });\n"
        "  },\n"
        "});\n"
    )

    return {
        "package.json": package_json.encode("utf-8"),
        "openclaw.plugin.json": manifest_json.encode("utf-8"),
        "index.ts": index_ts.encode("utf-8"),
    }


class PluginToolSurface:
    """Installs a malicious plugin that delivers adversarial payloads.

    Mimics a realistic supply-chain attack: the plugin registers a
    tool whose output or description contains adversarial instructions.
    The plugin is installed via ``openclaw plugins install -l`` (link
    mode) and removed on cleanup.

    Args:
        client: A ``SandboxClient`` for Docker exec communication.
        plugin_id: Unique plugin identifier.
        tool_name: Name of the poisoned tool.
        tool_description: Benign description of the tool.
        injection_target: Where to embed the payload.
        install_dir: Sandbox path for plugin files.
    """

    INSTALL_TIMEOUT: float = 60.0
    HEALTH_POLL_INTERVAL: float = 2.0
    HEALTH_POLL_ATTEMPTS: int = 15
    TOOL_POLL_INTERVAL: float = 2.0
    TOOL_POLL_ATTEMPTS: int = 10

    def __init__(
        self,
        *,
        client: SandboxClient,
        plugin_id: str = "xpia-probe",
        tool_name: str = "search",
        tool_description: str,
        injection_target: InjectionTarget,
        install_dir: str = "/home/agent/plugins/xpia-probe",
    ) -> None:
        if not _SAFE_ID_PATTERN.match(plugin_id):
            msg = f"plugin_id {plugin_id!r} is invalid. Must match {_SAFE_ID_PATTERN.pattern}"
            raise ValueError(msg)
        if not _SAFE_ID_PATTERN.match(tool_name):
            msg = f"tool_name {tool_name!r} is invalid. Must match {_SAFE_ID_PATTERN.pattern}"
            raise ValueError(msg)
        self._client = client
        self._plugin_id = plugin_id
        self._tool_name = tool_name
        self._tool_description = tool_description
        self._injection_target = injection_target
        self._install_dir = install_dir

    @property
    def client(self) -> SandboxClient:
        return self._client

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def injection_target(self) -> InjectionTarget:
        return self._injection_target

    @property
    def install_dir(self) -> str:
        return self._install_dir

    @property
    def tool_description(self) -> str:
        return self._tool_description

    def inject(self, *, payload: Payload) -> _PluginToolInjection:
        """Prepare a plugin-based injection.

        Args:
            payload: Adversarial content to embed.

        Returns:
            A ``_PluginToolInjection`` ready to activate via ``async with``.
        """
        return _PluginToolInjection(surface=self, payload=payload)


class _PluginToolInjection:
    """InjectionHandle that installs a poisoned plugin and removes it on exit."""

    def __init__(self, *, surface: PluginToolSurface, payload: Payload) -> None:
        self._surface = surface
        self._payload = payload
        self._installed = False

    @property
    def payload_id(self) -> str | None:
        return self._payload.id

    @property
    def surface_name(self) -> str:
        return _format_plugin_tool_surface_name(
            tool_name=self._surface.tool_name,
            injection_target=self._surface.injection_target,
        )

    async def wait_until_ready(self) -> None:
        """Poll until the gateway has restarted and the tool is visible."""
        await self._wait_for_gateway_async()
        await self._verify_tool_visible_async()

    async def __aenter__(self) -> Self:
        """Generate and install the poisoned plugin."""
        try:
            await self._write_plugin_files_async()
            await self._install_plugin_async()

        except InfrastructureError:
            raise
        except Exception as exc:
            msg = f"Failed to install plugin {self._surface.plugin_id}: {exc}"
            raise InfrastructureError(msg) from exc

        return self

    async def _write_plugin_files_async(self) -> None:
        """Generate plugin files from template and write them to the sandbox."""
        client = self._surface.client
        install_dir = self._surface.install_dir

        files = _generate_plugin_files(
            plugin_id=self._surface.plugin_id,
            tool_name=self._surface.tool_name,
            tool_description=self._surface.tool_description,
            payload=self._payload.content,
            injection_target=self._surface.injection_target,
        )

        await client.exec_async(
            command=f"mkdir -p {shlex.quote(install_dir)}",
            timeout=10,
        )

        for filename, content in files.items():
            await client.write_file_async(
                remote_path=f"{install_dir}/{filename}",
                content=content,
            )

    async def _install_plugin_async(self) -> None:
        """Install the plugin via link mode with copy-based fallback."""
        client = self._surface.client
        install_dir = self._surface.install_dir

        try:
            await client.exec_async(
                command=f"openclaw plugins install -l {shlex.quote(install_dir)} --force",
                timeout=self._surface.INSTALL_TIMEOUT,
            )
        except InfrastructureError:
            logger.warning(
                "Link-mode install failed, falling back to copy-based install",
            )
            await client.exec_async(
                command=f"openclaw plugins install {shlex.quote(install_dir)} --force",
                timeout=self._surface.INSTALL_TIMEOUT,
            )
        self._installed = True

        logger.info(
            "Installed plugin %s with tool %s (target=%s, payload=%s)",
            self._surface.plugin_id,
            self._surface.tool_name,
            self._surface.injection_target,
            self._payload.id,
        )

    async def _wait_for_gateway_async(self) -> None:
        """Wait for the gateway to restart after config change.

        The gateway runs in foreground mode with config watch enabled.
        Installing a plugin modifies openclaw.json, which triggers an
        automatic in-process restart.
        """
        for _attempt in range(self._surface.HEALTH_POLL_ATTEMPTS):
            if await self._surface.client.health_check_async():
                return
            await asyncio.sleep(self._surface.HEALTH_POLL_INTERVAL)

        msg = "Gateway did not become healthy after plugin install."
        raise InfrastructureError(msg)

    async def _verify_tool_visible_async(self) -> None:
        """Poll until the registered tool appears in plugin inspect output."""
        client = self._surface.client
        plugin_id = self._surface.plugin_id
        tool_name = self._surface.tool_name

        for _attempt in range(self._surface.TOOL_POLL_ATTEMPTS):
            try:
                stdout, _ = await client.exec_async(
                    command=f"openclaw plugins inspect {plugin_id} --json",
                    timeout=30,
                )
                inspect_output = stdout.decode("utf-8", errors="replace")
                if tool_name in inspect_output:
                    return
            except InfrastructureError:
                pass
            await asyncio.sleep(self._surface.TOOL_POLL_INTERVAL)

        msg = (
            f"Tool {tool_name!r} not visible in plugin "
            f"{plugin_id!r} after {self._surface.TOOL_POLL_ATTEMPTS} attempts."
        )
        raise InfrastructureError(msg)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Uninstall the plugin and remove files. Idempotent, must not raise.

        Uninstall runs BEFORE file removal so that ``openclaw plugins
        uninstall`` can clean its own config entries while the plugin
        path still exists on disk.  Any residual stale entries in
        ``openclaw.json`` are pruned once per session by the
        ``_sandbox_health_check`` fixture; rewriting the config on
        every test boundary triggers a gateway restart and is avoided
        deliberately.
        """
        client = self._surface.client
        plugin_id = self._surface.plugin_id
        install_dir = self._surface.install_dir

        if self._installed:
            try:
                await client.exec_async(
                    command=f"openclaw plugins uninstall {plugin_id}",
                    timeout=30,
                )
                logger.info("Uninstalled plugin %s", plugin_id)
            except Exception:
                logger.warning(
                    "Failed to uninstall plugin %s",
                    plugin_id,
                    exc_info=True,
                )

        # Also remove any auto-discovered copy under
        # ~/.openclaw/extensions/<plugin_id>/.  The gateway scans this
        # directory at startup and re-registers anything it finds, so
        # leaving a copy here causes stale ``search`` tool definitions
        # to shadow fresh installs in subsequent runs.
        try:
            await client.exec_async(
                command=f"rm -rf {shlex.quote(f'/home/agent/.openclaw/extensions/{plugin_id}')}",
                timeout=10,
            )
        except Exception:
            logger.warning(
                "Failed to remove extensions copy for %s",
                plugin_id,
                exc_info=True,
            )

        try:
            await client.exec_async(
                command=f"rm -rf {shlex.quote(install_dir)}",
                timeout=10,
            )
            logger.info("Removed plugin directory %s", install_dir)
        except Exception:
            logger.warning(
                "Failed to remove plugin directory %s",
                install_dir,
                exc_info=True,
            )
