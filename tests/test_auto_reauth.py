"""Reautenticação automática e a separação recusa × sessão morta (2026-09-14).

Incidente do dia: uma leitura com 403 comum (sem permissão) caía no refresh
oculto via browser, que regravou `session.json` com cookie não provado e
derrubou a sessão. O dono resolveu com `ssh ubuntu` + `blackboard-mcp login` —
que agora é o fallback automático.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from blackboard_mcp import session as session_module
from blackboard_mcp.client import AuthenticationRequired, BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.session import BlackboardRequestRejected, BlackboardSession, SessionStale

BASE = "https://bb.example.edu"


def _session(tmp_path: Path) -> BlackboardSession:
    s = BlackboardSession(BASE, tmp_path, "sober")
    s.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:tok"}])
    return s


def _transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = httpx.AsyncClient

    def fake(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(session_module.httpx, "AsyncClient", fake)


@pytest.mark.asyncio
async def test_403_with_a_live_session_is_a_rejected_operation_not_an_expired_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check: com o `get` antigo, este 403 virava SessionStale e
    disparava o refresh via browser que derrubou a sessão."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/learn/api/v1/users/me":
            return httpx.Response(200, json={"id": "_1_1"})
        return httpx.Response(403, json={"status": 403})

    _transport(monkeypatch, handler)
    with pytest.raises(BlackboardRequestRejected) as exc:
        await _session(tmp_path).get("/learn/api/v1/courses/_9_1/gradebook/columns/_8_1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_403_when_users_me_also_fails_is_an_expired_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _transport(monkeypatch, lambda req: httpx.Response(403, text="<html>login</html>"))
    with pytest.raises(SessionStale):
        await _session(tmp_path).get("/learn/api/v1/courses/_9_1/contents")


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))


@pytest.mark.asyncio
async def test_expired_session_reauthenticates_once_and_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    get = AsyncMock(side_effect=[SessionStale("401"), {"ok": True}])
    monkeypatch.setattr(client._session, "get", get)
    reauth = AsyncMock(return_value={"authenticated": True})
    monkeypatch.setattr(client, "reauthenticate", reauth)
    assert await client._rest_get("/learn/api/v1/x") == {"ok": True}
    reauth.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_operation_never_triggers_reauthentication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client._session, "get", AsyncMock(side_effect=BlackboardRequestRejected(403, "/x")))
    reauth = AsyncMock()
    monkeypatch.setattr(client, "reauthenticate", reauth)
    with pytest.raises(BlackboardRequestRejected):
        await client._rest_get("/x")
    reauth.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_automatic_login_tells_the_owner_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client._session, "get", AsyncMock(side_effect=SessionStale("401")))
    monkeypatch.setattr(client, "reauthenticate", AsyncMock(return_value={"authenticated": False, "needs_owner": True}))
    with pytest.raises(AuthenticationRequired, match="blackboard-mcp login --profile sober"):
        await client._rest_get("/x")


@pytest.mark.asyncio
async def test_reauthenticate_opens_the_window_only_when_chrome_is_down_and_waits_with_a_login_tab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client._session, "get", AsyncMock(side_effect=SessionStale("401")))
    monkeypatch.setattr(client, "_cdp_available", lambda: False)
    opened = MagicMock()
    monkeypatch.setattr(client, "open_login_window", opened)
    complete = AsyncMock(return_value={"authenticated": True, "profile": "sober", "session_saved": True})
    monkeypatch.setattr(client, "complete_login", complete)
    result = await client.reauthenticate(timeout_s=5)
    assert result["authenticated"] is True and result["recovered"] == "browser_sso"
    opened.assert_called_once()
    assert complete.await_args.kwargs == {"timeout_s": 5, "open_login_tab": True}


@pytest.mark.asyncio
async def test_reauthenticate_skips_the_browser_when_another_process_already_logged_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client._session, "get", AsyncMock(return_value={"id": "_1_1"}))
    complete = AsyncMock()
    monkeypatch.setattr(client, "complete_login", complete)
    assert (await client.reauthenticate())["recovered"] == "already_valid"
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_reauthentications_run_one_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client._session, "get", AsyncMock(side_effect=SessionStale("401")))
    monkeypatch.setattr(client, "_cdp_available", lambda: True)
    running = {"now": 0, "max": 0}

    async def slow_login(**kwargs):
        running["now"] += 1
        running["max"] = max(running["max"], running["now"])
        await asyncio.sleep(0.02)
        running["now"] -= 1
        return {"authenticated": False}

    monkeypatch.setattr(client, "complete_login", slow_login)
    await asyncio.gather(client.reauthenticate(), client.reauthenticate())
    assert running["max"] == 1
