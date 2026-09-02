from blackboard_mcp.assessments import extract_assessments


def test_extracts_item_carrying_a_structured_due_date() -> None:
    rows = extract_assessments("_course_1", [{
        "id": "_item_1", "title": "AS - Unidade I", "kind": "item", "depth": 2,
        "due_at": "2026-11-06T23:59:00.000Z",
    }])
    assert rows == [{
        "course_id": "_course_1", "content_id": "_item_1", "title": "AS - Unidade I",
        "due_at": "2026-11-06T23:59:00.000Z", "observed_status": "listed",
    }]


def test_ignores_items_without_a_due_date() -> None:
    assert extract_assessments("_course_1", [
        {"id": "_folder_1", "title": "Atividades", "kind": "folder", "depth": 0, "due_at": None},
        {"id": "_file_1", "title": "Plano de Ensino.pdf", "kind": "item", "depth": 1, "due_at": None},
    ]) == []


def test_sorts_by_due_date_then_content_id() -> None:
    rows = extract_assessments("_course_1", [
        {"id": "_b", "title": "B", "kind": "item", "depth": 1, "due_at": "2026-11-06T23:59:00.000Z"},
        {"id": "_a", "title": "A", "kind": "item", "depth": 1, "due_at": "2026-09-12T23:59:00.000Z"},
    ])
    assert [r["content_id"] for r in rows] == ["_a", "_b"]
