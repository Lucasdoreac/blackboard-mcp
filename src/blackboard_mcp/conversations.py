"""Aba Mensagens: quem são os professores e o que já foi conversado.

SÓ LEITURA. Enviar mensagem cria conteúdo na caixa de OUTRA pessoa, com a
identidade de quem manda, e não tem desfazer — fica para uma entrega própria,
com portão de confirmação, e não se mistura com o caminho de leitura.

Duas descobertas medidas em 2026-09-17, e a segunda é contraintuitiva:

1. As conversas vivem em `/learn/api/v1/courses/{curso}/conversations`, com
   `permissions: {"create": true, "delete": true, "edit": true}` — a API diz
   que o aluno PODE criar, ao contrário do diário de classe, onde
   `createAttempt` é `false` até nas atividades já entregues.

2. **Quem é professor só a API PÚBLICA conta.** A interna
   (`/learn/api/v1/courses/{c}/memberships`) devolve papel como `'S'` e sem
   nome nenhum — inútil para escolher destinatário. A pública
   (`/learn/api/public/v1/courses/{c}/users?expand=user`) devolve
   `courseRoleId: "Instructor"` com nome completo. Ou seja: a API que NÃO
   deixa escrever é a única que diz para quem escrever.

Módulo PURO: recebe o JSON e devolve estrutura. Quem busca é o `client`.
"""

from __future__ import annotations

from typing import Any

from .assessment_detail import _raw, extract_instructions

# `courseRoleId` de quem ENSINA. `Grader` entra porque também responde dúvida;
# `TeachingAssistant` idem. Aluno nunca.
TEACHING_ROLES = frozenset({"Instructor", "TeachingAssistant", "CourseBuilder", "Grader"})


def _person(user: Any, fallback_id: str = "") -> dict[str, Any]:
    """Nome legível + id de um usuário, seja qual for o formato do payload.

    A API pública traz `user.name.{given,family}`; a interna traz
    `sender.{givenName,familyName}`. Os dois aparecem, e um leitor que só
    entenda um deles mostra destinatário em branco na metade dos casos."""
    if not isinstance(user, dict):
        return {"id": fallback_id, "name": ""}
    nome = user.get("name")
    if isinstance(nome, dict):
        partes = [str(nome.get("given") or ""), str(nome.get("family") or "")]
    else:
        partes = [str(user.get("givenName") or ""), str(user.get("familyName") or "")]
    return {
        "id": str(user.get("id") or fallback_id or ""),
        "name": " ".join(p for p in partes if p).strip(),
        "username": str(user.get("userName") or ""),
    }


def parse_instructors(payload: Any) -> list[dict[str, Any]]:
    """Quem ENSINA a disciplina, a partir da listagem de usuários da API pública."""
    linhas = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(linhas, list):
        return []
    saida: list[dict[str, Any]] = []
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        papel = str(linha.get("courseRoleId") or "")
        if papel not in TEACHING_ROLES:
            continue
        pessoa = _person(linha.get("user"), str(linha.get("userId") or ""))
        if not pessoa["id"]:
            continue
        saida.append({**pessoa, "role": papel})
    return saida


def parse_message(message: Any, base_url: str) -> dict[str, Any] | None:
    """Uma mensagem: quem mandou, quando, e o TEXTO (o corpo vem em HTML)."""
    if not isinstance(message, dict):
        return None
    texto, anexos = extract_instructions(_raw(message.get("body")), base_url)
    return {
        "id": str(message.get("id") or ""),
        "conversation_id": str(message.get("conversationId") or ""),
        "sender": _person(message.get("sender"), str(message.get("senderId") or "")),
        "posted_at": str(message.get("postDate") or ""),
        "text": texto.strip(),
        "attachments": anexos,
        "read": bool(message.get("isRead")),
    }


def parse_conversation(conversa: Any, base_url: str) -> dict[str, Any] | None:
    """Uma conversa com suas mensagens em ordem de postagem."""
    if not isinstance(conversa, dict) or not conversa.get("id"):
        return None
    mensagens = [
        m for m in (parse_message(x, base_url) for x in (conversa.get("messages") or []))
        if m is not None
    ]
    mensagens.sort(key=lambda m: m["posted_at"])
    return {
        "id": str(conversa["id"]),
        "course_id": str(conversa.get("courseId") or ""),
        "created_at": str(conversa.get("createdDate") or ""),
        "updated_at": str(conversa.get("updatedDate") or ""),
        "creator_id": str(conversa.get("creatorId") or ""),
        "participant_ids": [str(x) for x in (conversa.get("participantIds") or [])],
        "includes_all_members": bool(conversa.get("includesAllMembers")),
        "can_reply": bool(conversa.get("canBeRepliedTo")),
        "unread": int(conversa.get("unreadCount") or 0),
        "total": int(conversa.get("totalCount") or len(mensagens)),
        "messages": mensagens,
    }


def parse_conversations(payload: Any, base_url: str) -> list[dict[str, Any]]:
    linhas = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(linhas, list):
        return []
    conversas = [c for c in (parse_conversation(x, base_url) for x in linhas) if c is not None]
    conversas.sort(key=lambda c: c["updated_at"] or c["created_at"], reverse=True)
    return conversas


def can_write(payload: Any) -> bool:
    """O que a API diz sobre criar conversa nesta disciplina.

    Informativo: nenhum caminho deste módulo escreve. Serve para o assistente
    saber, ANTES de oferecer, se mandar mensagem é possível aqui."""
    permissoes = payload.get("permissions") if isinstance(payload, dict) else None
    return bool(isinstance(permissoes, dict) and permissoes.get("create"))


__all__ = [
    "TEACHING_ROLES",
    "can_write",
    "parse_conversation",
    "parse_conversations",
    "parse_instructors",
    "parse_message",
]
