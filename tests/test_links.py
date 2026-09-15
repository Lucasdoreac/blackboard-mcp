"""Link Ultra em toda atividade e aviso que sai da bridge — o dono abre direto."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings

BASE = "https://bb.example.edu"


def _item() -> dict:
    return {
        "title": "AS", "contentHandler": "resource/x-bb-asmt-test-link", "visibility": "VISIBLE",
        "genericReadOnlyData": {"dueDate": "2026-11-06T23:59:00.000Z"},
        "contentDetail": {"resource/x-bb-asmt-test-link": {"test": {
            "assessment": {"subtype": "Assignment", "instructions": {"rawText": ""}, "description": {"rawText": ""}},
            "deploymentSettings": {"attemptCount": 1},
        }}},
    }


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))


@pytest.mark.asyncio
async def test_listed_activity_carries_the_ultra_overview_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[
        {"id": "_7_1", "title": "AS - Unidade I", "kind": "item", "depth": 1, "due_at": "2026-11-06T23:59:00.000Z"},
    ]))
    [row] = await client.list_assessments("_1_1")
    assert row["url"] == f"{BASE}/ultra/courses/_1_1/assessment/_7_1/overview"


@pytest.mark.asyncio
async def test_activity_detail_carries_the_same_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value=_item()))
    detail = await client.get_assessment("_1_1", "_7_1")
    assert detail["url"] == f"{BASE}/ultra/courses/_1_1/assessment/_7_1/overview"


@pytest.mark.asyncio
async def test_announcement_carries_the_course_announcements_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value={"results": [
        {"id": "_3_1", "title": "Prova remarcada", "createdDate": "2026-09-15T10:00:00Z", "body": {"rawText": "<p>Nova data</p>"}},
    ]}))
    [row] = await client.list_announcements("_1_1")
    assert row["url"] == f"{BASE}/ultra/courses/_1_1/announcements"
