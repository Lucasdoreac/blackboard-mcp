"""Revisão de uma tentativa JÁ respondida — questões, resposta dada e gabarito.

Medido ao vivo (2026-09-14, 151 notas com tentativa em 36 disciplinas, 508
questões): `GET /gradebook/attempts/{id}?columnId=&expand=toolAttemptDetail`
devolve, por questão (`questionAttempts[]`), o enunciado, as alternativas na
ordem exibida, `givenAnswer` (1 booleano por alternativa), `correct`/
`partiallyCorrect` e `automatedFeedback`. Quando o professor libera o gabarito
(`isCorrectAnswersVisible`), cada alternativa traz `correctAnswer` — 231 das
411 de múltipla escolha. Sem liberação, o gabarito fica `None`: nunca se infere
certo pela resposta dada.

Puro: recebe o JSON e reusa o texto/anexos de `assessment_detail`.
"""

from __future__ import annotations

from typing import Any

from .assessment_detail import _raw, extract_instructions

ANSWERED_STATUSES = frozenset({"COMPLETED", "NEEDS_GRADING"})
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _option_rows(question: dict[str, Any], given: Any, visible: bool, base_url: str) -> list[dict[str, Any]]:
    rows = []
    marks = given if isinstance(given, list) else []
    for index, answer in enumerate(question.get("answers") or []):
        text, _ = extract_instructions(_raw(answer.get("answerText")), base_url)
        correct = answer.get("correctAnswer") if visible and isinstance(answer.get("correctAnswer"), bool) else None
        rows.append({
            "letter": _LETTERS[index] if index < len(_LETTERS) else str(index + 1),
            "text": text,
            "chosen": bool(marks[index]) if index < len(marks) and isinstance(marks[index], bool) else False,
            "correct": correct,
        })
    return rows


def parse_reviewed_attempt(attempt: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    """Tentativa respondida → questões com resposta e gabarito; None se não é
    avaliação respondida (em andamento, trabalho sem questões, outro tipo)."""
    if str(attempt.get("status") or "") not in ANSWERED_STATUSES:
        return None
    detail = (attempt.get("toolAttemptDetail") or {}).get("resource/x-bb-assessment") or {}
    question_attempts = detail.get("questionAttempts") or []
    if not question_attempts:
        return None
    questions = []
    for position, qa in enumerate(question_attempts, start=1):
        question = qa.get("question") or {}
        visible = bool(qa.get("isCorrectAnswersVisible"))
        text, attachments = extract_instructions(_raw(question.get("questionText")), base_url)
        given = qa.get("givenAnswer")
        feedback, _ = extract_instructions(_raw(qa.get("automatedFeedback")), base_url) if qa.get("isFeedbackVisible") else ("", [])
        questions.append({
            "number": qa.get("visibleQuestionNumber") or position,
            "question_id": str(qa.get("questionId") or question.get("id") or ""),
            "type": str(qa.get("questionType") or question.get("questionType") or ""),
            "text": text,
            "attachments": [{k: v for k, v in a.items() if not k.startswith("_")} for a in attachments],
            "options": _option_rows(question, given, visible, base_url),
            "given_text": given if isinstance(given, str) else None,
            "answer_key_visible": visible,
            "result": (
                None if not qa.get("isResultVisible")
                else "correct" if qa.get("correct") else "partial" if qa.get("partiallyCorrect") else "incorrect"
            ),
            "feedback": feedback,
            "points": question.get("points"),
        })
    assessment = detail.get("assessment") or {}
    return {
        "attempt_id": str(attempt.get("id") or ""),
        "status": str(attempt.get("status") or ""),
        "attempt_date": str(attempt.get("attemptDate") or ""),
        "title": str(assessment.get("title") or ""),
        "questions": questions,
    }


def attempt_ids_from_grade(grade: dict[str, Any]) -> list[str]:
    """Tentativas de uma nota, sem repetir (first/last/highest podem coincidir)."""
    seen: list[str] = []
    for key in ("firstAttemptId", "highestAttemptId", "lastAttemptId"):
        value = grade.get(key)
        if value and value not in seen:
            seen.append(str(value))
    return seen


__all__ = ["ANSWERED_STATUSES", "attempt_ids_from_grade", "parse_reviewed_attempt"]
