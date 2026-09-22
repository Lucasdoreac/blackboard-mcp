"""Recovery distinguishes a missing browser from an owner-pending login."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.session import SessionStale


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", base_url="https://bb.example.edu", data_home=tmp_path))


@pytest.mark.asyncio
async def test_reauthenticate_reports_browser_launch_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client._session, "get", AsyncMock(side_effect=SessionStale("401")))
    monkeypatch.setattr(client, "_cdp_available", lambda: False)
    monkeypatch.setattr(client, "open_login_window", lambda: {"opened": False, "reason": "browser_launch_failed"})

    result = await client.reauthenticate()

    assert result == {
        "authenticated": False,
        "profile": "sober",
        "needs_owner": True,
        "reason": "browser_launch_failed",
    }


@pytest.mark.asyncio
async def test_reauthenticate_reports_unavailable_recovery_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client._session, "get", AsyncMock(side_effect=SessionStale("401")))
    monkeypatch.setattr(client, "_cdp_available", lambda: False)
    monkeypatch.setattr(client, "open_login_window", lambda: {"opened": True})
    monkeypatch.setattr(client, "_wait_for_recovery_browser", AsyncMock(return_value=False))

    result = await client.reauthenticate()

    assert result == {
        "authenticated": False,
        "profile": "sober",
        "needs_owner": True,
        "reason": "recovery_browser_unavailable",
    }
