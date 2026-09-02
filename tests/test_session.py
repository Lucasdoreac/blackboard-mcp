import json
from pathlib import Path

import httpx
import pytest

import blackboard_mcp.session as session_module
from blackboard_mcp.session import BlackboardSession, SessionStale, extract_xsrf


def test_extract_xsrf_parses_the_bbrouter_field() -> None:
    value = "expires:1788328401,id:abc,timeout:28800,xsrf:bd2085f0-d355-4c85-a4ab-8af9ef16a3f2"
    assert extract_xsrf(value) == "bd2085f0-d355-4c85-a4ab-8af9ef16a3f2"


def test_extract_xsrf_returns_none_when_absent() -> None:
    assert extract_xsrf("expires:1,id:abc,timeout:28800") is None


def _fresh_session(tmp_path: Path) -> BlackboardSession:
    return BlackboardSession("https://bb.example.edu", tmp_path, "sober")


def _mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_client_cls = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(session_module.httpx, "AsyncClient", fake_async_client)


def test_adopt_persists_cookies_and_extracted_xsrf(tmp_path: Path) -> None:
    session = _fresh_session(tmp_path)
    session.adopt([
        {"name": "BbRouter", "value": "expires:1,id:x,timeout:28800,xsrf:the-xsrf"},
        {"name": "JSESSIONID", "value": "j1"},
    ])
    assert session.configured is True
    on_disk = json.loads((tmp_path / "profiles" / "sober" / "session.json").read_text())
    assert on_disk["cookies"]["BbRouter"].endswith("xsrf:the-xsrf")
    assert on_disk["xsrf"] == "the-xsrf"


def test_adopt_without_bbrouter_raises_session_stale(tmp_path: Path) -> None:
    with pytest.raises(SessionStale):
        _fresh_session(tmp_path).adopt([{"name": "JSESSIONID", "value": "j1"}])


def test_reloading_from_disk_recovers_the_same_session(tmp_path: Path) -> None:
    first = _fresh_session(tmp_path)
    first.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:tok"}])
    second = _fresh_session(tmp_path)
    assert second.configured is True


@pytest.mark.asyncio
async def test_get_raises_session_stale_without_prior_login(tmp_path: Path) -> None:
    with pytest.raises(SessionStale):
        await _fresh_session(tmp_path).get("/learn/api/v1/users/me")


@pytest.mark.asyncio
async def test_get_sends_xsrf_header_and_returns_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _fresh_session(tmp_path)
    session.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:the-xsrf"}])

    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["xsrf"] = request.headers.get("x-blackboard-xsrf")
        captured["requested_with"] = request.headers.get("x-requested-with")
        return httpx.Response(200, json={"id": "_1_1"}, headers={"content-type": "application/json"})

    _mock_transport(monkeypatch, handler)
    body = await session.get("/learn/api/v1/users/me")

    assert body == {"id": "_1_1"}
    assert captured["xsrf"] == "the-xsrf"
    assert captured["requested_with"] == "XMLHttpRequest"


@pytest.mark.asyncio
async def test_get_raises_session_stale_on_401(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _fresh_session(tmp_path)
    session.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:tok"}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    _mock_transport(monkeypatch, handler)
    with pytest.raises(SessionStale):
        await session.get("/learn/api/v1/users/me")


@pytest.mark.asyncio
async def test_get_persists_rotated_bbrouter_cookie_from_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Revert-check target: without persisting Set-Cookie rotation, the
    keep-alive ping renews the session only in memory — a bridge restart
    would silently lose the renewal and the session would go stale sooner
    than Blackboard's own 8h inactivity window actually allows."""
    session = _fresh_session(tmp_path)
    session.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:old-xsrf"}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"ok": True},
            headers=[
                ("content-type", "application/json"),
                ("set-cookie", "BbRouter=expires:2,timeout:28800,xsrf:new-xsrf; Path=/; Secure; HttpOnly"),
            ],
        )

    _mock_transport(monkeypatch, handler)
    await session.get("/learn/api/v1/utilities/timeUntilBbSessionInactive")

    on_disk = json.loads((tmp_path / "profiles" / "sober" / "session.json").read_text())
    assert on_disk["xsrf"] == "new-xsrf"
    assert "expires:2" in on_disk["cookies"]["BbRouter"]
