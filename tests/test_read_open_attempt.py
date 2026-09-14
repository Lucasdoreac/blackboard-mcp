"""`read_open_attempt`: lê a tentativa aberta, nunca cria uma."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings

BASE = "https://bb.example.edu"
ITEM = {"title": "AS - Unidade I", "contentDetail": {"resource/x-bb-asmt-test-link": {"test": {"gradingColumn": {"id": "_5_1"}}}}}
ATTEMPT = {"id": "_9_1", "status": "IN_PROGRESS", "attemptDate": "2026-09-14T19:33:24Z", "toolAttemptDetail": {"resource/x-bb-assessment": {
    "assessment": {"title": "AS - Unidade I"},
    "questionAttempts": [{"questionType": "multipleanswer", "questionId": "_1_1", "visibleQuestionNumber": 1, "givenAnswer": [False, False],
                          "question": {"questionText": {"rawText": "<p>Q?</p>"}, "answers": [{"answerText": {"rawText": "<p>a</p>"}}, {"answerText": {"rawText": "<p>b</p>"}}]}}],
}}}


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lookup: dict) -> tuple[BlackboardClient, AsyncMock]:
    client = BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))

    async def rest_get(path, params=None):
        if path.endswith("/contents/_2_1"):
            return ITEM
        if path.endswith("/users/me"):
            return {"id": "_me_1"}
        if path.endswith("/attempts"):
            return {"lookup": lookup}
        return ATTEMPT

    get = AsyncMock(side_effect=rest_get)
    monkeypatch.setattr(client, "_rest_get", get)
    return client, get


@pytest.mark.asyncio
async def test_reads_the_in_progress_attempt_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(tmp_path, monkeypatch, {"_g_1": [{"id": "_9_1", "status": "IN_PROGRESS"}]})
    out = await client.read_open_attempt("_7_1", "_2_1")
    assert out["open"] is True and out["attempt_id"] == "_9_1"
    assert out["questions"][0]["text"] == "Q?" and [o["text"] for o in out["questions"][0]["options"]] == ["a", "b"]


@pytest.mark.asyncio
async def test_without_open_attempt_returns_open_false_and_never_posts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, get = _client(tmp_path, monkeypatch, {"_g_1": [{"id": "_8_1", "status": "COMPLETED"}]})
    out = await client.read_open_attempt("_7_1", "_2_1")
    assert out["open"] is False
    assert not any("gradebook/attempts/" in str(call.args[0]) for call in get.await_args_list)
    assert not hasattr(client._session, "post")
