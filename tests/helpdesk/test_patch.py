# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Mitigation-patch round-trip + demo collect-only smoke tests."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ._helpers import HELPDESK_BOT_DIR

if TYPE_CHECKING:
    from pathlib import Path


class TestMitigationPatch:
    """The shipped ``mitigation.patch`` round-trips against the live ``agent.py``."""

    def test_applies_and_reverses_cleanly(self, tmp_path: Path) -> None:
        """The published patch applies, parses, and reverses on a clean checkout.

        Protects the README's three-step walkthrough: if the patch
        drifts out of sync with ``agent.py``, this test fails before any
        demo user hits a confusing ``error: patch failed``.
        """
        git_path = shutil.which("git")
        if git_path is None:
            pytest.skip("git not on PATH")

        work = tmp_path / "demo"
        pkg_dir = work / "helpdesk-bot" / "helpdesk_bot"
        pkg_dir.mkdir(parents=True)
        shutil.copy(
            HELPDESK_BOT_DIR / "helpdesk_bot" / "agent.py",
            pkg_dir / "agent.py",
        )
        shutil.copy(HELPDESK_BOT_DIR / "mitigation.patch", work / "mitigation.patch")

        def git(*args: str) -> subprocess.CompletedProcess[str]:
            # All args originate from this test file (literal strings); no
            # untrusted input reaches subprocess.
            return subprocess.run(  # noqa: S603 (git path from shutil.which is trusted)
                [git_path, *args],
                cwd=work,
                check=True,
                capture_output=True,
                text=True,
            )

        git("init", "-q", "--initial-branch=main")
        git("config", "user.email", "smoke@local")
        git("config", "user.name", "smoke")
        git("config", "core.autocrlf", "false")
        git("add", "helpdesk-bot/helpdesk_bot/agent.py")
        git("commit", "-qm", "baseline")

        # Apply. Must succeed, must produce valid Python.
        git("apply", "mitigation.patch")
        ast.parse((pkg_dir / "agent.py").read_text(encoding="utf-8"))

        # Reverse. After reverse the file must be byte-identical to the
        # original baseline (so `git checkout -- helpdesk_bot/agent.py`
        # in the README is equivalent to `git apply -R`).
        git("apply", "-R", "mitigation.patch")
        original_bytes = (HELPDESK_BOT_DIR / "helpdesk_bot" / "agent.py").read_bytes()
        post_reverse_bytes = (pkg_dir / "agent.py").read_bytes()
        assert post_reverse_bytes == original_bytes

    def test_demo_pytest_collects_without_errors(self) -> None:
        """``pytest --collect-only`` inside the helpdesk_bot demo must not error.

        Fast, integrated check that the test file's imports
        (``helpdesk_bot.*``, ``rampart``, ``agent_framework``) all resolve
        and that pytest's RAMPART markers register cleanly. Does not run
        any test body, so no LLM call is made.
        """
        # Use sys.executable so the collect-only run hits the same
        # interpreter pytest itself was invoked with; pinning to an
        # absolute path or a bare "python" would be wrong on most CI
        # runners (different venv, different Python version).
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_xpia.py"],
            cwd=HELPDESK_BOT_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"pytest collect failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
