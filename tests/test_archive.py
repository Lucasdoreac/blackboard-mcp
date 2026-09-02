import json
from pathlib import Path

import pytest

from blackboard_mcp.archive import archive_declared_pdfs, is_declared_pdf


def test_pdf_classifier_requires_explicit_inventory_declaration() -> None:
    assert is_declared_pdf({"kind": "item", "title": "Aula.pdf"})
    assert is_declared_pdf({"kind": "item", "title": "Arquivo em PDF - Unidade I"})
    assert not is_declared_pdf({"kind": "item", "title": "Videoaula"})
    assert not is_declared_pdf({"kind": "learning_module", "title": "Arquivo em PDF"})


@pytest.mark.asyncio
async def test_archive_is_idempotent_and_records_unsupported_items(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    async def download(course_id: str, content_id: str) -> dict:
        seen.append((course_id, content_id))
        directory = tmp_path / "downloads" / "course_1"
        directory.mkdir(parents=True, exist_ok=True)
        artifact = directory / "item_1--aula.pdf"
        artifact.write_bytes(b"%PDF-study")
        from blackboard_mcp.downloads import persist_download
        temporary = tmp_path / "tmp.pdf"
        temporary.write_bytes(b"%PDF-study")
        return persist_download(tmp_path, course_id=course_id, content_id=content_id, title="Aula.pdf", suggested_filename="aula.pdf", temporary_path=temporary)

    items = [
        {"id": "_item_1", "kind": "item", "title": "Aula.pdf"},
        {"id": "_video_1", "kind": "item", "title": "Videoaula"},
    ]
    first = await archive_declared_pdfs(data_home=tmp_path, course_id="_course_1", items=items, download=download)
    second = await archive_declared_pdfs(data_home=tmp_path, course_id="_course_1", items=items, download=download)
    assert seen == [("_course_1", "_item_1")]
    assert len(first["downloaded"]) == 1
    assert second["skipped"] == [{"content_id": "_item_1", "title": "Aula.pdf", "reason": "already_verified"}]
    assert second["not_archived"]["count"] == 1
    report = json.loads((tmp_path / "archives" / "course_1.json").read_text())
    assert "url" not in json.dumps(report).lower()
