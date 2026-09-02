from pathlib import Path

import pytest

from blackboard_mcp.bridge import KEEPALIVE_PATH, keepalive_ping
from blackboard_mcp.session import BlackboardSession


def _fresh_session(tmp_path: Path) -> BlackboardSession:
    return BlackboardSession("https://bb.example.edu", tmp_path, "sober")


@pytest.mark.asyncio
async def test_ping_is_a_noop_when_no_session_is_configured(tmp_path: Path) -> None:
    session = _fresh_session(tmp_path)
    assert await keepalive_ping(session) is False


@pytest.mark.asyncio
async def test_ping_calls_the_keepalive_endpoint_and_reports_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _fresh_session(tmp_path)
    session.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:tok"}])

    calls: list[tuple[str, dict | None]] = []

    async def fake_get(path: str, params: dict | None = None):
        calls.append((path, params))
        return {"timeBeforeTimeout": 28787130}

    monkeypatch.setattr(session, "get", fake_get)
    assert await keepalive_ping(session) is True
    assert calls == [(KEEPALIVE_PATH, {"forceLogout": "false"})]


@pytest.mark.asyncio
async def test_ping_swallows_session_stale_and_reports_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Revert-check target: without the try/except here, a genuinely expired
    session would crash the background keep-alive task (and, unhandled,
    silently kill the whole loop forever — the bridge would never try
    again). A real read afterwards is what should surface the clear
    re-login error to the owner, not this loop."""
    from blackboard_mcp.session import SessionStale

    session = _fresh_session(tmp_path)
    session.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:tok"}])

    async def fake_get(path: str, params: dict | None = None):
        raise SessionStale("rejected")

    monkeypatch.setattr(session, "get", fake_get)
    assert await keepalive_ping(session) is False


@pytest.mark.asyncio
async def test_ping_swallows_network_errors_and_reports_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _fresh_session(tmp_path)
    session.adopt([{"name": "BbRouter", "value": "expires:1,timeout:28800,xsrf:tok"}])

    async def fake_get(path: str, params: dict | None = None):
        raise RuntimeError("dns hiccup")

    monkeypatch.setattr(session, "get", fake_get)
    assert await keepalive_ping(session) is False
