from blackboard_mcp.content_tree import is_container, normalize_tree_row


def test_normalizes_a_folder_as_a_container() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Documentos", "contentHandler": "resource/x-bb-folder"}, depth=0)
    assert row == {
        "id": "_1_1", "title": "Documentos", "kind": "folder", "depth": 0, "due_at": None,
        "mime_type": None, "content_handler": "resource/x-bb-folder", "external_url": None,
        "parent_id": None,
    }


def test_normalizes_a_lesson_as_a_learning_module() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Boas-vindas", "contentHandler": "resource/x-bb-lesson"}, depth=0)
    assert row["kind"] == "learning_module"


def test_normalizes_a_file_as_a_plain_item_with_no_due_date() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Plano.pdf", "contentHandler": "resource/x-bb-file"}, depth=2)
    assert row["kind"] == "item"
    assert row["due_at"] is None


def test_carries_the_real_file_mime_type_when_present() -> None:
    """Real incident (2026-09-03): `Aula02_Arquitetura_das_Linguagens_Formais`
    is a genuine PDF (confirmed by its own `mimeType`/`fileName`) whose title
    carries no `.pdf` suffix — the archiver's title-only heuristic missed it.
    The `@view=Summary` row already carries this field for free (no extra
    REST call), so normalization should not throw it away."""
    row = normalize_tree_row({
        "id": "_1_1", "title": "Aula02_Arquitetura_das_Linguagens_Formais",
        "contentHandler": "resource/x-bb-file",
        "contentDetail": {"resource/x-bb-file": {"file": {
            "mimeType": "application/pdf", "fileName": "Aula02_Arquitetura_das_Linguagens_Formais.pdf",
        }}},
    }, depth=2)
    assert row["mime_type"] == "application/pdf"


def test_mime_type_is_none_when_absent() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Link externo", "contentHandler": "resource/x-bb-externallink"}, depth=1)
    assert row["mime_type"] is None


def test_carries_the_externallink_url_when_present() -> None:
    row = normalize_tree_row({
        "id": "_1_1", "title": "Material Didático - Unidade I", "contentHandler": "resource/x-bb-externallink",
        "contentDetail": {"resource/x-bb-externallink": {"url": "https://bb.example/bbcswebdav/xid-1_1"}},
    }, depth=1)
    assert row["external_url"] == "https://bb.example/bbcswebdav/xid-1_1"


def test_external_url_is_none_when_absent() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Plano.pdf", "contentHandler": "resource/x-bb-file"}, depth=2)
    assert row["external_url"] is None


def test_parent_id_defaults_to_none() -> None:
    row = normalize_tree_row({"id": "_1_1", "title": "Item raiz", "contentHandler": "resource/x-bb-file"}, depth=0)
    assert row["parent_id"] is None


def test_parent_id_is_carried_when_given() -> None:
    """Real incident (2026-09-04): a "Videoaula" folder wraps a single
    document child that embeds the actual lecture player — the child's own
    page never loads it, only the parent folder's does. The tree walk needs
    this to retry there."""
    row = normalize_tree_row(
        {"id": "_2_1", "title": "ultraDocumentBody", "contentHandler": "resource/x-bb-document"},
        depth=1, parent_id="_1_1",
    )
    assert row["parent_id"] == "_1_1"


def test_content_handler_survives_normalization_for_document_pages() -> None:
    """`resource/x-bb-document` collapses to the same `kind: "item"` as a
    file or an assessment link — a consumer that needs document pages
    specifically (e.g. to look for embedded video descriptions) needs the
    raw handler, not just `kind`."""
    row = normalize_tree_row({"id": "_1_1", "title": "Página", "contentHandler": "resource/x-bb-document"}, depth=1)
    assert row["kind"] == "item"
    assert row["content_handler"] == "resource/x-bb-document"


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
