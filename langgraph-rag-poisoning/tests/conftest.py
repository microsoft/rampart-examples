from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv

from langgraph_rag_poisoning.adapter import RAGRefundAdapter
from langgraph_rag_poisoning.surface import LocalDocSurface
from rampart.reporting import JsonFileReportSink, ReportSink


@pytest.fixture(scope="session", autouse=True)
def _load_demo_env() -> None:
    """Load dotenv configuration once for the session."""
    load_dotenv()


@pytest.fixture(scope="session")
def rampart_sinks() -> list[ReportSink]:
    """Specify RAMPART report output locations."""
    return [JsonFileReportSink(output_dir=Path(".report"))]


@pytest.fixture
def refund_bot() -> RAGRefundAdapter:
    """Return a fresh RAGRefundAdapter instance."""
    return RAGRefundAdapter()


@pytest.fixture
def doc_surface() -> LocalDocSurface:
    """Return a LocalDocSurface instance."""
    return LocalDocSurface()
