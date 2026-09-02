from blackboard_mcp.content_tree import is_container, normalize_tree_row


def test_normalizes_a_folder_as_a_container() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Documentos", "contentHandler": "resource/x-bb-folder"}, depth=0)
    assert row == {"id": "_1_1", "title": "Documentos", "kind": "folder", "depth": 0, "due_at": None}


def test_normalizes_a_lesson_as_a_learning_module() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Boas-vindas", "contentHandler": "resource/x-bb-lesson"}, depth=0)
    assert row["kind"] == "learning_module"


def test_normalizes_a_file_as_a_plain_item_with_no_due_date() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Plano.pdf", "contentHandler": "resource/x-bb-file"}, depth=2)
    assert row["kind"] == "item"
    assert row["due_at"] is None


def test_carries_the_structured_due_date_when_present() -> None:
    row = normalize_tree_row({
        "id": "_1_1", "title": "07 - Compreendendo", "contentHandler": "resource/x-bb-asmt-test-link",
        "genericReadOnlyData": {"dueDate": "2026-09-13T02:59:00.000Z"},
    }, depth=1)
    assert row["due_at"] == "2026-09-13T02:59:00.000Z"


def test_missing_id_or_title_is_skipped() -> None:
    assert normalize_tree_row({"title": "no id"}, depth=0) is None
    assert normalize_tree_row({"id": "_1_1"}, depth=0) is None


def test_is_container_matches_folder_and_lesson_only() -> None:
    assert is_container({"contentHandler": "resource/x-bb-folder"}) is True
    assert is_container({"contentHandler": "resource/x-bb-lesson"}) is True
    assert is_container({"contentHandler": "resource/x-bb-file"}) is False
    assert is_container({}) is False
