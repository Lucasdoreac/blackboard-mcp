"""`BlackboardClient._fetch_transcript_from_kaltura` sends a `Referer`.

Real incident (2026-09-04): `caption_captionasset::list`/`serveWebVTT` answer
`200 OK` but with an EMPTY caption list / empty VTT playlist when the request
carries no `Referer` for the institution's own Blackboard domain — no error,
just silent degradation (Kaltura's access-control is domain-based, checked at
the CDN edge). `page.request` is Playwright's APIRequestContext, which never
auto-sets `Referer` to the page's current URL the way an in-page `fetch()`
would — this was mistaken for a session-privilege issue for hours before a
live network capture of the real player proved it was the missing header.
Confirmed live: a bare domain (no course/content path) is enough.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings

_READY_CAPTION = {
    "id": "1_capid", "status": 2, "isDefault": True, "objectType": "KalturaCaptionAsset",
}


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", data_home=tmp_path, base_url="https://bb.example.com"))


def _fake_json_response(payload: object) -> AsyncMock:
    resp = AsyncMock()
    resp.ok = True
    resp.json = AsyncMock(return_value=payload)
    resp.text = AsyncMock(return_value="")
    return resp


def _fake_text_response(text: str) -> AsyncMock:
    resp = AsyncMock()
    resp.ok = True
    resp.text = AsyncMock(return_value=text)
    return resp


@pytest.mark.asyncio
async def test_every_kaltura_request_carries_a_referer_for_our_own_domain(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = AsyncMock()
    page.request.post = AsyncMock(
        return_value=_fake_json_response([{"ks": "kstoken"}, {"objects": [_READY_CAPTION]}])
    )
    page.request.get = AsyncMock(
        side_effect=[
            _fake_text_response("#EXTM3U\nsegmentIndex/1.vtt\n"),
            _fake_text_response("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nola"),
        ]
    )

    transcript = await client._fetch_transcript_from_kaltura(page, entry_id="1_entry", partner_id="42")

    assert transcript == "ola"
    post_call = page.request.post.call_args
    assert post_call.kwargs["headers"] == {"Referer": "https://bb.example.com/"}
    for get_call in page.request.get.call_args_list:
        assert get_call.kwargs["headers"] == {"Referer": "https://bb.example.com/"}


@pytest.mark.asyncio
async def test_revert_check_missing_referer_would_go_unnoticed_by_status_alone(tmp_path: Path) -> None:
    """Documents the real failure shape: Kaltura degrades to EMPTY content
    with a 200 OK, never a non-2xx status — `response.ok` alone can never
    catch this class of bug, only asserting the header itself can."""
    client = _client(tmp_path)
    page = AsyncMock()
    page.request.post = AsyncMock(
        return_value=_fake_json_response([{"ks": "kstoken"}, {"objects": [_READY_CAPTION]}])
    )
    page.request.get = AsyncMock(return_value=_fake_text_response(""))

    transcript = await client._fetch_transcript_from_kaltura(page, entry_id="1_entry", partner_id="42")

    assert transcript is None
