from pathlib import Path

import pytest

from blackboard_mcp.video_transcript_cache import get_entry, load_cache, save_entry


def test_load_cache_is_empty_when_never_checked(tmp_path: Path) -> None:
    assert load_cache(tmp_path, "_1_1") == {}


def test_save_and_load_a_negative_entry(tmp_path: Path) -> None:
    save_entry(tmp_path, "_1_1", "_2_1", has_video=False)
    entry = get_entry(tmp_path, "_1_1", "_2_1")
    assert entry is not None
    assert entry["has_video"] is False
    assert entry["entry_id"] is None
    assert "checked_at" in entry


def test_save_and_load_a_positive_entry_with_kaltura_ids(tmp_path: Path) -> None:
    save_entry(tmp_path, "_1_1", "_2_1", has_video=True, entry_id="0_abc123", partner_id="1756931")
    entry = get_entry(tmp_path, "_1_1", "_2_1")
    assert entry == {
        "has_video": True, "entry_id": "0_abc123", "partner_id": "1756931",
        "checked_at": entry["checked_at"],
    }


def test_get_entry_returns_none_for_an_unchecked_content_id(tmp_path: Path) -> None:
    save_entry(tmp_path, "_1_1", "_2_1", has_video=False)
    assert get_entry(tmp_path, "_1_1", "_3_1") is None


def test_entries_for_different_courses_never_collide(tmp_path: Path) -> None:
    save_entry(tmp_path, "_1_1", "_2_1", has_video=True, entry_id="x", partner_id="1")
    save_entry(tmp_path, "_9_1", "_2_1", has_video=False)
    assert get_entry(tmp_path, "_1_1", "_2_1")["has_video"] is True
    assert get_entry(tmp_path, "_9_1", "_2_1")["has_video"] is False


def test_save_entry_rejects_malformed_course_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="course_id invalido"):
        save_entry(tmp_path, "not-a-course", "_2_1", has_video=False)


def test_save_entry_rejects_malformed_content_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="content_id invalido"):
        save_entry(tmp_path, "_1_1", "not-a-content-id", has_video=False)


def test_load_cache_recovers_from_a_corrupt_file(tmp_path: Path) -> None:
    """Best-effort persistence: a corrupted cache file degrades to "nothing
    cached yet" rather than crashing the whole video walk."""
    path = tmp_path / "video_cache" / "1_1.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert load_cache(tmp_path, "_1_1") == {}


def test_save_entry_overwrites_a_previous_result_for_the_same_content_id(tmp_path: Path) -> None:
    """Real incident (2026-09-04): the owner pointed to a REAL video the
    first pass missed — a later, successful re-check has to be able to
    replace an earlier "no video" verdict, not just merge/ignore it."""
    save_entry(tmp_path, "_1_1", "_2_1", has_video=False)
    save_entry(tmp_path, "_1_1", "_2_1", has_video=True, entry_id="0_abc", partner_id="42")
    entry = get_entry(tmp_path, "_1_1", "_2_1")
    assert entry["has_video"] is True
    assert entry["entry_id"] == "0_abc"
