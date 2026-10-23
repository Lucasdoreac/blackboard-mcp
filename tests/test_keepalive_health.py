"""Keep-alive observável e recarga do disco sem restart (incidente 2026-10-20/23).

O cookie venceu em 2026-10-20 depois de 8 h sem ping bem-sucedido, sem
nenhum aviso. Em 2026-10-23 um session.json novo, copiado do Mac, só valeu
depois de `systemctl --user restart`: `auth_status` nunca relia o disco.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx
import pytest

from blackboard_mcp import bridge
from blackboard_mcp import session as session_module
from blackboard_mcp.bridge import KEEPALIVE_PATH, _keepalive_loop, keepalive_ping
from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.session import BlackboardSession, SessionStale, extract_expires, session_path

BASE = "https://bb.example.edu"
SEGREDO_VELHO = "segredo-velho-nao-logar"
SEGREDO_NOVO = "segredo-novo-nao-logar"


def _bbrouter(segredo: str, expires: float) -> str:
    return f"expires:{int(expires)},id:{segredo},timeout:28800,xsrf:{segredo}"


def _grava(tmp_path: Path, segredo: str, expires: float) -> None:
    alvo = session_path(tmp_path, "sober")
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(json.dumps({"cookies": {"BbRouter": _bbrouter(segredo, expires)}, "xsrf": segredo}),
                    encoding="utf-8")


def _blackboard_que_so_aceita(monkeypatch: pytest.MonkeyPatch, segredo: str, chamadas: list[str]) -> None:
    """Servidor falso: 200 só para o cookie `segredo`; 401 (com Set-Cookie) para o resto."""
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path)
        if f"id:{segredo}" in request.headers.get("cookie", ""):
            return httpx.Response(200, json={"id": "me"})
        return httpx.Response(401, json={"status": 401},
                              headers={"set-cookie": "BbRouter=expires:1,id:anonimo,xsrf:anonimo; Path=/"})

    def fake(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(session_module.httpx, "AsyncClient", fake)


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))


def test_extract_expires_reads_seconds_and_milliseconds() -> None:
    assert extract_expires("expires:1760990100,xsrf:x") == 1760990100
    assert extract_expires("expires:1760990100000,xsrf:x") == 1760990100
    assert extract_expires("xsrf:x") is None
    assert extract_expires("expires:abc") is None


@pytest.mark.asyncio
async def test_auth_status_uses_a_session_json_swapped_on_disk_without_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check: com `_retry_after_reload=False` em `auth_status` (ed916ed)
    a segunda chamada continua `authenticated: False` — o defeito de 2026-10-23."""
    _grava(tmp_path, SEGREDO_VELHO, time.time() - 60)
    client = _client(tmp_path)
    chamadas: list[str] = []
    _blackboard_que_so_aceita(monkeypatch, SEGREDO_NOVO, chamadas)

    assert (await client.auth_status())["authenticated"] is False

    _grava(tmp_path, SEGREDO_NOVO, time.time() + 8 * 3600)   # login no Mac, copiado para cá
    status = await client.auth_status()

    assert status["authenticated"] is True
    assert status["expires_at"] == pytest.approx(time.time() + 8 * 3600, abs=5)


@pytest.mark.asyncio
async def test_rejected_response_never_overwrites_a_fresh_session_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check: absorver o Set-Cookie de um 401 gravaria o jar velho por
    cima do session.json novo antes da recarga, e o login trazido de fora se
    perderia (hipótese de risco; o 401 real pode ou não trazer Set-Cookie)."""
    _grava(tmp_path, SEGREDO_VELHO, time.time() - 60)
    sessao = BlackboardSession(BASE, tmp_path, "sober")
    chamadas: list[str] = []
    _blackboard_que_so_aceita(monkeypatch, SEGREDO_NOVO, chamadas)

    _grava(tmp_path, SEGREDO_NOVO, time.time() + 8 * 3600)
    assert await sessao.get("/learn/api/v1/users/me") == {"id": "me"}

    disco = json.loads(session_path(tmp_path, "sober").read_text(encoding="utf-8"))
    assert f"id:{SEGREDO_NOVO}" in disco["cookies"]["BbRouter"]


@pytest.mark.asyncio
async def test_keepalive_failure_is_logged_with_class_and_remaining_time_but_no_cookie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _grava(tmp_path, SEGREDO_VELHO, time.time() + 90 * 60)
    sessao = BlackboardSession(BASE, tmp_path, "sober")

    async def rede_caiu(path, params=None):
        raise httpx.ConnectError("dns")

    monkeypatch.setattr(sessao, "get", rede_caiu)
    with caplog.at_level(logging.WARNING, logger="blackboard_mcp.keepalive"):
        assert await keepalive_ping(sessao) is False

    texto = caplog.text
    assert "classe=network" in texto and "ConnectError" in texto
    assert "sessao_restante=89min" in texto or "sessao_restante=90min" in texto
    assert SEGREDO_VELHO not in texto
    assert sessao.keepalive.consecutive_failures == 1
    assert sessao.keepalive.last_failure_class == "network"


@pytest.mark.asyncio
async def test_keepalive_classifies_a_rejected_session_and_resets_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _grava(tmp_path, SEGREDO_VELHO, time.time() + 6 * 3600)
    sessao = BlackboardSession(BASE, tmp_path, "sober")
    respostas: list[Exception | dict] = [SessionStale("401"), {"timeBeforeTimeout": 1}]

    async def get(path, params=None):
        assert path == KEEPALIVE_PATH
        resposta = respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr(sessao, "get", get)
    with caplog.at_level(logging.WARNING, logger="blackboard_mcp.keepalive"):
        assert await keepalive_ping(sessao) is False
        assert sessao.keepalive.last_failure_class == "session_stale"
        assert await keepalive_ping(sessao) is True

    assert sessao.keepalive.consecutive_failures == 0
    assert sessao.keepalive.last_ok_at == pytest.approx(time.time(), abs=5)
    assert "recuperado" in caplog.text


@pytest.mark.parametrize(
    ("restante_s", "falhas", "esperado"),
    [
        (90 * 60, 2, True),       # < 2 h e falhando: avisa
        (3 * 3600, 2, False),     # falhando, mas longe de vencer
        (90 * 60, 0, False),      # perto de vencer, mas os pings estão bons
        (-60, 1, True),           # já venceu e segue falhando
    ],
)
def test_keepalive_failing_needs_both_less_than_two_hours_and_failures(
    tmp_path: Path, restante_s: float, falhas: int, esperado: bool
) -> None:
    """Revert-check: trocar o `and` por `or` (ou tirar o limite de 2 h) faz os
    casos 'longe de vencer' ou 'pings bons' avisarem o dono à toa."""
    agora = 1_800_000_000.0
    _grava(tmp_path, SEGREDO_VELHO, agora + restante_s)
    sessao = BlackboardSession(BASE, tmp_path, "sober")
    sessao.keepalive.consecutive_failures = falhas
    assert sessao.keepalive_failing(agora) is esperado


@pytest.mark.asyncio
async def test_auth_status_exposes_the_keepalive_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _grava(tmp_path, SEGREDO_VELHO, time.time() + 30 * 60)
    client = _client(tmp_path)
    client.session.keepalive.consecutive_failures = 3
    client.session.keepalive.last_failure_class = "network"
    client.session.keepalive.last_ok_at = 123.0

    async def ok(path, params=None, **kw):
        return {"id": "me"}

    monkeypatch.setattr(client.session, "get", ok)
    status = await client.auth_status()

    assert status["authenticated"] is True
    assert status["keepalive_failing"] is True
    assert status["last_keepalive_ok_at"] == 123.0
    assert status["last_keepalive_failure_class"] == "network"
    assert SEGREDO_VELHO not in json.dumps(status)


@pytest.mark.asyncio
async def test_keepalive_loop_retries_after_300s_on_failure_and_returns_to_1200s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check: com o laço antigo (sempre `interval_s`) as esperas seriam
    [1200, 1200, 1200, 1200]."""
    sessao = BlackboardSession(BASE, tmp_path, "sober")
    resultados = [False, False, True]
    esperas: list[float] = []

    async def ping(_sessao):
        return resultados.pop(0)

    async def sleep(segundos):
        esperas.append(segundos)
        if len(esperas) > 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(bridge, "keepalive_ping", ping)
    monkeypatch.setattr(bridge.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await _keepalive_loop(sessao, 1200.0)

    assert esperas == [1200.0, 300.0, 300.0, 1200.0]
