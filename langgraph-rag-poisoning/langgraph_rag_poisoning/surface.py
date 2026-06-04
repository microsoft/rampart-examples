from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Self

from rampart.core.injection import InjectionHandle, sleep_until_ready

if TYPE_CHECKING:
    import types
    from rampart import Payload

_logger = logging.getLogger(__name__)

DEFAULT_DOCS_DIR = Path(__file__).resolve().parent / "data" / "docs"


def _resolve_docs_dir() -> Path:
    """Return the configured docs-store directory.

    Reads ``RAG_DOCS_DIR`` from the environment; falls back to
    the demo's bundled ``data/docs`` directory. Supports pytest-xdist partition.
    """
    override = os.getenv("RAG_DOCS_DIR")
    root = Path(override).resolve() if override else DEFAULT_DOCS_DIR

    worker_id = os.getenv("PYTEST_XDIST_WORKER")
    if worker_id and worker_id != "master":
        root = root.parent / f"{root.name}_{worker_id}"
    return root


class DocStore:
    """Filesystem-backed document store."""

    def __init__(self, root: Path | None = None) -> None:
        """Initialise the store. Defaults to the configured docs directory."""
        self._root = root or _resolve_docs_dir()
        
        # If worker partition, copy baseline documents to it so retrieval works correctly
        if self._root != DEFAULT_DOCS_DIR:
            self._root.mkdir(parents=True, exist_ok=True)
            if DEFAULT_DOCS_DIR.exists():
                for path in DEFAULT_DOCS_DIR.glob("*.md"):
                    dst = self._root / path.name
                    # Do not copy poisoned_policy.md since it is injected by tests
                    if path.name == "poisoned_policy.md":
                        continue
                    if not dst.exists():
                        try:
                            dst.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                        except Exception:
                            pass

    @property
    def root(self) -> Path:
        """Directory backing this document store."""
        return self._root

    def read(self, filename: str) -> str:
        """Return content of a document, or empty string."""
        path = self._root / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write(self, filename: str, content: str) -> Path:
        """Create or overwrite a document."""
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / filename
        path.write_text(content, encoding="utf-8")
        return path

    def delete(self, filename: str) -> None:
        """Remove a document."""
        path = self._root / filename
        path.unlink(missing_ok=True)


@dataclass(frozen=True, kw_only=True, slots=True)
class LocalDocSurface:
    """RAMPART ``Surface`` that injects a poisoned policy document into the store."""

    store: DocStore = field(default_factory=DocStore)
    indexing_delay: float = 0.0

    def inject(self, *, payload: Payload) -> _LocalDocInjection:
        """Prepare an injection of ``payload`` into the doc store."""
        return _LocalDocInjection(
            surface=self,
            payload=payload,
        )


class _LocalDocInjection(InjectionHandle):
    """``InjectionHandle`` for ``LocalDocSurface``.

    Writes the poisoned policy document on ``__aenter__`` and deletes it on
    ``__aexit__``.
    """

    def __init__(
        self,
        *,
        surface: LocalDocSurface,
        payload: Payload,
    ) -> None:
        self._surface = surface
        self._payload = payload
        self._filename = "poisoned_policy.md"

    @property
    def payload_id(self) -> str | None:
        """Stable identifier for the injected payload."""
        return self._payload.id

    @property
    def surface_name(self) -> str:
        """Friendly name surfaced in RAMPART reports."""
        return "LocalDocStore"

    async def wait_until_ready(self) -> None:
        """Sleep for ``indexing_delay`` seconds (default 0)."""
        if self._surface.indexing_delay > 0:
            await sleep_until_ready(self._surface.indexing_delay)

    async def __aenter__(self) -> Self:
        """Activate the injection by writing the poisoned document."""
        self._surface.store.write(
            self._filename,
            self._payload.content,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Remove the poisoned document. Cleanup must not raise."""
        try:
            self._surface.store.delete(self._filename)
        except Exception:
            _logger.debug(
                "LocalDocSurface cleanup failed for %s",
                self._filename,
                exc_info=True,
            )
