"""Recarga da sessão do disco — o que faltava para o login externo curar a
bridge em execução (achado ao vivo 2026-09-05)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from blackboard_mcp.session import BlackboardSession, SessionStale, session_path


def _grava_sessao(tmp_path: Path, bbrouter: str) -> None:
    alvo = session_path(tmp_path, "sober")
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(json.dumps({
        "cookies": {"BbRouter": bbrouter}, "xsrf": bbrouter.split("xsrf:")[1].split(",")[0],
    }), encoding="utf-8")


def test_reload_picks_up_a_login_made_by_another_process(tmp_path: Path) -> None:
    """A bridge carrega a sessão UMA vez, no __init__. Sem recarga, o
    `blackboard-mcp login` feito por fora não cura o processo vivo — foi o que
    manteve a bridge de 10:02 inútil até 13:25."""
    _grava_sessao(tmp_path, "expires:1,xsrf:velho,timeout:28800")
    sessao = BlackboardSession("https://bb.example.edu", tmp_path, "sober")
    assert sessao._xsrf == "velho"

    _grava_sessao(tmp_path, "expires:2,xsrf:novo,timeout:28800")   # login por fora
    assert sessao.reload_from_disk() is True
    assert sessao._xsrf == "novo"


def test_reload_is_false_when_disk_has_nothing_new(tmp_path: Path) -> None:
    """Sem cookie novo, a recarga não pode dizer que trouxe algo — senão o
    caminho de retry viraria laço contra um 401 legítimo."""
    _grava_sessao(tmp_path, "expires:1,xsrf:igual,timeout:28800")
    sessao = BlackboardSession("https://bb.example.edu", tmp_path, "sober")
    assert sessao.reload_from_disk() is False


def test_reload_is_false_when_there_is_no_session_file(tmp_path: Path) -> None:
    sessao = BlackboardSession("https://bb.example.edu", tmp_path, "sober")
    assert sessao.configured is False
    assert sessao.reload_from_disk() is False


@pytest.mark.asyncio
async def test_unconfigured_session_reloads_before_giving_up(tmp_path: Path, monkeypatch) -> None:
    """Bridge que subiu ANTES do primeiro login: `configured` é False e a
    mensagem 'faca login' é definitiva. Com a recarga, o login posterior é
    encontrado sem reiniciar o processo."""
    sessao = BlackboardSession("https://bb.example.edu", tmp_path, "sober")
    with pytest.raises(SessionStale):
        await sessao.get("/learn/api/v1/qualquer")

    _grava_sessao(tmp_path, "expires:9,xsrf:depoisdologin,timeout:28800")
    chamadas: list[str] = []

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        def json(self) -> dict:  # noqa: D102
            return {"ok": True}

    class _Client:
        def __init__(self, **kw) -> None: ...
        async def __aenter__(self):  # noqa: D105
            return self
        async def __aexit__(self, *a) -> None:  # noqa: D105
            return None
        async def get(self, path, params=None, headers=None):  # noqa: D102
            chamadas.append(headers.get("X-Blackboard-XSRF", ""))
            return _Resp()

    monkeypatch.setattr("blackboard_mcp.session.httpx.AsyncClient", _Client)
    monkeypatch.setattr("blackboard_mcp.session.BlackboardSession._absorb_rotated_cookies",
                        lambda self, r: None)

    assert await sessao.get("/learn/api/v1/qualquer") == {"ok": True}
    assert chamadas == ["depoisdologin"]
