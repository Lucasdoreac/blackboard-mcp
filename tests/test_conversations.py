"""Aba Mensagens — leitura: quem ensina e o que já foi conversado.

Medido em 2026-09-17 na conta do dono. O achado contraintuitivo que estes
testes travam: **quem é professor só a API PÚBLICA conta**. A interna devolve
papel `'S'` e nenhum nome, então um leitor construído sobre ela mostraria
destinatário em branco.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.conversations import (
    can_write,
    parse_conversation,
    parse_conversations,
    parse_instructors,
)

BASE = "https://bb.example.edu"
CURSO = "_1169578_1"

# Formato REAL da API pública (2026-09-17): 55 Student, 1 Instructor.
USUARIOS = {"results": [
    {"userId": "_3937056_1", "courseRoleId": "Student",
     "user": {"id": "_3937056_1", "name": {"given": "Lucas", "family": "Dórea Cardoso"}}},
    {"userId": "_3853586_1", "courseRoleId": "Instructor",
     "user": {"id": "_3853586_1", "userName": "flavia",
              "name": {"given": "Flavia", "family": "Maria Alves Lopes"}}},
]}

# Formato REAL da interna: conversa com mensagem cujo corpo é HTML.
CONVERSA = {
    "id": "_6523228_1", "courseId": CURSO, "creatorId": "_3937056_1",
    "createdDate": "2026-08-11T00:31:18.383Z", "updatedDate": "2026-08-11T00:31:18.383Z",
    "participantIds": ["_3937056_1", "_3853586_1"], "canBeRepliedTo": True,
    "unreadCount": 0, "totalCount": 2,
    "messages": [
        {"id": "_2_1", "conversationId": "_6523228_1", "postDate": "2026-08-12T10:00:00Z",
         "isRead": True, "senderId": "_3853586_1",
         "sender": {"id": "_3853586_1", "givenName": "Flavia", "familyName": "Maria Alves Lopes"},
         "body": {"rawText": "<p>Recebi, obrigada.</p>"}},
        {"id": "_1_1", "conversationId": "_6523228_1", "postDate": "2026-08-11T00:31:18Z",
         "isRead": True, "senderId": "_3937056_1",
         "sender": {"id": "_3937056_1", "givenName": "Lucas", "familyName": "Dórea Cardoso"},
         "body": {"rawText": "<p>Professora, segue a análise.</p>"}},
    ],
}


def test_only_the_public_api_shape_reveals_who_teaches() -> None:
    """A interna devolve `'S'` sem nome; um leitor sobre ela não acharia ninguém."""
    professores = parse_instructors(USUARIOS)
    assert [p["id"] for p in professores] == ["_3853586_1"]
    assert professores[0]["name"] == "Flavia Maria Alves Lopes"
    assert professores[0]["role"] == "Instructor"

    interna = {"results": [{"userId": "_3853586_1", "courseRoleId": "S"}]}
    assert parse_instructors(interna) == [], "papel 'S' da interna nao identifica professor"


def test_students_are_never_listed_as_teachers() -> None:
    """Anti-oco: se o filtro caísse, o dono mandaria mensagem para a turma toda
    achando que falava com a professora."""
    assert all(p["role"] != "Student" for p in parse_instructors(USUARIOS))
    so_alunos = {"results": [u for u in USUARIOS["results"] if u["courseRoleId"] == "Student"]}
    assert parse_instructors(so_alunos) == []


def test_message_html_becomes_readable_text() -> None:
    conversa = parse_conversation(CONVERSA, BASE)
    assert conversa is not None
    assert [m["text"] for m in conversa["messages"]] == [
        "Professora, segue a análise.", "Recebi, obrigada."
    ], "em ordem de postagem, e sem HTML"


def test_sender_name_survives_the_internal_payload_shape() -> None:
    """A interna usa `givenName`/`familyName`; a pública usa `name.given`.
    Um leitor que só entenda um dos dois mostra remetente em branco."""
    conversa = parse_conversation(CONVERSA, BASE)
    assert conversa["messages"][1]["sender"]["name"] == "Flavia Maria Alves Lopes"


def test_conversations_come_newest_first() -> None:
    velha = {**CONVERSA, "id": "_1_1", "updatedDate": "2026-01-01T00:00:00Z"}
    lista = parse_conversations({"results": [velha, CONVERSA]}, BASE)
    assert [c["id"] for c in lista] == ["_6523228_1", "_1_1"]


def test_can_write_reads_the_permission_the_api_gives() -> None:
    assert can_write({"permissions": {"create": True}}) is True
    assert can_write({"permissions": {"create": False}}) is False
    assert can_write({}) is False, "sem permissao declarada, nao se promete envio"


def test_parser_is_not_hollow() -> None:
    for lixo in (None, {}, {"results": None}, "texto", []):
        assert parse_conversations(lixo, BASE) == []
        assert parse_instructors(lixo) == []
    assert parse_conversation({"courseId": CURSO}, BASE) is None, "conversa sem id nao existe"


def _client(tmp_path: Path, resposta: dict) -> tuple[BlackboardClient, AsyncMock]:
    cliente = BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))
    espiao = AsyncMock(return_value=resposta)
    cliente._rest_get = espiao  # type: ignore[assignment]
    return cliente, espiao


@pytest.mark.asyncio
async def test_list_instructors_uses_the_public_api(tmp_path: Path) -> None:
    cliente, espiao = _client(tmp_path, USUARIOS)
    professores = await cliente.list_instructors(CURSO)
    assert professores[0]["name"] == "Flavia Maria Alves Lopes"
    caminho = str(espiao.await_args_list[0].args[0])
    assert "/public/v1/" in caminho, "a interna nao expoe o papel; tem que ser a publica"


@pytest.mark.asyncio
async def test_reading_messages_never_writes(tmp_path: Path) -> None:
    """Esta entrega é de LEITURA. O envio virá com portão próprio; até lá,
    nenhum caminho daqui pode escrever na caixa de outra pessoa."""
    cliente, espiao = _client(tmp_path, {"permissions": {"create": True}, "results": [CONVERSA]})
    saida = await cliente.list_conversations(CURSO)
    assert saida["can_send"] is True
    assert saida["conversations"][0]["id"] == "_6523228_1"
    await cliente.read_conversation(CURSO, "_6523228_1")
    # `_rest_get` é o único verbo usado; escrita vive noutra classe.
    assert espiao.await_count == 2
    assert not hasattr(cliente, "_rest_post")
