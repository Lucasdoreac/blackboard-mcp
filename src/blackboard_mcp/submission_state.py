"""Estado de entrega de uma atividade — quantas tentativas foram usadas e se já foi enviada.

Por que existe (2026-09-16): o `list_assessments` declara que não infere estado
de entrega, e essa frase passou a ser lida como "o Blackboard não expõe isso".
Não é verdade. O que não se infere é o estado A PARTIR DA LISTAGEM; o diário de
classe devolve as tentativas de cada coluna, e elas dizem exatamente o que
aconteceu.

Contrato MEDIDO na conta do dono (2026-09-16), disciplina `_1169578_1`:

    GET /learn/api/v1/courses/{curso}/gradebook/columns/{coluna}/attempts
    -> {"lookup": {"<attemptId>": [ {...}, ... ]}, "permissions": {...}}

Cada tentativa traz `status`, `attemptDate`, `displayGrade`, `exempt` e
`studentSubmission`. Seis atividades entregues apareceram com
`status="NEEDS_GRADING"`; as não entregues vieram com `lookup` vazio.

**`permissions.createAttempt` é `false` até nas colunas que o dono JÁ entregou.**
Ou seja: aquele campo não diz se dá para enviar, e não pode ser lido como tal —
é a permissão do diário de classe, não a do aluno. O envio do aluno passa por
outra rota, ainda não mapeada.

Módulo PURO: recebe o JSON e devolve o estado. Quem busca é o `client`.
"""

from __future__ import annotations

from typing import Any

# Tentativa ENTREGUE. `IN_PROGRESS` fica de fora de propósito: é tentativa
# começada e não enviada, que é justamente o estado que o dono precisa ver como
# "ainda falta" — tratá-la como entrega é o erro caro deste módulo.
SUBMITTED_STATUSES = frozenset({"NEEDS_GRADING", "COMPLETED", "IN_PROGRESS_AGAIN"})
IN_PROGRESS_STATUSES = frozenset({"IN_PROGRESS"})


def _attempts(payload: Any) -> list[dict[str, Any]]:
    """Achata o `lookup`: cada chave guarda uma LISTA de tentativas, não uma."""
    lookup = payload.get("lookup") if isinstance(payload, dict) else None
    if not isinstance(lookup, dict):
        return []
    saida: list[dict[str, Any]] = []
    for valor in lookup.values():
        for item in valor if isinstance(valor, list) else [valor]:
            if isinstance(item, dict):
                saida.append(item)
    return saida


def _file_names(attempt: dict[str, Any]) -> list[str]:
    """Nomes dos ANEXOS. Eles vivem em `studentSubmissionFiles[]`, não dentro de
    `studentSubmission` — este é o envio de TEXTO (`rawText`/`displayText`), e a
    atividade aceita os dois. Medido em 2026-09-16: a primeira versão procurava
    em `studentSubmission.files` e devolvia lista vazia para uma tentativa que
    tinha dois PDFs anexados."""
    arquivos = attempt.get("studentSubmissionFiles")
    if not isinstance(arquivos, list):
        return []
    nomes = []
    for arquivo in arquivos:
        if not isinstance(arquivo, dict):
            continue
        nome = (
            (arquivo.get("file") or {}).get("fileName")
            or arquivo.get("name")
            or arquivo.get("linkName")
        )
        if nome:
            nomes.append(str(nome))
    return nomes


def _submitted_text(attempt: dict[str, Any]) -> str:
    envio = attempt.get("studentSubmission")
    if not isinstance(envio, dict):
        return ""
    return str(envio.get("displayText") or envio.get("rawText") or "").strip()


def parse_submission_state(payload: Any, *, attempts_allowed: int | None = None) -> dict[str, Any]:
    """Estado de entrega a partir da resposta do diário de classe.

    `submitted` é sobre TENTATIVA ENVIADA, nunca sobre existir tentativa: uma
    `IN_PROGRESS` conta como começada e não entregue.
    """
    tentativas = _attempts(payload)
    # Mais recente primeiro: `attemptDate` é ISO-8601 em UTC, ordenável como texto.
    ordenadas = sorted(tentativas, key=lambda t: str(t.get("attemptDate") or ""), reverse=True)
    enviadas = [t for t in ordenadas if str(t.get("status") or "") in SUBMITTED_STATUSES]
    em_andamento = [t for t in ordenadas if str(t.get("status") or "") in IN_PROGRESS_STATUSES]
    ultima = ordenadas[0] if ordenadas else None

    restantes: int | None = None
    if isinstance(attempts_allowed, int) and attempts_allowed > 0:
        restantes = max(attempts_allowed - len(enviadas), 0)

    return {
        "submitted": bool(enviadas),
        "in_progress": bool(em_andamento),
        "attempts_used": len(enviadas),
        "attempts_allowed": attempts_allowed,
        "attempts_left": restantes,
        "latest_status": str(ultima.get("status")) if ultima and ultima.get("status") else None,
        "latest_at": str(ultima.get("attemptDate")) if ultima and ultima.get("attemptDate") else None,
        "grade": str(ultima.get("displayGrade")) if ultima and ultima.get("displayGrade") else None,
        "files": _file_names(ultima) if ultima else [],
        "has_text": bool(_submitted_text(ultima)) if ultima else False,
    }


__all__ = ["IN_PROGRESS_STATUSES", "SUBMITTED_STATUSES", "parse_submission_state"]
