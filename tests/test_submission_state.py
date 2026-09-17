"""`submission_status`: já foi entregue, e quantas tentativas sobraram.

O que este arquivo trava é uma afirmação FALSA que circulava: "o Blackboard não
expõe estado de entrega". A descrição do `list_assessments` diz que ele não
INFERE estado — e isso virou, por leitura apressada, "não dá para saber". Dá: o
diário de classe devolve as tentativas de cada coluna.

Contrato medido na conta do dono (2026-09-16, disciplina `_1169578_1`): seis
atividades entregues com `status="NEEDS_GRADING"`, duas não entregues com
`lookup` vazio.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.submission_state import parse_submission_state

BASE = "https://bb.example.edu"
CURSO, CONTEUDO, COLUNA = "_1169578_1", "_23732596_1", "_5253447_1"


def _entregue(attempt_id: str, quando: str, arquivos: list[str] | None = None) -> dict:
    return {
        "id": attempt_id,
        "status": "NEEDS_GRADING",
        "attemptDate": quando,
        "displayGrade": None,
        "studentSubmission": {
            "files": [{"name": n, "linkName": n, "file": {"fileName": n}} for n in (arquivos or [])]
        },
    }


def test_no_attempt_means_not_submitted() -> None:
    estado = parse_submission_state({"lookup": {}, "permissions": {}}, attempts_allowed=2)
    assert estado["submitted"] is False
    assert estado["attempts_used"] == 0
    assert estado["attempts_left"] == 2
    assert estado["latest_status"] is None


def test_a_submitted_attempt_is_counted_with_its_files() -> None:
    payload = {"lookup": {"_203186459_1": [
        _entregue("_203186459_1", "2026-08-11T00:31:42.419Z", ["Dijkstra_Lucas_Dorea.pdf", "dijkstra_lucas.c"])
    ]}}
    estado = parse_submission_state(payload, attempts_allowed=2)
    assert estado["submitted"] is True
    assert estado["attempts_used"] == 1
    assert estado["attempts_left"] == 1
    assert estado["latest_status"] == "NEEDS_GRADING"
    assert estado["files"] == ["Dijkstra_Lucas_Dorea.pdf", "dijkstra_lucas.c"]


def test_an_attempt_in_progress_is_not_a_submission() -> None:
    """O erro caro deste módulo seria contar tentativa ABERTA como entregue: o
    dono relaxaria achando que enviou, e o prazo passaria com a tentativa
    parada. `late_attempts_blocked` é `true` na Atividade 09 — não há depois."""
    payload = {"lookup": {"_9_1": [{"id": "_9_1", "status": "IN_PROGRESS", "attemptDate": "2026-09-20T22:00:00Z"}]}}
    estado = parse_submission_state(payload, attempts_allowed=2)
    assert estado["submitted"] is False
    assert estado["in_progress"] is True
    assert estado["attempts_used"] == 0
    assert estado["attempts_left"] == 2


def test_the_latest_attempt_wins_regardless_of_lookup_order() -> None:
    payload = {"lookup": {
        "_1_1": [_entregue("_1_1", "2026-08-01T10:00:00Z", ["velho.pdf"])],
        "_2_1": [_entregue("_2_1", "2026-09-10T10:00:00Z", ["novo.pdf"])],
    }}
    estado = parse_submission_state(payload, attempts_allowed=2)
    assert estado["attempts_used"] == 2
    assert estado["attempts_left"] == 0
    assert estado["files"] == ["novo.pdf"], "a última tentativa é a que descreve o estado"


def test_parser_is_not_hollow() -> None:
    """Sem `lookup` utilizável nada é afirmado — e `attempts_left` não inventa
    número quando o limite é desconhecido."""
    for lixo in (None, {}, {"lookup": None}, {"lookup": []}, "texto"):
        estado = parse_submission_state(lixo)
        assert estado["submitted"] is False and estado["attempts_used"] == 0
        assert estado["attempts_left"] is None


def _client(tmp_path: Path, colunas: list[dict], tentativas: dict) -> tuple[BlackboardClient, AsyncMock]:
    client = BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))

    async def rest_get(path: str, params: dict | None = None):
        if path.endswith("/gradebook/columns"):
            return {"results": colunas}
        if path.endswith("/attempts"):
            return tentativas
        raise AssertionError(f"GET inesperado: {path}")

    espiao = AsyncMock(side_effect=rest_get)
    client._rest_get = espiao  # type: ignore[assignment]
    client._assessment_detail = AsyncMock(  # type: ignore[assignment]
        return_value={"title": "09 - Complexidade do Caixeiro Viajante",
                      "due_at": "2026-09-21T02:59:00.000Z", "attempts_allowed": 2}
    )
    return client, espiao


@pytest.mark.asyncio
async def test_status_resolves_the_column_by_content_id(tmp_path: Path) -> None:
    """A coluna sai da LISTA, casando `contentId`. O caminho do
    `read_open_attempt` (`resource/x-bb-asmt-test-link`) só existe em PROVA, e
    a Atividade 09 é `Assignment` — por ali ela não resolveria coluna nenhuma."""
    colunas = [
        {"id": "_1_1", "contentId": "_outro_1", "effectiveColumnName": "Outra"},
        {"id": COLUNA, "contentId": CONTEUDO, "effectiveColumnName": "09 - Complexidade"},
    ]
    client, espiao = _client(tmp_path, colunas, {"lookup": {}})
    estado = await client.submission_status(CURSO, CONTEUDO)
    assert estado["column_id"] == COLUNA and estado["known"] is True
    assert estado["submitted"] is False and estado["attempts_allowed"] == 2
    assert any(COLUNA in str(c.args[0]) for c in espiao.await_args_list), "consultou a coluna certa"


@pytest.mark.asyncio
async def test_without_a_column_it_says_it_does_not_know(tmp_path: Path) -> None:
    """Anti-oco: sem coluna, `known=False`. Devolver "não entregue" seria pior
    que não responder — o dono relaxaria com uma confirmação que ninguém deu."""
    client, _ = _client(tmp_path, [{"id": "_1_1", "contentId": "_outro_1"}], {"lookup": {}})
    estado = await client.submission_status(CURSO, CONTEUDO)
    assert estado["known"] is False
    assert "submitted" not in estado, "sem coluna não se afirma estado nenhum"


@pytest.mark.asyncio
async def test_status_never_writes(tmp_path: Path) -> None:
    """A tool é de LEITURA. Se algum dia alguém a fizer abrir tentativa, esta
    guarda cai: só `_rest_get` pode ser usado."""
    client, espiao = _client(tmp_path, [{"id": COLUNA, "contentId": CONTEUDO}], {"lookup": {}})
    await client.submission_status(CURSO, CONTEUDO)
    assert espiao.await_count >= 1
    assert not hasattr(client, "_rest_post"), "o cliente não tem caminho de escrita"
