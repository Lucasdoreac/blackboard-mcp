"""Aba Mensagens — leitura: quem ensina e o que já foi conversado.

Medido em 2026-09-17 na conta do dono. O achado contraintuitivo que estes
testes travam: **quem é professor só a API PÚBLICA conta**. A interna devolve
papel `'S'` e nenhum nome, então um leitor construído sobre ela mostraria
destinatário em branco.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
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


def test_the_class_code_never_leaks_into_the_person_name() -> None:
    """Medido na conta real: esta instituição guarda a TURMA em `familyName` e
    o nome completo em `givenName`. Concatenar produzia
    "Lucas Dórea Cardoso UDF_Ciência da Computação (Bacharelado)_6N1_20262".
    O próprio payload avisa qual usar, em `preferredDisplayName`."""
    from blackboard_mcp.conversations import parse_message

    bruto = {
        "id": "_1_1", "postDate": "2026-08-11T00:47:00Z",
        "sender": {"id": "_3937056_1", "givenName": "Lucas Dórea Cardoso",
                   "familyName": "UDF_Ciência da Computação (Bacharelado)_6N1_20262",
                   "preferredDisplayName": "GIVEN_NAME"},
        "body": {"rawText": "<p>oi</p>"},
    }
    assert parse_message(bruto, BASE)["sender"]["name"] == "Lucas Dórea Cardoso"


def test_a_normal_split_name_still_joins_both_parts() -> None:
    """Anti-oco: sem a preferência declarada, sobrenome de verdade não some."""
    from blackboard_mcp.conversations import parse_message

    bruto = {
        "id": "_2_1", "postDate": "2026-08-11T00:47:00Z",
        "sender": {"id": "_9_1", "givenName": "Flavia", "familyName": "Maria Alves Lopes"},
        "body": {"rawText": "<p>oi</p>"},
    }
    assert parse_message(bruto, BASE)["sender"]["name"] == "Flavia Maria Alves Lopes"


def test_attachment_names_use_the_key_the_extractor_produces() -> None:
    """O extrator devolve `file_name`. Procurar `name`/`fileName` mostra `None`
    — foi o que a primeira prova ao vivo fez, e o defeito era do script, não
    da biblioteca."""
    from blackboard_mcp.conversations import parse_message

    html_anexo = (
        '<p><a href="/bbcswebdav/x.docx" data-bbtype="attachment" '
        'data-bbfile="{&quot;fileName&quot;:&quot;Analise.docx&quot;}">Analise.docx</a></p>'
    )
    msg = parse_message({"id": "_3_1", "postDate": "2026-08-11T00:47:00Z",
                         "body": {"rawText": html_anexo}}, BASE)
    assert [a["file_name"] for a in msg["attachments"]] == ["Analise.docx"]


# --- Envio de mensagem --------------------------------------------------------
#
# Portão mais estrito que o do `submit_assignment`: lá o conteúdo era um PDF já
# revisado pelo dono e o efeito era só dele. Aqui o texto costuma ser REDIGIDO
# por um modelo e vai para a caixa de OUTRA pessoa, com o nome do dono.

def _writer_espiao(monkeypatch) -> list[tuple[str, Any]]:
    from blackboard_mcp.submitting import MessageWriter

    chamadas: list[tuple[str, Any]] = []

    async def start_conversation(self, course_id, recipient_ids, texto):  # noqa: ANN001
        chamadas.append(("start_conversation", tuple(recipient_ids)))
        return {"id": "_nova_1"}

    async def reply(self, course_id, conversation_id, texto):  # noqa: ANN001
        chamadas.append(("reply", conversation_id))
        return {"id": "_msg_1"}

    monkeypatch.setattr(MessageWriter, "start_conversation", start_conversation)
    monkeypatch.setattr(MessageWriter, "reply", reply)
    return chamadas


def _cliente_msg(tmp_path: Path, monkeypatch, conversas_depois: list[dict] | None = None):
    cliente = BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))
    cliente.list_instructors = AsyncMock(return_value=[  # type: ignore[assignment]
        {"id": "_3853586_1", "name": "Flavia Maria Alves Lopes", "role": "Instructor"}
    ])
    cliente.list_conversations = AsyncMock(return_value={  # type: ignore[assignment]
        "conversations": conversas_depois if conversas_depois is not None else [{"id": "_nova_1"}]
    })
    return cliente


@pytest.mark.asyncio
async def test_a_message_is_never_sent_without_confirmation(tmp_path: Path, monkeypatch) -> None:
    """O preview existe para ser LIDO antes. Um texto escrito por modelo indo
    para a professora sem o dono ver é risco de outra natureza."""
    chamadas = _writer_espiao(monkeypatch)
    cliente = _cliente_msg(tmp_path, monkeypatch)
    saida = await cliente.send_course_message(
        CURSO, "Professora, boa noite.", recipient_ids=["_3853586_1"]
    )
    assert chamadas == [], "nada sai sem confirm"
    assert saida["preview"] is True and saida["sent"] is False
    assert saida["text"] == "Professora, boa noite."
    assert saida["recipients"][0]["name"] == "Flavia Maria Alves Lopes", "quem recebe vem por NOME"


@pytest.mark.asyncio
async def test_with_confirmation_it_opens_the_conversation(tmp_path: Path, monkeypatch) -> None:
    chamadas = _writer_espiao(monkeypatch)
    cliente = _cliente_msg(tmp_path, monkeypatch)
    saida = await cliente.send_course_message(
        CURSO, "Segue a atividade.", recipient_ids=["_3853586_1"], confirm=True
    )
    assert chamadas == [("start_conversation", ("_3853586_1",))]
    assert saida["sent"] is True and saida["conversation_id"] == "_nova_1"


@pytest.mark.asyncio
async def test_sent_is_read_back_not_taken_from_the_write(tmp_path: Path, monkeypatch) -> None:
    """Anti-oco: a escrita devolveu um id, mas se a conversa não aparece na
    listagem, `sent` é False. Acreditar em quem escreveu é verde oco."""
    _writer_espiao(monkeypatch)
    cliente = _cliente_msg(tmp_path, monkeypatch, conversas_depois=[])
    saida = await cliente.send_course_message(
        CURSO, "oi", recipient_ids=["_3853586_1"], confirm=True
    )
    assert saida["conversation_id"] == "_nova_1"
    assert saida["sent"] is False, "o leitor nao achou a conversa — vale o leitor"


@pytest.mark.asyncio
async def test_new_and_reply_are_mutually_exclusive(tmp_path: Path, monkeypatch) -> None:
    from blackboard_mcp.submitting import SubmissionError

    chamadas = _writer_espiao(monkeypatch)
    cliente = _cliente_msg(tmp_path, monkeypatch)
    for kwargs in ({}, {"recipient_ids": ["_1_1"], "conversation_id": "_2_1"}):
        with pytest.raises(SubmissionError, match="UM"):
            await cliente.send_course_message(CURSO, "oi", confirm=True, **kwargs)
    assert chamadas == []


@pytest.mark.asyncio
async def test_an_unknown_recipient_is_flagged_not_hidden(tmp_path: Path, monkeypatch) -> None:
    """Se o id não é do corpo docente, o preview diz isso — mandar para a turma
    achando que fala com a professora é o erro caro aqui."""
    _writer_espiao(monkeypatch)
    cliente = _cliente_msg(tmp_path, monkeypatch)
    saida = await cliente.send_course_message(CURSO, "oi", recipient_ids=["_desconhecido_1"])
    assert "fora do corpo docente" in saida["recipients"][0]["name"]


def test_message_body_escapes_what_the_model_wrote() -> None:
    """Texto de modelo nunca injeta marcação na caixa de outra pessoa."""
    from blackboard_mcp.submitting import SubmissionError, message_body

    corpo = message_body("Oi <b>prof</b>\n\nsegue <script>alert(1)</script>")
    assert "<script>" not in corpo["rawText"]
    assert "&lt;script&gt;" in corpo["rawText"]
    assert corpo["rawText"].count("<p>") == 2, "paragrafo em branco vira <p>, o resto e escapado"
    for vazio in ("", "   ", "\n\n"):
        with pytest.raises(SubmissionError):
            message_body(vazio)
