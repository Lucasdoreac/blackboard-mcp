"""Envio de atividade: irreversível, então o portão vem antes da mecânica.

O contrato dos quatro passos foi MEDIDO observando um envio real em 2026-09-17
(ver `submitting.py`). O que este arquivo trava não é o formato — é que nada
saia sem confirmação, e que "enviado" só seja dito quando o Blackboard
confirmar pelo leitor, não pela resposta de quem escreveu.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.submitting import (
    SubmissionError,
    SubmissionWriter,
    file_part,
    submission_files,
)

BASE = "https://bb.example.edu"
CURSO, CONTEUDO, COLUNA = "_1169578_1", "_23732596_1", "_5253447_1"
# Objeto de arquivo como o upload real devolveu (captura de 2026-09-17).
ARQUIVO_DEVOLVIDO = {
    "isMedia": False,
    "webLocation": f"{BASE}/sessions/B5/ABC/def/",
    "fileLocation": "BB%3FBB_eOFUHVE%2BVer2/I4bfjqhF",
    "mimeType": "application/pdf",
    "fileName": "atividade.pdf",
}


def _pdf(tmp_path: Path) -> Path:
    caminho = tmp_path / "atividade.pdf"
    caminho.write_bytes(b"%PDF-1.7 conteudo de verdade")
    return caminho


def _client(tmp_path: Path, estado: dict[str, Any], depois: dict[str, Any] | None = None):
    cliente = BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))
    estados = [estado, depois if depois is not None else estado]
    cliente.submission_status = AsyncMock(side_effect=estados)  # type: ignore[assignment]
    return cliente


def _writer_espiao(monkeypatch, tentativa_id: str = "_9_1") -> list[tuple[str, Any]]:
    """Registra os passos de escrita sem falar com rede nenhuma."""
    chamadas: list[tuple[str, Any]] = []

    async def upload(self, caminho):  # noqa: ANN001
        chamadas.append(("upload", caminho.name))
        return dict(ARQUIVO_DEVOLVIDO)

    async def start_attempt(self, course_id, column_id, arquivos):  # noqa: ANN001
        chamadas.append(("start_attempt", column_id))
        return {"id": tentativa_id, "status": "IN_PROGRESS"}

    async def submit_attempt(self, course_id, attempt_id, arquivos, texto=""):  # noqa: ANN001
        chamadas.append(("submit_attempt", attempt_id))
        return {"id": attempt_id, "status": "NEEDS_GRADING"}

    monkeypatch.setattr(SubmissionWriter, "upload", upload)
    monkeypatch.setattr(SubmissionWriter, "start_attempt", start_attempt)
    monkeypatch.setattr(SubmissionWriter, "submit_attempt", submit_attempt)
    return chamadas


PENDENTE = {"known": True, "submitted": False, "attempts_left": 2, "attempts_used": 0,
            "column_id": COLUNA, "title": "09", "due_at": "2026-09-21T02:59:00.000Z"}
ENVIADO = {"known": True, "submitted": True, "attempts_left": 1, "attempts_used": 1,
           "column_id": COLUNA, "title": "09", "files": ["atividade.pdf"]}


@pytest.mark.asyncio
async def test_without_confirmation_nothing_is_written(tmp_path: Path, monkeypatch) -> None:
    """O portão que o dono pediu: "sempre com minha confirmação explícita antes
    de cada envio". Ele tem que ser INERTE por omissão — quem esquece o
    parâmetro não entrega por acidente."""
    chamadas = _writer_espiao(monkeypatch)
    cliente = _client(tmp_path, PENDENTE)
    saida = await cliente.submit_assignment(CURSO, CONTEUDO, str(_pdf(tmp_path)))

    assert chamadas == [], "nenhuma escrita sem confirm"
    assert saida["preview"] is True and saida["submitted"] is False
    assert "confirm=true" in saida["warning"]
    # O plano mostra o que seria consumido, para a decisão ser informada.
    assert saida["attempts_left"] == 2 and saida["file"]["name"] == "atividade.pdf"


@pytest.mark.asyncio
async def test_with_confirmation_the_three_steps_run_in_order(tmp_path: Path, monkeypatch) -> None:
    chamadas = _writer_espiao(monkeypatch)
    cliente = _client(tmp_path, PENDENTE, ENVIADO)
    saida = await cliente.submit_assignment(CURSO, CONTEUDO, str(_pdf(tmp_path)), confirm=True)

    assert [c[0] for c in chamadas] == ["upload", "start_attempt", "submit_attempt"]
    assert chamadas[1][1] == COLUNA, "a tentativa nasce na coluna resolvida pelo leitor"
    assert saida["submitted"] is True and saida["attempts_left"] == 1
    assert saida["preview"] is False


@pytest.mark.asyncio
async def test_success_is_read_back_not_taken_from_the_write(tmp_path: Path, monkeypatch) -> None:
    """Anti-oco: mesmo o PATCH devolvendo `NEEDS_GRADING`, se o leitor disser
    que não entrou, `submitted` é False. Acreditar em quem escreveu é como se
    declara verde oco."""
    _writer_espiao(monkeypatch)
    nao_entrou = {**PENDENTE, "submitted": False, "attempts_left": 2}
    cliente = _client(tmp_path, PENDENTE, nao_entrou)
    saida = await cliente.submit_assignment(CURSO, CONTEUDO, str(_pdf(tmp_path)), confirm=True)

    assert saida["status"] == "NEEDS_GRADING", "a escrita disse que deu certo"
    assert saida["submitted"] is False, "e o leitor desmentiu — vale o leitor"


@pytest.mark.asyncio
async def test_no_attempts_left_refuses_before_writing(tmp_path: Path, monkeypatch) -> None:
    chamadas = _writer_espiao(monkeypatch)
    cliente = _client(tmp_path, {**PENDENTE, "attempts_left": 0, "attempts_used": 2})
    with pytest.raises(SubmissionError, match="tentativa"):
        await cliente.submit_assignment(CURSO, CONTEUDO, str(_pdf(tmp_path)), confirm=True)
    assert chamadas == []


@pytest.mark.asyncio
async def test_unknown_state_refuses_instead_of_guessing(tmp_path: Path, monkeypatch) -> None:
    """Sem conseguir CONFERIR a entrega, não se envia: o resultado seria um
    envio que ninguém sabe se entrou."""
    chamadas = _writer_espiao(monkeypatch)
    cliente = _client(tmp_path, {"known": False})
    with pytest.raises(SubmissionError):
        await cliente.submit_assignment(CURSO, CONTEUDO, str(_pdf(tmp_path)), confirm=True)
    assert chamadas == []


@pytest.mark.asyncio
async def test_a_bad_file_is_caught_before_any_write(tmp_path: Path, monkeypatch) -> None:
    """Validar o anexo DEPOIS de abrir a tentativa deixaria uma tentativa
    queimada por causa de um caminho errado."""
    chamadas = _writer_espiao(monkeypatch)
    cliente = _client(tmp_path, PENDENTE)
    vazio = tmp_path / "vazio.pdf"
    vazio.write_bytes(b"")
    with pytest.raises(SubmissionError):
        await cliente.submit_assignment(CURSO, CONTEUDO, str(vazio), confirm=True)
    with pytest.raises(SubmissionError):
        await cliente.submit_assignment(CURSO, CONTEUDO, str(tmp_path / "nao_existe.pdf"), confirm=True)
    assert chamadas == []


def test_file_part_derives_the_mimetype(tmp_path: Path) -> None:
    nome, dados, tipo = file_part(_pdf(tmp_path))
    assert nome == "atividade.pdf" and tipo == "application/pdf" and dados.startswith(b"%PDF")


def test_submission_files_forwards_the_whole_upload_object() -> None:
    """A captura mostrou que o Blackboard acha o arquivo por `webLocation` +
    `fileLocation`. Reduzir o objeto a um id quebraria o envio."""
    arquivos = submission_files(dict(ARQUIVO_DEVOLVIDO))
    assert arquivos == [{"file": ARQUIVO_DEVOLVIDO}]
    assert arquivos[0]["file"]["fileLocation"].startswith("BB%3F")


def test_submission_files_refuses_an_upload_without_a_reference() -> None:
    """Anti-oco: se o upload voltar sem referência, parar aqui é melhor que
    criar tentativa com anexo que o servidor não resolve."""
    for lixo in ({}, {"mimeType": "application/pdf"}, "texto", None):
        with pytest.raises(SubmissionError):
            submission_files(lixo)
