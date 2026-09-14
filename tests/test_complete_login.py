"""`blackboard-mcp login` no formato do `nlm login` (2026-09-14).

Antes, `login` só abria o Chrome e saía: nada esperava o dono, nada gravava
`session.json` — o cookie só era capturado no primeiro comando que precisasse
do Blackboard, e só se a janela seguisse aberta. No mesmo dia o dono parou no
portal da instituição achando que já estava logado, e nada avisou.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from blackboard_mcp import client as client_mod
from blackboard_mcp.client import BlackboardClient, login_stage
from blackboard_mcp.config import Settings
from blackboard_mcp.session import SessionStale, session_path

BASE = "https://bb.example.edu"
PORTAL = "https://portal.example.edu/gfa/home?token=segredo"
ULTRA = f"{BASE}/ultra/course"
COOKIES = [{"name": "BbRouter", "value": "expires:9,xsrf:novo,timeout:28800"}]


def test_stage_is_blackboard_once_a_tab_reaches_ultra_on_the_configured_host() -> None:
    assert login_stage([PORTAL, ULTRA], BASE) == ("blackboard", "bb.example.edu")


def test_stage_flags_the_portal_and_returns_only_the_host() -> None:
    """O caso real: logado no portal, nunca no Blackboard. O token da URL de
    SSO não pode vazar para o terminal — só o host sai."""
    assert login_stage([PORTAL, "chrome://newtab/"], BASE) == ("other_host", "portal.example.edu")


def test_stage_on_the_blackboard_host_outside_ultra_is_still_waiting() -> None:
    """Sessão vencida redireciona para `/?new_loc=...` no MESMO host — isso é
    login em andamento, não outro site."""
    assert login_stage([f"{BASE}/?new_loc=%2Fultra%2Fcourse", "about:blank"], BASE) == ("waiting", None)


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))


def _fake_playwright(monkeypatch: pytest.MonkeyPatch, url_sequence: list[list[str]]) -> AsyncMock:
    """CDP falso cujas abas avançam uma posição da sequência a cada poll."""
    polls = iter(url_sequence)
    context = MagicMock()
    context.cookies = AsyncMock(return_value=COOKIES)
    type(context).pages = property(lambda _self: [SimpleNamespace(url=u) for u in next(polls)])
    browser = MagicMock()
    browser.is_connected.return_value = True
    browser.contexts = [context]
    playwright = AsyncMock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=browser)
    starter = MagicMock()
    starter.start = AsyncMock(return_value=playwright)
    monkeypatch.setattr(client_mod, "async_playwright", lambda: starter)
    return playwright


@pytest.mark.asyncio
async def test_login_waits_past_the_portal_then_saves_a_proven_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check: sem `complete_login`, `session.json` não existe ao fim do
    `login` — era exatamente o estado de antes."""
    client = _client(tmp_path)
    playwright = _fake_playwright(monkeypatch, [[PORTAL], [PORTAL], [ULTRA]])
    probed: list[str] = []

    async def fake_get(self, path, params=None, *, _retry_after_reload=True):
        probed.append(path)
        return {"id": "me"}

    monkeypatch.setattr(client_mod.BlackboardSession, "get", fake_get)
    progress: list[str] = []

    result = await client.complete_login(timeout_s=5, interval_s=0, on_progress=progress.append)

    assert result == {"authenticated": True, "profile": "sober", "session_saved": True}
    saved = json.loads(session_path(tmp_path, "sober").read_text(encoding="utf-8"))
    assert saved["xsrf"] == "novo"
    assert probed == ["/learn/api/v1/users/me"]
    assert len([m for m in progress if "portal.example.edu" in m]) == 1  # avisa uma vez, não a cada poll
    assert all("segredo" not in m for m in progress)
    playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_cookie_never_overwrites_the_saved_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aba em /ultra por instantes antes do redirect de sessão vencida: o cookie
    é recusado por REST, e o `session.json` existente não pode ser trocado por
    ele — a prova roda num jar descartável."""
    alvo = session_path(tmp_path, "sober")
    alvo.parent.mkdir(parents=True)
    alvo.write_text(json.dumps({"cookies": {"BbRouter": "expires:1,xsrf:antigo"}, "xsrf": "antigo"}), encoding="utf-8")
    client = _client(tmp_path)
    _fake_playwright(monkeypatch, [[ULTRA]] * 1000)

    async def rejecting_get(self, path, params=None, *, _retry_after_reload=True):
        raise SessionStale("401")

    monkeypatch.setattr(client_mod.BlackboardSession, "get", rejecting_get)

    result = await client.complete_login(timeout_s=0.05, interval_s=0.001)

    assert result["authenticated"] is False and result["reason"] == "login_timeout"
    assert json.loads(alvo.read_text(encoding="utf-8"))["xsrf"] == "antigo"


@pytest.mark.asyncio
async def test_keeps_waiting_while_chrome_is_not_reachable_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O Chrome recém-aberto demora a expor a porta CDP; falha de conexão é
    espera, não erro."""
    client = _client(tmp_path)
    playwright = _fake_playwright(monkeypatch, [[ULTRA]])
    browser = playwright.chromium.connect_over_cdp.return_value
    playwright.chromium.connect_over_cdp = AsyncMock(side_effect=[ConnectionError("ainda subindo"), browser])

    async def fake_get(self, path, params=None, *, _retry_after_reload=True):
        return {"id": "me"}

    monkeypatch.setattr(client_mod.BlackboardSession, "get", fake_get)

    result = await client.complete_login(timeout_s=5, interval_s=0)

    assert result["authenticated"] is True
    assert playwright.chromium.connect_over_cdp.await_count == 2
