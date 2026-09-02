from blackboard_mcp.announcements import extract_announcements


def test_extracts_title_body_and_published_at() -> None:
    rows = extract_announcements("_course_1", [{
        "id": "_4299599_1",
        "title": "11/08 _ Aula no Laboratório 5 do Edifício 4R",
        "createdDate": "2026-08-11T22:18:35.744Z",
        "body": {"rawText": "<p>Turma, vem para a aula 02!</p><br><p>Profa. Kadidja Valéria</p><br>"},
    }])
    assert rows == [{
        "course_id": "_course_1", "content_id": "_4299599_1",
        "title": "11/08 _ Aula no Laboratório 5 do Edifício 4R",
        "body": "Turma, vem para a aula 02! Profa. Kadidja Valéria",
        "published_at": "2026-08-11T22:18:35.744Z",
    }]


def test_skips_rows_missing_required_fields() -> None:
    assert extract_announcements("_course_1", [{"id": "_1_1", "title": "", "createdDate": "2026-08-11T22:18:35.744Z"}]) == []
    assert extract_announcements("_course_1", [{"id": "", "title": "x", "createdDate": "2026-08-11T22:18:35.744Z"}]) == []
    assert extract_announcements("_course_1", [{"id": "_1_1", "title": "x", "createdDate": ""}]) == []


def test_missing_body_becomes_empty_string_not_a_crash() -> None:
    rows = extract_announcements("_course_1", [{
        "id": "_1_1", "title": "Aviso sem corpo", "createdDate": "2026-08-11T22:18:35.744Z",
    }])
    assert rows[0]["body"] == ""


def test_sorted_newest_first() -> None:
    rows = extract_announcements("_course_1", [
        {"id": "_a", "title": "A", "createdDate": "2026-08-01T00:00:00.000Z", "body": {"rawText": ""}},
        {"id": "_b", "title": "B", "createdDate": "2026-08-11T00:00:00.000Z", "body": {"rawText": ""}},
    ])
    assert [r["content_id"] for r in rows] == ["_b", "_a"]
