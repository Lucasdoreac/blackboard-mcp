from pathlib import Path

from blackboard_mcp.downloads import (
    list_verified_receipts, persist_download, read_download_chunk, verified_receipt,
)


def test_persist_download_never_uses_signed_url_or_unsafe_filename(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    temporary.write_bytes(b"%PDF-study material")
    receipt = persist_download(
        tmp_path / "state",
        course_id="_course_1",
        content_id="_item_1",
        title="Aula 1",
        suggested_filename="../../aula?.pdf",
        temporary_path=temporary,
    )
    assert receipt["filename"] == "item_1--aula_.pdf"
    path = tmp_path / "state" / "downloads" / "course_1" / receipt["filename"]
    assert path.read_bytes() == b"%PDF-study material"
    assert path.stat().st_mode & 0o077 == 0
    assert "url" not in path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8").lower()


def test_read_download_chunk_verifies_hash_and_is_bounded(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    temporary.write_bytes(b"%PDF-abcdefgh")
    persist_download(
        tmp_path / "state", course_id="_course_1", content_id="_item_1",
        title="Aula 1", suggested_filename="aula.pdf", temporary_path=temporary,
    )
    chunk = read_download_chunk(tmp_path / "state", course_id="_course_1", content_id="_item_1", offset=7, length=3)
    assert chunk["offset"] == 7
    assert chunk["total_bytes"] == 13
    assert chunk["eof"] is False
    assert chunk["data_b64"] == "Y2Rl"


def test_persist_download_rejects_html_disguised_as_pdf(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    temporary.write_bytes(b"<html>not a pdf</html>")
    import pytest
    with pytest.raises(ValueError, match="PDF valido"):
        persist_download(
            tmp_path / "state", course_id="_course_1", content_id="_item_1",
            title="Aula", suggested_filename="aula.pdf", temporary_path=temporary,
        )
    assert not temporary.exists()


def test_verified_receipt_rejects_tampered_artifact(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    temporary.write_bytes(b"%PDF-original")
    receipt = persist_download(
        tmp_path / "state", course_id="_course_1", content_id="_item_1",
        title="Aula", suggested_filename="aula.pdf", temporary_path=temporary,
    )
    artifact = tmp_path / "state" / "downloads" / "course_1" / receipt["filename"]
    assert verified_receipt(tmp_path / "state", course_id="_course_1", content_id="_item_1")
    artifact.write_bytes(b"%PDF-tampered")
    assert verified_receipt(tmp_path / "state", course_id="_course_1", content_id="_item_1") is None


def test_list_verified_receipts_excludes_paths_and_tampered_files(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    temporary.write_bytes(b"%PDF-study")
    receipt = persist_download(
        tmp_path / "state", course_id="_course_1", content_id="_item_1",
        title="Aula", suggested_filename="aula.pdf", temporary_path=temporary,
    )
    rows = list_verified_receipts(tmp_path / "state", course_id="_course_1")
    assert rows == [{
        "course_id": "_course_1", "content_id": "_item_1", "title": "Aula",
        "kind": "pdf",
        "sha256": receipt["sha256"], "size_bytes": receipt["size_bytes"],
        "downloaded_at": receipt["downloaded_at"],
    }]
    assert "filename" not in rows[0]


def test_receipt_carries_the_proven_kind(tmp_path: Path) -> None:
    """A `.pptx` (`PK\\x03\\x04`) verificado como office tem que dizer 'office'
    no recibo — senão o consumidor re-adivinha 'pdf' pelo título em prosa e
    roda o extrator errado (real: pypdfium2 num ZIP, 2026-09-09)."""
    temp = tmp_path / "t"
    temp.write_bytes(b"PK\x03\x04" + b"rest of a zip" * 4)
    receipt = persist_download(
        tmp_path / "state", course_id="_c_1", content_id="_i_1",
        title="Apostila 02 PDM", suggested_filename="Apostila 02 PDM",
        temporary_path=temp, kind="office",
    )
    assert receipt["kind"] == "office"
    rows = list_verified_receipts(tmp_path / "state", course_id="_c_1")
    assert rows[0]["kind"] == "office"
