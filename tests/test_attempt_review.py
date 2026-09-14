"""Revisão de tentativa respondida — formato medido ao vivo em 2026-09-14
(Circuitos Lógicos 2024.2: `correctAnswer` por alternativa, `givenAnswer`
booleano, `partiallyCorrect`, `automatedFeedback`)."""

from __future__ import annotations

from blackboard_mcp.attempt_review import attempt_ids_from_grade, parse_reviewed_attempt

BASE = "https://bb.example.edu"


def _answer(text: str, correct: bool) -> dict:
    return {"answerText": {"rawText": f"<p>{text}</p>"}, "correctAnswer": correct, "id": text}


def _attempt(status: str = "COMPLETED", visible: bool = True) -> dict:
    return {
        "id": "_7_1", "status": status, "attemptDate": "2024-10-01T12:00:00.000Z",
        "toolAttemptDetail": {"resource/x-bb-assessment": {
            "assessment": {"title": "AS - Unidade II"},
            "questionAttempts": [{
                "questionType": "multipleanswer", "questionId": "_19244024_1", "visibleQuestionNumber": 1,
                "givenAnswer": [False, False, False, True, False],
                "isCorrectAnswersVisible": visible, "isResultVisible": True, "isFeedbackVisible": True,
                "correct": False, "partiallyCorrect": True,
                "automatedFeedback": {"rawText": "<p>Circuitos lógicos operam dados binários.</p>"},
                "question": {"questionText": {"rawText": "<p>Analise as asserções.</p>"}, "points": 0.075, "answers": [
                    _answer("I e II falsas", False), _answer("I verdadeira", False), _answer("II verdadeira", False),
                    _answer("I e II verdadeiras e II justifica I", True), _answer("I e II verdadeiras", False),
                ]},
            }],
        }},
    }


def test_answered_attempt_carries_given_answer_answer_key_result_and_feedback() -> None:
    review = parse_reviewed_attempt(_attempt(), BASE)
    q = review["questions"][0]
    assert review["title"] == "AS - Unidade II" and q["text"] == "Analise as asserções."
    assert [o["letter"] for o in q["options"] if o["chosen"]] == ["D"]
    assert [o["letter"] for o in q["options"] if o["correct"]] == ["D"]
    assert q["result"] == "partial" and "binários" in q["feedback"]


def test_hidden_answer_key_is_none_never_inferred_from_the_given_answer() -> None:
    """Revert-check: lendo `correctAnswer` sem olhar `isCorrectAnswersVisible`,
    o gabarito escondido viraria 'False' em todas — e o banco diria que
    nenhuma alternativa estava certa."""
    q = parse_reviewed_attempt(_attempt(visible=False), BASE)["questions"][0]
    assert {o["correct"] for o in q["options"]} == {None}
    assert q["answer_key_visible"] is False


def test_in_progress_attempt_and_assignment_without_questions_are_not_answered_assessments() -> None:
    assert parse_reviewed_attempt(_attempt(status="IN_PROGRESS"), BASE) is None
    no_questions = _attempt()
    no_questions["toolAttemptDetail"]["resource/x-bb-assessment"]["questionAttempts"] = []
    assert parse_reviewed_attempt(no_questions, BASE) is None


def test_attempt_ids_from_grade_do_not_repeat() -> None:
    assert attempt_ids_from_grade({"firstAttemptId": "_1_1", "highestAttemptId": "_2_1", "lastAttemptId": "_2_1"}) == ["_1_1", "_2_1"]


def test_open_attempt_questions_come_with_options_and_no_answer_key() -> None:
    """Tentativa em andamento (formato da AS - Unidade I de Big Data): questões e
    alternativas sim, gabarito nunca — mesmo com `isCorrectAnswersVisible`."""
    from blackboard_mcp.attempt_review import OPEN_STATUSES, parse_attempt_questions

    attempt = _attempt(status="IN_PROGRESS")
    for option in attempt["toolAttemptDetail"]["resource/x-bb-assessment"]["questionAttempts"][0]["question"]["answers"]:
        option.pop("correctAnswer")
    parsed = parse_attempt_questions(attempt, BASE, statuses=OPEN_STATUSES)
    q = parsed["questions"][0]
    assert [o["letter"] for o in q["options"]] == ["A", "B", "C", "D", "E"]
    assert {o["correct"] for o in q["options"]} == {None}
    assert parse_attempt_questions(_attempt(status="COMPLETED"), BASE, statuses=OPEN_STATUSES) is None
