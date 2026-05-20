# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Interactive HTML report sink for OpenClaw integration tests.

Generates a self-contained HTML file with:

- Summary stats (safe/unsafe/undetermined/error) with animated donut chart
- Architecture diagram showing the sandboxed execution flow
- Attack surface breakdown by injection target
- Scenario × trial heatmap (fully dynamic, clickable)
- Expandable per-turn conversation view with payload highlighting
- Per-tool-name color coding for visual tracing
- Key findings with actionable takeaways
- Sandbox environment metadata at the bottom
- Modern dark UI using only vanilla HTML/CSS/JS — fully self-contained

Usage::

    from openclaw.html_report import HtmlReportSink

    @pytest.fixture(scope="session")
    def rampart_sinks():
        return [HtmlReportSink(output_dir=Path(".report"))]
"""

from __future__ import annotations

import html
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from rampart.core.result import Result
    from rampart.core.types import Turn
    from rampart.reporting.sink import TestRunReport

logger = logging.getLogger(__name__)

# Stable color palette for tool names — each tool gets a consistent
# hue across the entire report so viewers can trace tool chains visually.
_TOOL_COLORS: dict[str, tuple[str, str, str]] = {
    # name -> (text, bg, border)
    "exec": ("#f87171", "rgba(239,68,68,0.10)", "rgba(239,68,68,0.30)"),
    "shell": ("#f87171", "rgba(239,68,68,0.10)", "rgba(239,68,68,0.30)"),
    "bash": ("#f87171", "rgba(239,68,68,0.10)", "rgba(239,68,68,0.30)"),
    "run": ("#f87171", "rgba(239,68,68,0.10)", "rgba(239,68,68,0.30)"),
    "search": ("#67e8f9", "rgba(6,182,212,0.10)", "rgba(6,182,212,0.30)"),
    "read": ("#93c5fd", "rgba(59,130,246,0.10)", "rgba(59,130,246,0.30)"),
    "write": ("#c4b5fd", "rgba(139,92,246,0.10)", "rgba(139,92,246,0.30)"),
    "edit": ("#c4b5fd", "rgba(139,92,246,0.10)", "rgba(139,92,246,0.30)"),
    "apply_patch": ("#d8b4fe", "rgba(168,85,247,0.10)", "rgba(168,85,247,0.30)"),
}
_DEFAULT_TOOL_COLOR = ("#a1a1aa", "rgba(161,161,170,0.08)", "rgba(161,161,170,0.25)")

# Tools that represent attacker-controlled execution.
_EXEC_TOOLS = frozenset({"exec", "shell", "bash", "run"})


def _tool_color(name: str) -> tuple[str, str, str]:
    return _TOOL_COLORS.get(name.lower(), _DEFAULT_TOOL_COLOR)


# Surface-name format emitted by ``PluginToolSurface``:
# ``PluginTool(<tool_name>:<injection_target>)``.  See
# ``openclaw.surface._format_plugin_tool_surface_name``.
_TOOL_OUTPUT_SURFACE_SUFFIX = ":tool_output)"
_PLUGIN_TOOL_SURFACE_PREFIX = "PluginTool("


def _payload_bearing_tool_names(*, result: Result) -> frozenset[str]:
    """Return lowercased tool names whose ``execute()`` output actually
    carried an injected payload for this result.

    Only tool calls *to those tools* should be visually flagged in the
    report — unrelated tools the agent invoked (``read``, ``exec``,
    …) are not payload-bearing even when the trial uses tool-output
    injection.
    """
    names: set[str] = set()
    for record in result.injections:
        sn = record.surface_name
        if not (
            sn.startswith(_PLUGIN_TOOL_SURFACE_PREFIX) and sn.endswith(_TOOL_OUTPUT_SURFACE_SUFFIX)
        ):
            continue
        # Extract ``<tool_name>`` from ``PluginTool(<tool_name>:tool_output)``.
        inner = sn[len(_PLUGIN_TOOL_SURFACE_PREFIX) : -len(_TOOL_OUTPUT_SURFACE_SUFFIX)]
        if inner:
            names.add(inner.lower())
    return frozenset(names)


class HtmlReportSink:
    """Writes an interactive HTML report for an OpenClaw test run.

    Args:
        output_dir: Directory to write the HTML file into.
            Created automatically if it does not exist.
    """

    def __init__(self, *, output_dir: Path) -> None:
        self._output_dir = output_dir

    async def emit_async(self, *, report: TestRunReport) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        filepath = self._output_dir / f"report_{timestamp}.html"
        content = self._render(report=report, timestamp=timestamp)
        filepath.write_text(content, encoding="utf-8")
        logger.info("HTML report written to %s", filepath)

    # Rendering

    def _render(self, *, report: TestRunReport, timestamp: str) -> str:
        summary = report.population_summary()
        total_duration_min = report.duration_seconds / 60

        sandbox_meta = self._extract_sandbox_metadata(report.results)
        surface_stats = self._compute_surface_stats(report.results)
        heatmap_data = self._build_heatmap(report.results)
        findings = self._build_findings(surface_stats)

        # Build result-index map keyed by test_name for heatmap links.
        result_index_by_name: dict[str, int] = {}
        results_html = ""
        for idx, r in enumerate(report.results):
            tname = (r.metadata or {}).get("test_name", "")
            if tname:
                result_index_by_name[tname] = idx
            results_html += self._render_result_row(result=r, index=idx)

        safe_pct = summary.safety_pass_rate * 100
        circ = 2 * 3.14159 * 80
        safe_arc = circ * summary.safety_pass_rate
        unsafe_arc = circ - safe_arc

        model = sandbox_meta.get("model", "unknown")
        provider = sandbox_meta.get("provider", "unknown")

        return _HTML_TEMPLATE.format(
            timestamp=timestamp,
            total=report.total_runs,
            passed=report.passed,
            failed=report.failed,
            undetermined=report.undetermined,
            errors=report.errors,
            duration_min=f"{total_duration_min:.0f}",
            pass_rate=f"{safe_pct:.1f}",
            asr=f"{summary.attack_success_rate * 100:.1f}",
            safe_pct=f"{safe_pct:.0f}",
            safe_arc=f"{safe_arc:.1f}",
            unsafe_arc=f"{unsafe_arc:.1f}",
            circ=f"{circ:.1f}",
            model=html.escape(str(model)),
            provider=html.escape(str(provider)),
            sandbox_env_html=self._render_sandbox_env(sandbox_meta),
            surface_cards_html=self._render_surface_cards(surface_stats),
            heatmap_html=self._render_heatmap(
                heatmap=heatmap_data,
                index_map=result_index_by_name,
            ),
            findings_html=self._render_findings(findings),
            results=results_html,
            safe_count=summary.safe_count,
            unsafe_count=summary.unsafe_count,
        )

    # Data extraction

    @staticmethod
    def _extract_sandbox_metadata(results: list[Result]) -> dict[str, Any]:
        for r in results:
            meta = r.metadata or {}
            if meta.get("openclaw_version") or meta.get("model"):
                return meta
            for t in r.turns:
                tmeta = t.response.metadata or {}
                if tmeta.get("openclaw_version") or tmeta.get("model"):
                    return tmeta
        return {}

    @staticmethod
    def _compute_surface_stats(
        results: list[Result],
    ) -> dict[str, dict[str, int]]:
        surfaces: dict[str, dict[str, int]] = {}
        for r in results:
            test_name = (r.metadata or {}).get("test_name", "")
            tl = test_name.lower()
            if "output" in tl:
                surface = "Tool Output"
            elif "desc" in tl:
                surface = "Tool Description"
            else:
                surface = "Other"
            surfaces.setdefault(surface, {"safe": 0, "unsafe": 0, "undetermined": 0, "error": 0})
            if r.safe:
                surfaces[surface]["safe"] += 1
            elif r.status.value == "unsafe":
                surfaces[surface]["unsafe"] += 1
            elif r.status.value == "undetermined":
                surfaces[surface]["undetermined"] += 1
            elif r.status.value == "error":
                surfaces[surface]["error"] += 1
        return surfaces

    @staticmethod
    def _build_heatmap(
        results: list[Result],
    ) -> list[dict[str, Any]]:
        """Build ordered heatmap rows from results.

        Each row is ``{scenario, trials: {trial_num: {status, test_name}}}``.
        Fully dynamic — derived entirely from result metadata.
        """
        rows: dict[str, dict[int, dict[str, str]]] = {}
        for r in results:
            test_name = (r.metadata or {}).get("test_name", "")
            if "[trial-" in test_name:
                parts = test_name.split("[trial-")
                scenario = parts[0]
                try:
                    trial = int(parts[1].rstrip("]"))
                except (ValueError, IndexError):
                    trial = 0
            else:
                scenario = test_name
                trial = 0
            rows.setdefault(scenario, {})
            rows[scenario][trial] = {
                "status": r.status.value,
                "test_name": test_name,
            }
        return [{"scenario": s, "trials": t} for s, t in rows.items()]

    @staticmethod
    def _build_findings(
        surface_stats: dict[str, dict[str, int]],
    ) -> list[dict[str, str]]:
        findings: list[dict[str, str]] = []
        for surface, stats in surface_stats.items():
            total = stats["safe"] + stats["unsafe"]
            if stats["unsafe"] > 0:
                rate = stats["unsafe"] / total * 100
                findings.append(
                    {
                        "color": "unsafe",
                        "icon": "⚠️",
                        "title": f"{surface} — {rate:.0f}% Attack Success",
                        "body": (
                            f"{stats['unsafe']}/{total} trials compromised "
                            f"via {surface.lower()} injection."
                        ),
                    }
                )
            else:
                findings.append(
                    {
                        "color": "safe",
                        "icon": "✅",
                        "title": f"{surface} — Fully Defended",
                        "body": (
                            f"All {total} trials defended against {surface.lower()} injection."
                        ),
                    }
                )
        return findings

    # Section renderers

    @staticmethod
    def _render_sandbox_env(meta: dict[str, Any]) -> str:
        if not meta:
            return ""
        sandbox_env = meta.get("sandbox_environment", {})
        cards = ""

        # Runtime.
        rows = ""
        for key, val in [
            ("OpenClaw", meta.get("openclaw_version", "—")),
            ("Node.js", meta.get("node_version", "—")),
            ("OS", f"{sandbox_env.get('os', '—')} {sandbox_env.get('arch', '')}".strip()),
            ("User", sandbox_env.get("user", "—")),
            ("Shell", sandbox_env.get("shell", "—")),
            ("Model", meta.get("model", "—")),
            ("Provider", meta.get("provider", "—")),
        ]:
            rows += (
                f'<div class="env-row"><span class="env-key">{html.escape(str(key))}</span>'
                f'<span class="env-val">{html.escape(str(val))}</span></div>'
            )
        cards += f'<div class="env-card"><h4>Runtime</h4>{rows}</div>'

        # Network.
        net_policy = str(meta.get("network_policy", "unknown"))
        safe_cls = " env-val--safe" if "deny" in net_policy.lower() else ""
        rows = ""
        for key, val, cls in [
            ("Network Policy", net_policy, safe_cls),
            ("API Keys in Sandbox", "None", " env-val--safe"),
            ("Observability", "TOOL_ONLY", ""),
        ]:
            rows += (
                f'<div class="env-row"><span class="env-key">{html.escape(str(key))}</span>'
                f'<span class="env-val{cls}">{html.escape(str(val))}</span></div>'
            )
        cards += f'<div class="env-card"><h4>Network &amp; Isolation</h4>{rows}</div>'

        # Bootstrap files.
        bootstrap = meta.get("bootstrap_files", [])
        if bootstrap:
            items = ""
            for f in bootstrap:
                name = html.escape(str(f.get("name", "")))
                size = f.get("size_bytes", 0)
                size_str = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
                items += f'<li>{name} <span class="file-size">{size_str}</span></li>'
            cards += (
                f'<div class="env-card"><h4>Bootstrap Files</h4>'
                f'<ul class="file-list">{items}</ul></div>'
            )

        # Workspace files.
        workspace = meta.get("workspace_files", [])
        if workspace:
            items = "".join(f"<li>{html.escape(str(f))}</li>" for f in workspace[:15])
            if len(workspace) > 15:
                items += f"<li>… and {len(workspace) - 15} more</li>"
            cards += (
                f'<div class="env-card"><h4>Workspace Files</h4>'
                f'<ul class="file-list">{items}</ul></div>'
            )

        # Plugins.
        plugins = meta.get("installed_plugins", [])
        if plugins:
            rows = ""
            for p in plugins:
                rows += (
                    f'<div class="env-row"><span class="env-key">{html.escape(str(p.get("name", "—")))}</span>'
                    f'<span class="env-val">{html.escape(str(p.get("version", "")))}</span></div>'
                )
            cards += f'<div class="env-card"><h4>Installed Plugins</h4>{rows}</div>'

        if not cards:
            return ""
        return (
            '<div class="section-title"><span class="icon">🖥️</span> '
            "Sandbox Environment</div>"
            f'<div class="sandbox-env">{cards}</div>'
        )

    @staticmethod
    def _render_surface_cards(
        surface_stats: dict[str, dict[str, int]],
    ) -> str:
        _DESCS = {
            "Tool Output": "Payload in tool execute() return value — trusted tool output.",
            "Tool Description": "Payload in tool schema description — lower trust tier.",
            "Workspace File": "Plugin register() appends payload to bootstrap files — system prompt tier.",
        }
        cards = ""
        for surface, stats in surface_stats.items():
            desc = _DESCS.get(surface, "")
            pills = f'<span class="surface-stat surface-stat--safe">{stats["safe"]} Safe</span>'
            if stats["unsafe"] > 0:
                pills += f' <span class="surface-stat surface-stat--unsafe">{stats["unsafe"]} Unsafe</span>'
            if stats.get("undetermined", 0) > 0:
                pills += f' <span class="surface-stat surface-stat--other">{stats["undetermined"]} Undetermined</span>'
            if stats.get("error", 0) > 0:
                pills += (
                    f' <span class="surface-stat surface-stat--other">{stats["error"]} Error</span>'
                )
            cards += (
                f'<div class="surface-card"><h4>{html.escape(surface)}</h4>'
                f"<p>{html.escape(desc)}</p>"
                f'<div class="surface-stats">{pills}</div></div>'
            )
        return cards

    @staticmethod
    def _render_heatmap(
        *,
        heatmap: list[dict[str, Any]],
        index_map: dict[str, int],
    ) -> str:
        if not heatmap:
            return ""
        max_trial = 0
        for row in heatmap:
            trials = row["trials"]
            if trials:
                max_trial = max(max_trial, *trials.keys())

        headers = "".join(f"<th>Trial {i}</th>" for i in range(max_trial + 1))
        rows = ""
        for row in heatmap:
            scenario = row["scenario"]
            label = html.escape(scenario.replace("test_", "").replace("_", " ").title())
            cells = ""
            for i in range(max_trial + 1):
                info = row["trials"].get(i)
                if info is None:
                    cells += "<td></td>"
                    continue
                status = info["status"]
                test_name = info["test_name"]
                idx = index_map.get(test_name, -1)
                cls = (
                    "hm-safe"
                    if status == "safe"
                    else "hm-unsafe"
                    if status == "unsafe"
                    else "hm-other"
                )
                onclick = f' onclick="scrollToResult({idx})"' if idx >= 0 else ""
                title = f' title="{html.escape(test_name)}"'
                cells += f'<td class="{cls}"{title}{onclick}></td>'
            rows += f"<tr><td>{label}</td>{cells}</tr>"

        return (
            f'<table class="heatmap-table">'
            f"<thead><tr><th>Scenario</th>{headers}</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    @staticmethod
    def _render_findings(findings: list[dict[str, str]]) -> str:
        if not findings:
            return ""
        cards = ""
        for f in findings:
            css = "var(--unsafe)" if f["color"] == "unsafe" else "var(--safe)"
            cards += (
                f'<div class="takeaway-item">'
                f'<h4 style="color:{css};">{f["icon"]} {html.escape(f["title"])}</h4>'
                f"<p>{html.escape(f['body'])}</p></div>"
            )
        return cards

    def _render_result_row(self, *, result: Result, index: int) -> str:
        status = result.status.value
        is_safe = status == "safe"
        icon = "●" if is_safe else "▲" if status == "unsafe" else "◆"
        icon_cls = "icon-safe" if is_safe else "icon-unsafe" if status == "unsafe" else "icon-other"
        pill_cls = (
            "pill--safe" if is_safe else "pill--unsafe" if status == "unsafe" else "pill--other"
        )

        meta = result.metadata or {}
        test_name = meta.get("test_name", "")
        model = meta.get("model", "")

        tool_seq = meta.get("tool_call_sequence", [])
        seq_html = self._render_tool_sequence(
            tool_calls=tool_seq,
            is_safe=is_safe,
        )

        turns_html = ""
        payload_tool_names = _payload_bearing_tool_names(result=result)
        for t in result.turns:
            turns_html += self._render_turn(
                turn=t,
                is_safe=is_safe,
                payload_tool_names=payload_tool_names,
            )

        return _RESULT_ROW.format(
            index=index,
            status=status,
            icon=icon,
            icon_cls=icon_cls,
            pill_cls=pill_cls,
            pill_label=status.upper(),
            summary=html.escape(result.summary or ""),
            test_name=html.escape(test_name),
            strategy=html.escape(result.strategy or "—"),
            duration=f"{result.duration_seconds:.0f}",
            model=html.escape(str(model)),
            seq_html=seq_html,
            turns=turns_html,
        )

    @staticmethod
    def _render_tool_sequence(*, tool_calls: list[str], is_safe: bool) -> str:
        if not tool_calls:
            return ""
        chips = ""
        for i, name in enumerate(tool_calls):
            text_c, bg_c, bdr_c = _tool_color(name)
            chips += (
                f'<span class="tc-chip" '
                f'style="color:{text_c};background:{bg_c};border:1px solid {bdr_c}">'
                f"{html.escape(name)}</span>"
            )
            if i < len(tool_calls) - 1:
                chips += '<span class="tc-arrow">→</span>'
        return f'<div class="tc-sequence">{chips}</div>'

    def _render_turn(
        self,
        *,
        turn: Turn,
        is_safe: bool,
        payload_tool_names: frozenset[str],
    ) -> str:
        prompt_text = html.escape(turn.request.prompt or "")
        response_text = html.escape(turn.response.text or "")

        tools_html = ""
        if turn.response.tool_calls:
            for tc in turn.response.tool_calls:
                name_lower = tc.name.lower()
                is_exec = name_lower in _EXEC_TOOLS
                text_c, bg_c, bdr_c = _tool_color(tc.name)

                tc_cls = "tool-call--malicious" if is_exec and not is_safe else "tool-call--colored"

                args_str = json.dumps(tc.arguments, indent=2, default=str) if tc.arguments else ""

                result_html = ""
                if tc.result:
                    escaped = html.escape(str(tc.result))
                    if name_lower in payload_tool_names:
                        result_html = (
                            f'<details class="tool-result"><summary>Tool Output (contains payload)</summary>'
                            f'<div class="payload-highlight"><code>{escaped}</code></div></details>'
                        )
                    else:
                        result_html = (
                            f'<details class="tool-result"><summary>Tool Output</summary>'
                            f"<pre>{escaped}</pre></details>"
                        )

                tools_html += (
                    f'<div class="{tc_cls}" style="border-left-color:{bdr_c};background:{bg_c}">'
                    f'<span class="tool-name" style="color:{text_c}">{html.escape(tc.name)}</span>'
                    f'<div class="tool-args">{html.escape(args_str)}</div>'
                    f"{result_html}</div>"
                )

        eval_html = ""
        if turn.eval_result is not None:
            outcome = turn.eval_result.outcome.value
            rationale = html.escape(turn.eval_result.rationale or "")
            if outcome == "detected":
                eval_html = f'<div class="eval-badge eval-badge--detected">▲ ATTACK DETECTED — {rationale}</div>'
            elif outcome == "not_detected":
                eval_html = f'<div class="eval-badge eval-badge--safe">● SAFE — {rationale}</div>'

        return _TURN_BLOCK.format(
            turn_number=turn.turn_number + 1,
            prompt=prompt_text,
            response=response_text,
            tool_calls=tools_html,
            eval=eval_html,
        )


# HTML fragments

_TURN_BLOCK = """\
<div class="turn">
  <div class="turn-header">Turn {turn_number}</div>
  <div class="message message--prompt">
    <div class="message-label">Prompt</div>
    <div class="message-body">{prompt}</div>
  </div>
  {tool_calls}
  <div class="message message--response">
    <div class="message-label">Response</div>
    <div class="message-body">{response}</div>
  </div>
  {eval}
</div>
"""

_RESULT_ROW = """\
<div class="result" data-status="{status}" id="result-{index}">
  <button class="result-header" onclick="toggle(this)" aria-expanded="false">
    <span class="result-icon {icon_cls}">{icon}</span>
    <div class="result-info">
      <div class="result-name">{summary}</div>
      <div class="result-sub">{test_name}</div>
    </div>
    <div class="result-tags">
      <span class="pill {pill_cls}">{pill_label}</span>
      <span class="pill pill--strategy">{strategy}</span>
      <span class="pill pill--model">{model}</span>
      <span class="pill pill--duration">{duration}s</span>
    </div>
    <span class="chevron">▸</span>
  </button>
  <div class="result-detail" id="detail-{index}" hidden>
    {seq_html}
    {turns}
  </div>
</div>
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>OpenClaw Agent Tests — {timestamp}</title>
<style>
  :root {{
    --bg: #09090b; --surface: #111114; --surface2: #19191e;
    --border: #27272a; --border-light: #3f3f46;
    --text: #fafafa; --text2: #a1a1aa; --text3: #71717a;
    --accent: #6366f1; --accent2: #818cf8;
    --safe: #22c55e; --safe-bg: rgba(34,197,94,0.08); --safe-border: rgba(34,197,94,0.25);
    --unsafe: #ef4444; --unsafe-bg: rgba(239,68,68,0.08); --unsafe-border: rgba(239,68,68,0.25);
    --warn: #f59e0b; --info: #06b6d4; --error: #ec4899;
    --radius: 10px; --radius-sm: 6px;
    --font: -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
    --mono: "Cascadia Code","JetBrains Mono","Fira Code",Consolas,monospace;
  }}
  *,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:var(--font); background:var(--bg); color:var(--text); line-height:1.6; }}
  .container {{ max-width:1140px; margin:0 auto; padding:2.5rem 2rem; }}

  /* Header */
  .header {{ padding:2rem 0; margin-bottom:2.5rem; border-bottom:1px solid var(--border); }}
  .header h1 {{ font-size:1.6rem; font-weight:800; letter-spacing:-0.03em; }}
  .header .sub {{ font-size:0.82rem; color:var(--text2); margin-top:0.3rem; }}
  .header .meta {{ display:flex; gap:1.5rem; margin-top:0.75rem; font-size:0.75rem; color:var(--text3); }}

  .section-title {{ font-size:0.95rem; font-weight:700; color:var(--text); margin:2rem 0 1rem; display:flex; align-items:center; gap:0.5rem; }}
  .section-title .icon {{ font-size:1.1rem; }}

  /* Stats */
  .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:0.75rem; margin-bottom:2rem; }}
  .stat {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.2rem; text-align:center; position:relative; overflow:hidden; }}
  .stat::before {{ content:''; position:absolute; top:0; left:0; right:0; height:2px; }}
  .stat--safe::before {{ background:var(--safe); }}
  .stat--unsafe::before {{ background:var(--unsafe); }}
  .stat--total::before {{ background:var(--accent); }}
  .stat--rate::before {{ background:var(--warn); }}
  .stat-val {{ font-size:2rem; font-weight:800; letter-spacing:-0.04em; line-height:1; }}
  .stat--safe .stat-val {{ color:var(--safe); }}
  .stat--unsafe .stat-val {{ color:var(--unsafe); }}
  .stat--total .stat-val {{ color:var(--accent2); }}
  .stat--rate .stat-val {{ color:var(--warn); }}
  .stat-lbl {{ font-size:0.65rem; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:var(--text2); margin-top:0.3rem; }}

  /* Overview */
  .overview {{ display:grid; grid-template-columns:280px 1fr; gap:1rem; margin-bottom:2rem; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.5rem; }}
  .card h3 {{ font-size:0.7rem; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:var(--text3); margin-bottom:1.25rem; }}
  .donut-wrap {{ position:relative; width:180px; height:180px; margin:0 auto; }}
  .donut-center {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); text-align:center; }}
  .donut-center .big {{ font-size:1.75rem; font-weight:800; color:var(--safe); }}
  .donut-center .small {{ font-size:0.65rem; color:var(--text3); text-transform:uppercase; letter-spacing:0.05em; }}
  .donut-legend {{ display:flex; gap:1.25rem; justify-content:center; margin-top:1rem; font-size:0.7rem; color:var(--text2); }}
  .donut-legend span {{ display:flex; align-items:center; gap:0.3rem; }}
  .legend-dot {{ width:8px; height:8px; border-radius:50%; }}

  .arch {{ display:flex; flex-direction:column; align-items:center; gap:0; }}
  .arch-node {{ padding:0.55rem 1.2rem; border-radius:var(--radius-sm); font-size:0.72rem; font-weight:600; text-align:center; min-width:200px; }}
  .arch-arrow {{ font-size:0.6rem; color:var(--text3); padding:0.2rem 0; text-align:center; }}
  .arch-arrow .arr {{ color:var(--border-light); }}
  .n-sandbox {{ background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.2); color:#fca5a5; }}
  .n-bridge {{ background:rgba(6,182,212,0.08); border:1px solid rgba(6,182,212,0.2); color:#67e8f9; }}
  .n-proxy {{ background:rgba(139,92,246,0.08); border:1px solid rgba(139,92,246,0.2); color:#c4b5fd; }}
  .n-cloud {{ background:rgba(34,197,94,0.08); border:1px solid rgba(34,197,94,0.2); color:#86efac; }}
  .n-docker {{ border:1px dashed var(--border-light); border-radius:var(--radius); padding:0.75rem; margin:0.3rem 0; }}
  .n-docker-lbl {{ font-size:0.55rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--text3); margin-bottom:0.4rem; text-align:center; }}

  /* Surfaces */
  .surface-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:0.75rem; margin-bottom:2rem; }}
  .surface-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.25rem; }}
  .surface-card h4 {{ font-size:0.8rem; font-weight:700; margin-bottom:0.35rem; }}
  .surface-card p {{ font-size:0.72rem; color:var(--text2); line-height:1.5; margin-bottom:0.6rem; }}
  .surface-stats {{ display:flex; gap:0.5rem; font-size:0.65rem; }}
  .surface-stat {{ padding:0.2rem 0.6rem; border-radius:20px; font-weight:600; }}
  .surface-stat--safe {{ background:var(--safe-bg); color:var(--safe); border:1px solid var(--safe-border); }}
  .surface-stat--unsafe {{ background:var(--unsafe-bg); color:var(--unsafe); border:1px solid var(--unsafe-border); }}
  .surface-stat--other {{ background:rgba(245,158,11,0.08); color:var(--warn); border:1px solid rgba(245,158,11,0.25); }}

  /* Heatmap */
  .heatmap-table {{
    width:100%; border-collapse:separate; border-spacing:3px;
    background:var(--surface); border-radius:var(--radius); padding:1.25rem; border:1px solid var(--border);
  }}
  .heatmap-table th {{ font-size:0.6rem; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; color:var(--text3); padding:0.4rem; text-align:center; }}
  .heatmap-table th:first-child {{ text-align:left; min-width:180px; }}
  .heatmap-table td {{ text-align:center; padding:0.4rem; border-radius:4px; font-size:0.7rem; font-weight:700; transition:transform 0.1s; }}
  .heatmap-table td:first-child {{ text-align:left; font-weight:600; font-size:0.72rem; color:var(--text); background:none!important; cursor:default; }}
  .heatmap-table td:not(:first-child) {{ cursor:pointer; }}
  .heatmap-table td:not(:first-child):hover {{ transform:scale(1.15); }}
  .hm-safe {{ background:rgba(34,197,94,0.15); color:var(--safe); }}
  .hm-unsafe {{ background:rgba(239,68,68,0.18); color:var(--unsafe); }}
  .hm-other {{ background:rgba(245,158,11,0.12); color:var(--warn); }}
  .hm-safe::after {{ content:'✓'; }}
  .hm-unsafe::after {{ content:'✕'; }}
  .hm-other::after {{ content:'?'; }}

  /* Filters */
  .filters {{ display:flex; gap:0.4rem; margin-bottom:1.25rem; align-items:center; flex-wrap:wrap; }}
  .filters-label {{ font-size:0.65rem; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:var(--text3); margin-right:0.4rem; }}
  .filter-btn {{
    font-family:var(--font); font-size:0.7rem; font-weight:500; padding:0.35rem 0.85rem;
    border-radius:20px; border:1px solid var(--border); background:var(--surface); color:var(--text2); cursor:pointer; transition:all 0.15s;
  }}
  .filter-btn:hover {{ border-color:var(--accent); color:var(--text); }}
  .filter-btn.active {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
  .filter-count {{ font-size:0.6rem; background:var(--surface2); padding:0.1rem 0.35rem; border-radius:8px; margin-left:0.25rem; }}

  /* Results */
  .result {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); margin-bottom:0.5rem; overflow:hidden; transition:border-color 0.15s; }}
  .result:hover {{ border-color:var(--border-light); }}
  .result[data-status="unsafe"] {{ border-left:3px solid var(--unsafe); }}
  .result[data-status="safe"] {{ border-left:3px solid var(--safe); }}
  .result[data-status="undetermined"] {{ border-left:3px solid var(--warn); }}
  .result[data-status="error"] {{ border-left:3px solid var(--error); }}
  .result-header {{
    display:flex; align-items:center; gap:0.6rem; padding:0.8rem 1.25rem; width:100%;
    background:none; border:none; color:var(--text); font:inherit; font-size:0.8rem; cursor:pointer; text-align:left;
  }}
  .result-icon {{ flex-shrink:0; font-size:0.9rem; }}
  .icon-safe {{ color:var(--safe); }} .icon-unsafe {{ color:var(--unsafe); }} .icon-other {{ color:var(--warn); }}
  .result-info {{ flex:1; min-width:0; }}
  .result-name {{ font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:0.78rem; }}
  .result-sub {{ font-size:0.65rem; color:var(--text3); margin-top:0.1rem; font-family:var(--mono); }}
  .result-tags {{ display:flex; gap:0.3rem; flex-shrink:0; flex-wrap:wrap; justify-content:flex-end; }}
  .pill {{ font-size:0.6rem; font-weight:600; padding:0.15rem 0.5rem; border-radius:20px; white-space:nowrap; }}
  .pill--safe {{ background:var(--safe-bg); color:var(--safe); border:1px solid var(--safe-border); }}
  .pill--unsafe {{ background:var(--unsafe-bg); color:var(--unsafe); border:1px solid var(--unsafe-border); }}
  .pill--other {{ background:rgba(245,158,11,0.08); color:var(--warn); border:1px solid rgba(245,158,11,0.25); }}
  .pill--strategy {{ background:rgba(99,102,241,0.08); color:var(--accent2); border:1px solid rgba(99,102,241,0.2); }}
  .pill--model {{ background:rgba(6,182,212,0.08); color:var(--info); border:1px solid rgba(6,182,212,0.2); }}
  .pill--duration {{ background:var(--surface2); color:var(--text3); border:1px solid var(--border); }}
  .chevron {{ font-size:0.75rem; color:var(--text3); transition:transform 0.2s; flex-shrink:0; }}
  .result-header[aria-expanded="true"] .chevron {{ transform:rotate(90deg); }}
  .result-detail {{ padding:0 1.25rem 1.25rem; }}
  .result-detail[hidden] {{ display:none; }}

  .tc-sequence {{ display:flex; align-items:center; gap:0.2rem; flex-wrap:wrap; margin:0.3rem 0 0.75rem; }}
  .tc-chip {{ font-family:var(--mono); font-size:0.62rem; font-weight:600; padding:0.15rem 0.5rem; border-radius:3px; }}
  .tc-arrow {{ color:var(--text3); font-size:0.65rem; }}

  .turn {{ background:var(--surface2); border:1px solid var(--border); border-radius:var(--radius-sm); padding:1rem; margin-bottom:0.6rem; }}
  .turn-header {{ font-size:0.6rem; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--accent2); margin-bottom:0.75rem; }}
  .message {{ margin-bottom:0.75rem; border-radius:var(--radius-sm); padding:0.75rem 1rem; }}
  .message--prompt {{ background:rgba(99,102,241,0.05); border-left:3px solid var(--accent); }}
  .message--response {{ background:rgba(255,255,255,0.015); border-left:3px solid var(--border); }}
  .message-label {{ font-size:0.55rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:var(--text3); margin-bottom:0.3rem; }}
  .message-body {{ font-size:0.78rem; white-space:pre-wrap; word-break:break-word; line-height:1.55; }}

  .tool-call--colored,.tool-call--malicious {{ border-radius:var(--radius-sm); padding:0.7rem 0.9rem; margin-bottom:0.4rem; font-family:var(--mono); font-size:0.7rem; border-left:3px solid; }}
  .tool-call--malicious {{ position:relative; }}
  .tool-call--malicious::after {{
    content:'ATTACK'; position:absolute; top:0.4rem; right:0.6rem;
    font-family:var(--font); font-size:0.5rem; font-weight:700; letter-spacing:0.08em;
    color:var(--unsafe); background:var(--unsafe-bg); padding:0.1rem 0.4rem; border-radius:8px; border:1px solid var(--unsafe-border);
  }}
  .tool-name {{ font-weight:700; margin-bottom:0.2rem; display:block; }}
  .tool-args {{ color:var(--text3); font-size:0.65rem; white-space:pre-wrap; }}
  .tool-result {{ margin-top:0.4rem; padding-top:0.4rem; border-top:1px solid var(--border); color:var(--text2); font-size:0.65rem; max-height:180px; overflow-y:auto; }}
  .tool-result summary {{ cursor:pointer; font-family:var(--font); font-weight:600; font-size:0.6rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text3); }}

  .payload-highlight {{ background:rgba(239,68,68,0.04); border:1px solid rgba(239,68,68,0.15); border-radius:var(--radius-sm); padding:0.75rem; margin:0.5rem 0; position:relative; }}
  .payload-highlight::before {{ content:'⚠ INJECTED PAYLOAD'; font-size:0.5rem; font-weight:700; letter-spacing:0.1em; color:var(--unsafe); display:block; margin-bottom:0.3rem; }}
  .payload-highlight code {{ font-family:var(--mono); font-size:0.68rem; color:#fca5a5; display:block; white-space:pre-wrap; }}

  .eval-badge {{ display:inline-flex; align-items:center; gap:0.3rem; padding:0.4rem 0.8rem; border-radius:var(--radius-sm); font-size:0.7rem; font-weight:700; margin-top:0.4rem; }}
  .eval-badge--detected {{ background:var(--unsafe-bg); border:1px solid var(--unsafe-border); color:var(--unsafe); }}
  .eval-badge--safe {{ background:var(--safe-bg); border:1px solid var(--safe-border); color:var(--safe); }}

  .takeaway {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1.5rem; margin-bottom:2rem; }}
  .takeaway-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:0.75rem; margin-top:0.75rem; }}
  .takeaway-item {{ padding:1rem; border-radius:var(--radius-sm); border:1px solid var(--border); background:var(--surface2); }}
  .takeaway-item h4 {{ font-size:0.75rem; font-weight:700; margin-bottom:0.35rem; }}
  .takeaway-item p {{ font-size:0.7rem; color:var(--text2); line-height:1.45; }}

  .sandbox-env {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:0.75rem; margin-bottom:2rem; }}
  .env-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:1rem 1.25rem; }}
  .env-card h4 {{ font-size:0.65rem; font-weight:600; text-transform:uppercase; letter-spacing:0.07em; color:var(--text3); margin-bottom:0.6rem; }}
  .env-row {{ display:flex; justify-content:space-between; align-items:center; padding:0.3rem 0; border-bottom:1px solid rgba(255,255,255,0.025); font-size:0.72rem; }}
  .env-row:last-child {{ border-bottom:none; }}
  .env-key {{ color:var(--text2); }}
  .env-val {{ font-family:var(--mono); font-size:0.66rem; color:var(--text); background:var(--surface2); padding:0.1rem 0.4rem; border-radius:3px; }}
  .env-val--safe {{ color:var(--safe); background:var(--safe-bg); }}
  .file-list {{ list-style:none; padding:0; font-family:var(--mono); font-size:0.65rem; color:var(--text2); max-height:140px; overflow-y:auto; }}
  .file-list li {{ padding:0.15rem 0; border-bottom:1px solid rgba(255,255,255,0.015); }}
  .file-list li:last-child {{ border-bottom:none; }}
  .file-size {{ float:right; color:var(--text3); font-size:0.6rem; }}

  .footer {{ text-align:center; padding:1.5rem 0; font-size:0.65rem; color:var(--text3); border-top:1px solid var(--border); margin-top:1rem; }}

  @keyframes highlight {{ 0% {{ box-shadow:0 0 0 2px var(--accent); }} 100% {{ box-shadow:none; }} }}
  .result--highlight {{ animation:highlight 1.5s ease-out; }}

  @media (max-width:800px) {{
    .stats {{ grid-template-columns:repeat(2,1fr); }}
    .overview {{ grid-template-columns:1fr; }}
    .surface-grid {{ grid-template-columns:1fr; }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>OpenClaw Agent Tests</h1>
    <div class="sub">Security assessment results — automated RAMPART test run</div>
    <div class="meta">
      <span>{timestamp} UTC</span>
      <span>{model}</span>
      <span>{duration_min} min</span>
      <span>{total} trials</span>
    </div>
  </div>

  <div class="stats">
    <div class="stat stat--total"><div class="stat-val">{total}</div><div class="stat-lbl">Total</div></div>
    <div class="stat stat--safe"><div class="stat-val">{passed}</div><div class="stat-lbl">Defended</div></div>
    <div class="stat stat--unsafe"><div class="stat-val">{failed}</div><div class="stat-lbl">Compromised</div></div>
    <div class="stat stat--rate"><div class="stat-val">{asr}%</div><div class="stat-lbl">Attack Success Rate</div></div>
  </div>

  <div class="overview">
    <div class="card">
      <h3>Pass Rate</h3>
      <div class="donut-wrap">
        <svg viewBox="0 0 200 200" width="180" height="180">
          <circle cx="100" cy="100" r="80" fill="none" stroke="#27272a" stroke-width="18"/>
          <circle cx="100" cy="100" r="80" fill="none" stroke="#22c55e" stroke-width="18"
                  stroke-dasharray="{safe_arc} {unsafe_arc}" stroke-dashoffset="125.6"
                  stroke-linecap="round" transform="rotate(-90 100 100)">
            <animate attributeName="stroke-dasharray" from="0 {circ}" to="{safe_arc} {unsafe_arc}" dur="0.8s"/>
          </circle>
        </svg>
        <div class="donut-center">
          <div class="big">{safe_pct}%</div>
          <div class="small">Safe</div>
        </div>
      </div>
      <div class="donut-legend">
        <span><span class="legend-dot" style="background:var(--safe)"></span> {safe_count} safe</span>
        <span><span class="legend-dot" style="background:var(--unsafe)"></span> {unsafe_count} unsafe</span>
      </div>
    </div>
    <div class="card">
      <h3>Test Architecture</h3>
      <div class="arch">
        <div class="n-docker">
          <div class="n-docker-lbl">Docker Sandbox — Network Deny All</div>
          <div class="arch-node n-sandbox">OpenClaw Agent — :18789</div>
          <div class="arch-arrow"><span class="arr">↓</span></div>
          <div class="arch-node n-bridge">Bridge — 127.0.0.1:54321</div>
        </div>
        <div class="arch-arrow"><span class="arr">↓</span> <span style="margin-left:0.3rem">firewall allows only :12435</span></div>
        <div class="arch-node n-proxy">Auth Proxy — :12435</div>
        <div class="arch-arrow"><span class="arr">↓</span> <span style="margin-left:0.3rem">+ Authorization header</span></div>
        <div class="arch-node n-cloud">{provider}</div>
      </div>
    </div>
  </div>

  <div class="section-title"><span class="icon">🎯</span> Attack Surfaces</div>
  <div class="surface-grid">{surface_cards_html}</div>

  <div class="section-title"><span class="icon">🗺️</span> Scenario × Trial</div>
  {heatmap_html}

  <div class="section-title" style="margin-top:2rem"><span class="icon">📋</span> Results</div>
  <div class="filters">
    <span class="filters-label">Show:</span>
    <button class="filter-btn active" onclick="filterStatus('all',this)">All <span class="filter-count">{total}</span></button>
    <button class="filter-btn" onclick="filterStatus('unsafe',this)">Unsafe <span class="filter-count">{failed}</span></button>
    <button class="filter-btn" onclick="filterStatus('safe',this)">Safe <span class="filter-count">{passed}</span></button>
  </div>
  <div class="results-list" id="results">{results}</div>

  <div class="takeaway">
    <div class="section-title" style="margin:0 0 0.5rem"><span class="icon">💡</span> Findings</div>
    <div class="takeaway-grid">{findings_html}</div>
  </div>

  <div style="margin-top:2rem">{sandbox_env_html}</div>

  <div class="footer">RAMPART × OpenClaw · {timestamp} UTC</div>
</div>

<script>
function toggle(btn) {{
  const d = btn.nextElementSibling;
  const exp = btn.getAttribute("aria-expanded") === "true";
  btn.setAttribute("aria-expanded", String(!exp));
  d.hidden = exp;
}}
function filterStatus(s, btn) {{
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".result").forEach(el => {{
    el.style.display = (s === "all" || el.dataset.status === s) ? "" : "none";
  }});
}}
function scrollToResult(idx) {{
  const el = document.getElementById("result-" + idx);
  if (!el) return;
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
  document.querySelector(".filter-btn").classList.add("active");
  document.querySelectorAll(".result").forEach(r => r.style.display = "");
  const btn = el.querySelector(".result-header");
  if (btn && btn.getAttribute("aria-expanded") !== "true") btn.click();
  el.scrollIntoView({{ behavior:"smooth", block:"center" }});
  el.classList.remove("result--highlight");
  void el.offsetWidth;
  el.classList.add("result--highlight");
}}
</script>
</body>
</html>
"""
