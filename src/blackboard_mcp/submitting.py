"""Envio de atividade — a ÚNICA superfície de escrita do projeto.

O resto do `blackboard-mcp` lê. A escrita mora aqui, num objeto separado e
nomeado, de propósito: `BlackboardSession` continua sem `post`/`patch`, e o
teste que guarda isso (`test_read_open_attempt`) segue valendo sem ressalva.
Quem quiser saber se um caminho escreve olha o tipo que ele usa, não a
documentação.

CONTRATO MEDIDO (2026-09-17), observando um envio real na conta do dono. Não
foi deduzido nem lembrado — cada passo saiu de uma requisição capturada:

    1. POST  /learn/api/v1/files?expand=mimeType,isMedia          -> 201
             multipart/form-data
             devolve {webLocation, fileLocation, mimeType, fileName}

    2. POST  /learn/api/v1/courses/{curso}/gradebook/columns/{col}/attempts  -> 201
             {"studentSubmissionFiles":[{"file": <o objeto do passo 1>}]}
             devolve a tentativa, com `id`

    3. PATCH /learn/api/v1/courses/{curso}/gradebook/attempts/{id}           -> 200
             mesmo corpo — salva rascunho, NÃO envia

    4. PATCH /learn/api/v1/courses/{curso}/gradebook/attempts/{id}
             ?saveBeforeSubmitAndPost=true                                  -> 200
             {"status":"NEEDS_GRADING", ...}  <- ESTE é o envio

O passo 4 é irreversível e consome uma tentativa. Por isso `submit_attempt`
existe separado de `start_attempt`: quem monta o rascunho não envia por
acidente.

O que NÃO é adivinhado: a rota de upload é `/learn/api/v1/files`, e não
`/uploads` — este último foi tentado antes da captura e devolveu 404.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx

from .session import BlackboardRequestRejected, BlackboardSession, SessionStale

SUBMITTED_STATUS = "NEEDS_GRADING"
_TIMEOUT_S = 120.0
# Teto de tamanho do anexo. Não é regra do Blackboard — é para uma chamada não
# ficar pendurada minutos num arquivo que ninguém quis mandar.
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
# Teto de mensagem: o que não cabe aqui é anexo, não recado.
MAX_MESSAGE_CHARS = 20_000


class SubmissionError(RuntimeError):
    """Falha de envio com mensagem utilizável por quem lê."""


def file_part(caminho: Path) -> tuple[str, bytes, str]:
    """(nome, conteúdo, mimetype) do anexo, com o tipo derivado da extensão."""
    if not caminho.is_file():
        raise SubmissionError(f"arquivo nao encontrado: {caminho}")
    dados = caminho.read_bytes()
    if not dados:
        raise SubmissionError(f"arquivo vazio: {caminho}")
    if len(dados) > MAX_UPLOAD_BYTES:
        raise SubmissionError(f"arquivo grande demais ({len(dados)} bytes): {caminho}")
    tipo = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"
    return caminho.name, dados, tipo


def submission_files(handle: Any) -> list[dict[str, Any]]:
    """`studentSubmissionFiles` a partir do que o upload devolveu.

    Repassa o objeto do upload INTEIRO: ele carrega `webLocation` e
    `fileLocation`, e é esse par que o Blackboard usa para achar o arquivo. Um
    id sozinho não serve — foi o que a captura mostrou."""
    if not isinstance(handle, dict):
        raise SubmissionError("o upload nao devolveu um objeto de arquivo utilizavel")
    if not handle.get("fileLocation") and not handle.get("id"):
        raise SubmissionError(f"upload sem referencia de arquivo: {sorted(handle)[:8]}")
    return [{"file": handle}]


class SubmissionWriter:
    """Escreve no Blackboard reusando a sessão autenticada de leitura.

    Os cookies e o XSRF vêm do `BlackboardSession`; o que este objeto acrescenta
    é o verbo. Nenhum método aqui é chamado sem HITL a montante — ver
    `client.submit_assignment`."""

    def __init__(self, session: BlackboardSession) -> None:
        self._session = session

    def _headers(self) -> dict[str, str]:
        return {
            "X-Requested-With": "XMLHttpRequest",
            "X-Blackboard-XSRF": getattr(self._session, "_xsrf", "") or "",
            "Accept": "application/json, text/plain, */*",
        }

    async def _write(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._session.configured and not self._session.reload_from_disk():
            raise SessionStale("sessao nao configurada; faca login")
        async with httpx.AsyncClient(
            base_url=self._session.base_url,
            cookies=self._session._cookies,  # noqa: SLF001 — mesma sessão, outro verbo
            timeout=_TIMEOUT_S,
        ) as cliente:
            # SEM retry: repetir uma escrita pode criar tentativa em dobro, e
            # uma atividade tem número contado. Falha de rede aqui sobe.
            resposta = await cliente.request(method, path, headers=self._headers(), **kwargs)
        self._session._absorb_rotated_cookies(resposta)  # noqa: SLF001
        if resposta.status_code >= 400:
            if resposta.status_code == 401:
                raise SessionStale("a sessao Blackboard foi recusada (401)")
            raise BlackboardRequestRejected(resposta.status_code, f"{path} :: {resposta.text[:200]}")
        try:
            return resposta.json()
        except ValueError:
            return {}

    async def upload(self, caminho: Path) -> dict[str, Any]:
        """Passo 1 — sobe o arquivo e devolve o objeto que os passos seguintes citam."""
        nome, dados, tipo = file_part(caminho)
        devolvido = await self._write(
            "POST", "/learn/api/v1/files",
            params={"expand": "mimeType,isMedia"},
            files={"file": (nome, dados, tipo)},
        )
        if isinstance(devolvido, dict) and isinstance(devolvido.get("results"), list) and devolvido["results"]:
            devolvido = devolvido["results"][0]
        if not isinstance(devolvido, dict):
            raise SubmissionError("upload nao devolveu objeto de arquivo")
        return devolvido

    async def start_attempt(self, course_id: str, column_id: str, arquivos: list[dict[str, Any]]) -> dict[str, Any]:
        """Passo 2 — cria a tentativa com o anexo. NÃO envia."""
        return await self._write(
            "POST", f"/learn/api/v1/courses/{course_id}/gradebook/columns/{column_id}/attempts",
            json={"studentSubmissionFiles": arquivos},
        )

    async def save_draft(self, course_id: str, attempt_id: str, arquivos: list[dict[str, Any]],
                         texto: str = "") -> dict[str, Any]:
        """Passo 3 — salva rascunho. NÃO envia."""
        corpo: dict[str, Any] = {"studentSubmissionFiles": arquivos}
        if texto:
            corpo["studentSubmission"] = {"rawText": texto}
        return await self._write(
            "PATCH", f"/learn/api/v1/courses/{course_id}/gradebook/attempts/{attempt_id}",
            json=corpo,
        )

    async def submit_attempt(self, course_id: str, attempt_id: str, arquivos: list[dict[str, Any]],
                             texto: str = "") -> dict[str, Any]:
        """Passo 4 — ENVIA. Irreversível: consome uma tentativa.

        Separado de `save_draft` de propósito: montar o rascunho e entregar são
        decisões diferentes, e só a segunda é definitiva."""
        return await self._write(
            "PATCH", f"/learn/api/v1/courses/{course_id}/gradebook/attempts/{attempt_id}",
            params={"saveBeforeSubmitAndPost": "true"},
            json={
                "status": SUBMITTED_STATUS,
                "studentSubmission": {"rawText": texto},
                "studentSubmissionFiles": arquivos,
            },
        )


def message_body(texto: str) -> dict[str, str]:
    """Corpo de mensagem no formato que o Blackboard guarda (`rawText`, HTML).

    O texto do dono é ESCAPADO: um `<` digitado por engano não pode virar tag,
    e conteúdo vindo de modelo nunca injeta marcação na caixa de outra pessoa.
    Quebra de linha vira parágrafo, que é como a interface exibe."""
    import html as _html

    limpo = (texto or "").strip()
    if not limpo:
        raise SubmissionError("mensagem vazia — nao mando silencio para ninguem")
    if len(limpo) > MAX_MESSAGE_CHARS:
        raise SubmissionError(f"mensagem longa demais ({len(limpo)} chars)")
    paragrafos = [_html.escape(p.strip()) for p in limpo.split("\n\n") if p.strip()]
    # `displayText` vazio é o que a interface manda — medido, não suposto.
    return {"rawText": "".join(f"<p>{p}</p>" for p in paragrafos), "displayText": ""}


class MessageWriter(SubmissionWriter):
    """Cria conversa e responde na aba Mensagens.

    Herda o transporte de `SubmissionWriter` — mesma sessão, mesma ausência de
    retry — porque o motivo é o mesmo: repetir uma escrita pode duplicar, e
    mensagem duplicada na caixa de um professor não se desfaz.

    CONTRATO MEDIDO (2026-09-17), escutando o dono abrir uma conversa real com
    a professora pela interface do Ultra:

        POST /learn/api/v1/courses/{curso}/conversations
             ?sendEmailToParticipants=true                             -> 201
             {"participantIds": ["_3853586_1"],
              "messages": [{"body": {"rawText": "<p>…</p>", "displayText": ""}}],
              "canBeRepliedTo": true}

    A rota era a hipótese certa; o CORPO estava errado em três dos quatro
    campos. `includesAllMembers` foi invenção minha e não existe na requisição
    real; `canBeRepliedTo` e `displayText` faltavam; e o parâmetro de e-mail,
    que decide se o professor é NOTIFICADO, não estava em lugar nenhum — uma
    mensagem sem ele pode ficar numa caixa que ninguém abre.

    O `POST .../conversations/preview` que a interface faz antes
    (`{"participantIds": [...], "messageLimit": 20}`) é da tela, não do envio:
    carrega o histórico com aquela pessoa. Não é replicado aqui.

    `reply` continua NÃO MEDIDO — a captura cobriu abrir conversa, não
    responder numa existente. Está dito no método."""

    async def start_conversation(self, course_id: str, recipient_ids: list[str],
                                 texto: str, *, notify_by_email: bool = True) -> dict[str, Any]:
        """Abre conversa com o(s) destinatário(s). Corpo conforme medido.

        `notify_by_email` acompanha o que a interface faz: sem ele a mensagem
        entra na caixa do Blackboard sem avisar ninguém, e uma mensagem que o
        professor não vê é o mesmo que não ter mandado."""
        if not recipient_ids:
            raise SubmissionError("sem destinatario — nao mando mensagem para ninguem")
        return await self._write(
            "POST", f"/learn/api/v1/courses/{course_id}/conversations",
            params={"sendEmailToParticipants": "true" if notify_by_email else "false"},
            json={
                "participantIds": list(recipient_ids),
                "messages": [{"body": message_body(texto)}],
                "canBeRepliedTo": True,
            },
        )

    async def reply(self, course_id: str, conversation_id: str, texto: str) -> dict[str, Any]:
        """Responde numa conversa existente. **NÃO MEDIDO** (2026-09-17): a
        captura cobriu abrir conversa, não responder. A rota segue a simetria
        do resto da API interna e é a melhor hipótese — quem chamar primeiro
        confere por `list_conversations`, nunca pela resposta."""
        return await self._write(
            "POST", f"/learn/api/v1/courses/{course_id}/conversations/{conversation_id}/messages",
            json={"body": message_body(texto)},
        )


__all__ = [
    "MAX_MESSAGE_CHARS",
    "MessageWriter",
    "message_body",
    "MAX_UPLOAD_BYTES",
    "SUBMITTED_STATUS",
    "SubmissionError",
    "SubmissionWriter",
    "file_part",
    "submission_files",
]
