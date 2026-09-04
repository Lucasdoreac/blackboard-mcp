"""`BlackboardClient._authenticated_page` cleanup on failure.

Real incident (2026-09-04): a stale SSO session made every subsequent call
into this method fail (`_require_base_url` raising `AuthenticationRequired`)
— and the PAGE each failed attempt had just opened was never closed. With
`attached=True` (CDP-attached to a real, externally-managed Chrome — the
only mode that works against this institution's SSO; headless is bounced to
login), `_close()` deliberately never closes the shared context, so nothing
else was going to close that tab either. 15 orphaned tabs accumulated in the
owner's own visible browser window before anyone noticed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import AuthenticationRequired, BlackboardClient
from blackboard_mcp.config import Settings


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", data_home=tmp_path))


@pytest.mark.asyncio
async def test_closes_the_page_it_opened_when_the_session_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    fake_page = AsyncMock()
    fake_page.url = "https://bb.example.com/?new_loc=%2Fultra%2Fcourse"
    fake_playwright, fake_context = AsyncMock(), AsyncMock()

    monkeypatch.setattr(client, "_context", AsyncMock(return_value=(fake_playwright, fake_context, True)))
    monkeypatch.setattr(client, "_page", AsyncMock(return_value=fake_page))
    monkeypatch.setattr(client, "_open_course", AsyncMock())  # navigation itself "succeeds"
    close_spy = AsyncMock()
    monkeypatch.setattr(client, "_close", close_spy)

    with pytest.raises(AuthenticationRequired):
        await client._authenticated_page()

    fake_page.close.assert_awaited_once()
    close_spy.assert_awaited_once_with(fake_playwright, fake_context, attached=True)


@pytest.mark.asyncio
async def test_never_closes_the_page_on_the_success_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check counterpart: the caller owns the page on success and
    closes it itself — `_authenticated_page` closing it too would be a
    double-close on every healthy call, not just the failing one."""
    client = BlackboardClient(Settings(profile="sober", data_home=tmp_path, base_url="https://bb.example.com"))
    fake_page = AsyncMock()
    fake_page.url = "https://bb.example.com/ultra/course"
    fake_playwright, fake_context = AsyncMock(), AsyncMock()

    monkeypatch.setattr(client, "_context", AsyncMock(return_value=(fake_playwright, fake_context, True)))
    monkeypatch.setattr(client, "_page", AsyncMock(return_value=fake_page))
    monkeypatch.setattr(client, "_open_course", AsyncMock())

    result = await client._authenticated_page()

    assert result == (fake_playwright, fake_context, fake_page, True)
    fake_page.close.assert_not_awaited()
