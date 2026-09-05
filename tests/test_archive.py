import json
from pathlib import Path

import pytest

from blackboard_mcp.archive import archive_declared_pdfs, is_declared_pdf


def test_pdf_classifier_requires_explicit_inventory_declaration() -> None:
    assert is_declared_pdf({"kind": "item", "title": "Aula.pdf"})
    assert is_declared_pdf({"kind": "item", "title": "Arquivo em PDF - Unidade I"})
    assert not is_declared_pdf({"kind": "item", "title": "Videoaula"})
    assert not is_declared_pdf({"kind": "learning_module", "title": "Arquivo em PDF"})


def test_pdf_classifier_treats_a_same_host_externallink_as_a_candidate() -> None:
    """Real incident (2026-09-04): "paralela"'s entire teaching material is
    `resource/x-bb-externallink` pointing at Blackboard's own bbcswebdav
    host, titled "Material Didático - Unidade I..VI" (no `.pdf`, no
    `mime_type` for this content type) — the title-only heuristic missed
    ALL of it, leaving the discipline's caderno with zero real material."""
    item = {
        "kind": "item", "title": "Material Didático - Unidade I",
        "content_handler": "resource/x-bb-externallink",
        "external_url": "https://bb.example.com/bbcswebdav/xid-1_1",
    }
    assert is_declared_pdf(item, expected_host="bb.example.com")
    assert not is_declared_pdf(item)  # no expected_host given: falls back to title-only, as before


def test_pdf_classifier_never_treats_a_cross_host_externallink_as_a_candidate() -> None:
    """Revert-check target: without the host check, a genuine third-party
    link (YouTube, an article) titled ambiguously would become a download
    candidate — the exact risk `_download_external_link`'s own host check
    exists to prevent, now duplicated one layer up at candidate selection."""
    item = {
        "kind": "item", "title": "Vídeo da aula",
        "content_handler": "resource/x-bb-externallink",
        "external_url": "https://youtube.com/watch?v=evil",
    }
    assert not is_declared_pdf(item, expected_host="bb.example.com")


def test_pdf_classifier_trusts_the_real_mime_type_over_the_title() -> None:
    """Real incident (2026-09-03): `Aula02_Arquitetura_das_Linguagens_Formais`
    is a genuine PDF confirmed by its own `mimeType`, but its title carries no
    `.pdf` suffix — the title-only heuristic missed it, leaving a real PDF
    permanently out of the acervo/caderno sync."""
    assert is_declared_pdf({
        "kind": "item", "title": "Aula02_Arquitetura_das_Linguagens_Formais", "mime_type": "application/pdf",
    })
    assert not is_declared_pdf({
        "kind": "item", "title": "Vídeo de boas-vindas", "mime_type": "video/mp4",
    })


@pytest.mark.asyncio
async def test_archive_is_idempotent_and_records_unsupported_items(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    async def download(course_id: str, content_id: str, kind: str = "pdf") -> dict:
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
