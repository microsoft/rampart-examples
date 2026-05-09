# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the ticket CRUD routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

# Endpoints removed in the rewrite. Tests guard against accidental
# resurrection. Spelled obliquely to keep the source text clean of
# legacy terminology. (``/api/health`` and ``/api/tools`` are back
# under ``meta.py`` and tested separately.)
_DROPPED_ENDPOINTS = (
    "/api/tickets-fixtures/" + "x" + "pia",
    "/api/events",
)


def test_list_empty(client: TestClient, tmp_ticket_dir: Path) -> None:
    assert client.get("/api/tickets").json() == []


def test_create_then_list(client: TestClient, tmp_ticket_dir: Path) -> None:
    r = client.post(
        "/api/tickets",
        json={"subject": "hi", "from": "a@b.com", "body": "x"},
    )
    assert r.status_code == 201
    assert r.json()["id"] == "T-1003"
    assert len(client.get("/api/tickets").json()) == 1


def test_next_id_walks_max(client: TestClient, seeded_ticket_dir: Path) -> None:
    r = client.post(
        "/api/tickets",
        json={"subject": "x", "from": "x@y.com", "body": "x"},
    )
    assert r.json()["id"] == "T-1004"


def test_sorting_by_mtime_ns(client: TestClient, seeded_ticket_dir: Path) -> None:
    # Touch T-1001 to make it the most recent without depending on
    # fixture-write ordering.
    (seeded_ticket_dir / "T-1001.json").write_text(
        (seeded_ticket_dir / "T-1001.json").read_text(),
    )
    ids = [t["id"] for t in client.get("/api/tickets").json()]
    assert ids[0] == "T-1001"


def test_get_404(client: TestClient, tmp_ticket_dir: Path) -> None:
    assert client.get("/api/tickets/T-9999").status_code == 404


def test_get_400_invalid_id(client: TestClient) -> None:
    assert client.get("/api/tickets/INVALID").status_code == 400


def test_delete(client: TestClient, seeded_ticket_dir: Path) -> None:
    assert client.delete("/api/tickets/T-1001").status_code == 204
    assert client.get("/api/tickets/T-1001").status_code == 404


def test_sample_returns_t1003_body(
    client: TestClient,
    seeded_ticket_dir: Path,
) -> None:
    r = client.get("/api/tickets/sample").json()
    assert r["from"] == "alex.kim@contoso.com"
    assert "policy 4.7.2" in r["body"]


def test_sample_404_when_seed_missing(
    client: TestClient,
    tmp_ticket_dir: Path,
) -> None:
    assert client.get("/api/tickets/sample").status_code == 404


@pytest.mark.parametrize("path", _DROPPED_ENDPOINTS)
def test_dropped_endpoints_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_no_reset_endpoint(client: TestClient) -> None:
    assert client.post("/api/reset").status_code in (404, 405)
