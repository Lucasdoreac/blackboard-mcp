"""`BlackboardClient.list_video_transcripts` orchestration, including the
parent-folder retry (real incident 2026-09-04: a "Videoaula" folder wraps a
single document child that embeds the Kaltura player — only the FOLDER's
own URL loads it, confirmed live by network capture)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", data_home=tmp_path))


@pytest.fixture(autouse=True)
def _no_pacing_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """`list_video_transcripts` paces real page navigations (2s/page, real
    incident 2026-09-04 — see `client.py`); tests exercise the LOGIC, not
    real wall-clock time, so the pace is zeroed here (a dedicated test below
    proves the pacing call itself happens)."""
    monkeypatch.setattr(BlackboardClient, "_PAGE_VISIT_PACE_S", 0.0)


_DOC_ROW = {
    "id": "_2_1", "title": "ultraDocumentBody", "kind": "item", "depth": 1,
    "due_at": None, "mime_type": None, "content_handler": "resource/x-bb-document",
    "external_url": None, "parent_id": "_1_1",
}
_DOC_ROW_NO_PARENT = {**_DOC_ROW, "id": "_3_1", "parent_id": None}
_FILE_ROW = {
    "id": "_4_1", "title": "Aula.pdf", "kind": "item", "depth": 1,
    "due_at": None, "mime_type": "application/pdf", "content_handler": "resource/x-bb-file",
    "external_url": None, "parent_id": "_1_1",
}


@pytest.mark.asyncio
async def test_only_visits_document_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW_NO_PARENT, _FILE_ROW]))
    get_transcript = AsyncMock(return_value=None)
    monkeypatch.setattr(client, "get_video_transcript", get_transcript)

    result = await client.list_video_transcripts("_1189334_1")

    assert result == []
    get_transcript.assert_awaited_once_with("_1189334_1", "_3_1")


@pytest.mark.asyncio
async def test_returns_transcript_found_directly_on_the_document_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW_NO_PARENT]))
    monkeypatch.setattr(client, "get_video_transcript", AsyncMock(return_value="fala do professor."))

    result = await client.list_video_transcripts("_1189334_1")

    assert result == [{
        "course_id": "_1189334_1", "content_id": "_3_1",
        "title": "ultraDocumentBody", "transcript": "fala do professor.",
    }]


@pytest.mark.asyncio
async def test_retries_on_the_parent_folder_when_the_document_page_yields_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check target: without the retry, this course's real video
    (confirmed live) would never be found — the document page alone loads
    no player."""
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW]))

    async def fake_get_video_transcript(course_id: str, content_id: str) -> str | None:
        return "fala do professor." if content_id == "_1_1" else None

    monkeypatch.setattr(client, "get_video_transcript", AsyncMock(side_effect=fake_get_video_transcript))

    result = await client.list_video_transcripts("_1189334_1")

    assert result == [{
        "course_id": "_1189334_1", "content_id": "_2_1",  # keyed by the CHILD id, not the parent's
        "title": "ultraDocumentBody", "transcript": "fala do professor.",
    }]


@pytest.mark.asyncio
async def test_never_retries_when_there_is_no_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW_NO_PARENT]))
    get_transcript = AsyncMock(return_value=None)
    monkeypatch.setattr(client, "get_video_transcript", get_transcript)

    result = await client.list_video_transcripts("_1189334_1")

    assert result == []
    assert get_transcript.await_count == 1


@pytest.mark.asyncio
async def test_rejects_an_invalid_course_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with pytest.raises(ValueError, match="course_id invalido"):
        await client.list_video_transcripts("not-a-course-id")


@pytest.mark.asyncio
async def test_a_failing_page_never_aborts_the_rest_of_the_course(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check target: real incident (2026-09-04) — a Playwright
    `TimeoutError` talking to Kaltura on ONE broken page killed
    `list_video_transcripts` before it ever reached the course's other,
    healthy pages."""
    client = _client(tmp_path)
    other_doc_row = {**_DOC_ROW_NO_PARENT, "id": "_5_1"}
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW_NO_PARENT, other_doc_row]))

    async def flaky_get_video_transcript(course_id: str, content_id: str) -> str | None:
        if content_id == "_3_1":
            raise TimeoutError("APIRequestContext.post: Timeout 30000ms exceeded.")
        return "fala do professor."

    monkeypatch.setattr(client, "get_video_transcript", AsyncMock(side_effect=flaky_get_video_transcript))

    result = await client.list_video_transcripts("_1189334_1")

    assert result == [{
        "course_id": "_1189334_1", "content_id": "_5_1",
        "title": "ultraDocumentBody", "transcript": "fala do professor.",
    }]


def _mock_authenticated_page(monkeypatch: pytest.MonkeyPatch, client: BlackboardClient) -> AsyncMock:
    fake_page = AsyncMock()
    monkeypatch.setattr(
        client, "_authenticated_page",
        AsyncMock(return_value=(AsyncMock(), AsyncMock(), fake_page, True)),
    )
    monkeypatch.setattr(client, "_close", AsyncMock())
    return fake_page


@pytest.mark.asyncio
async def test_full_discovery_paces_after_the_real_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real incident (2026-09-04): back-to-back real Playwright navigations
    (not REST calls) made Blackboard Ultra's own SPA throw an error screen
    mid-walk — a short pace after each FULL discovery navigation avoids
    hammering it. A cache hit (below) never navigates Blackboard at all and
    has nothing to be gentle about, so it must NOT pay this pace."""
    monkeypatch.setattr(BlackboardClient, "_PAGE_VISIT_PACE_S", 2.0)  # override the autouse fixture above
    client = _client(tmp_path)
    _mock_authenticated_page(monkeypatch, client)
    monkeypatch.setattr(client, "_discover_kaltura_ids", AsyncMock(return_value=None))
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    import blackboard_mcp.client as client_module
    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)

    result = await client.get_video_transcript("_1189334_1", "_2_1")

    assert result is None
    assert sleep_calls == [2.0]


@pytest.mark.asyncio
async def test_cached_negative_skips_all_browser_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A page already confirmed to have no video is never re-checked — real
    incident (2026-09-04): re-walking already-seen, video-less pages every
    run hit Blackboard's own bloat/error pages for nothing."""
    from blackboard_mcp import video_transcript_cache

    client = _client(tmp_path)
    video_transcript_cache.save_entry(tmp_path, "_1189334_1", "_2_1", has_video=False)
    authenticated_page = AsyncMock(side_effect=AssertionError("must never open an authenticated page"))
    monkeypatch.setattr(client, "_authenticated_page", authenticated_page)
    context_spy = AsyncMock(side_effect=AssertionError("must never open ANY browser page for a known-empty one"))
    monkeypatch.setattr(client, "_context", context_spy)

    result = await client.get_video_transcript("_1189334_1", "_2_1")

    assert result is None


@pytest.mark.asyncio
async def test_cached_positive_uses_a_bare_page_never_the_authenticated_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A video already discovered skips the expensive, Blackboard-login-
    dependent navigation entirely — only a bare page scoped to Kaltura's own
    domain is opened for the (cheap, tokenless-of-Blackboard) caption fetch."""
    from blackboard_mcp import video_transcript_cache

    client = _client(tmp_path)
    video_transcript_cache.save_entry(
        tmp_path, "_1189334_1", "_2_1", has_video=True, entry_id="0_abc123", partner_id="1756931",
    )
    authenticated_page = AsyncMock(side_effect=AssertionError("must never open the Blackboard-authenticated page"))
    monkeypatch.setattr(client, "_authenticated_page", authenticated_page)
    fake_bare_page = AsyncMock()
    monkeypatch.setattr(client, "_context", AsyncMock(return_value=(AsyncMock(), AsyncMock(), True)))
    monkeypatch.setattr(client, "_page", AsyncMock(return_value=fake_bare_page))
    monkeypatch.setattr(client, "_close", AsyncMock())
    fetch = AsyncMock(return_value="fala do professor.")
    monkeypatch.setattr(client, "_fetch_transcript_from_kaltura", fetch)

    result = await client.get_video_transcript("_1189334_1", "_2_1")

    assert result == "fala do professor."
    fetch.assert_awaited_once_with(fake_bare_page, entry_id="0_abc123", partner_id="1756931")
    fake_bare_page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_discovery_of_a_real_video_saves_ids_to_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blackboard_mcp import video_transcript_cache

    client = _client(tmp_path)
    _mock_authenticated_page(monkeypatch, client)
    monkeypatch.setattr(client, "_discover_kaltura_ids", AsyncMock(return_value=("0_abc123", "1756931")))
    monkeypatch.setattr(client, "_fetch_transcript_from_kaltura", AsyncMock(return_value="fala do professor."))

    result = await client.get_video_transcript("_1189334_1", "_2_1")

    assert result == "fala do professor."
    entry = video_transcript_cache.get_entry(tmp_path, "_1189334_1", "_2_1")
    assert entry == {
        "has_video": True, "entry_id": "0_abc123", "partner_id": "1756931", "checked_at": entry["checked_at"],
    }


@pytest.mark.asyncio
async def test_full_discovery_of_no_video_saves_a_negative_cache_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check target: without this, a page confirmed empty today would
    be re-walked by every future run forever."""
    from blackboard_mcp import video_transcript_cache

    client = _client(tmp_path)
    _mock_authenticated_page(monkeypatch, client)
    monkeypatch.setattr(client, "_discover_kaltura_ids", AsyncMock(return_value=None))
    fetch = AsyncMock(side_effect=AssertionError("must never fetch captions when no video was found"))
    monkeypatch.setattr(client, "_fetch_transcript_from_kaltura", fetch)

    result = await client.get_video_transcript("_1189334_1", "_2_1")

    assert result is None
    entry = video_transcript_cache.get_entry(tmp_path, "_1189334_1", "_2_1")
    assert entry["has_video"] is False


@pytest.mark.asyncio
async def test_safe_wrapper_caches_a_failing_page_as_no_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check target: real incident (2026-09-04) — a page that always
    errors (institution bloat, unrelated to any lecture) was re-walked by
    Playwright on every single run forever, because an exception short-
    circuits `get_video_transcript` before it ever reaches its own cache
    write. `_get_video_transcript_safe` has to write the cache itself."""
    from blackboard_mcp import video_transcript_cache

    client = _client(tmp_path)
    monkeypatch.setattr(
        client, "get_video_transcript",
        AsyncMock(side_effect=TimeoutError("APIRequestContext.post: Timeout 30000ms exceeded.")),
    )

    result = await client._get_video_transcript_safe("_1189334_1", "_2_1")

    assert result is None
    entry = video_transcript_cache.get_entry(tmp_path, "_1189334_1", "_2_1")
    assert entry["has_video"] is False


@pytest.mark.asyncio
async def test_safe_wrapper_still_lets_a_real_programming_bug_surface(tmp_path: Path) -> None:
    """`_get_video_transcript_safe` degrades operational failures (timeouts,
    broken pages) — it must not also hide a genuine `ValueError` from a
    malformed id, which would be a real bug in the caller."""
    client = _client(tmp_path)
    with pytest.raises(ValueError, match="content_id invalido"):
        await client._get_video_transcript_safe("_1189334_1", "not-an-id")


@pytest.mark.asyncio
async def test_get_video_transcript_rejects_invalid_ids(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with pytest.raises(ValueError, match="course_id invalido"):
        await client.get_video_transcript("bad", "_1_1")
    with pytest.raises(ValueError, match="content_id invalido"):
        await client.get_video_transcript("_1_1", "bad")
