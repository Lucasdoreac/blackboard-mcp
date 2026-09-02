from pathlib import Path

from blackboard_mcp.sync import save_snapshot


def test_first_snapshot_marks_every_item_added(tmp_path: Path) -> None:
    result = save_snapshot(tmp_path, "_1_1", [{"id": "a", "title": "A"}])
    assert result["added"] == ["a"]
    assert result["changed"] == []


def test_second_snapshot_is_deterministic_and_reports_delta(tmp_path: Path) -> None:
    save_snapshot(tmp_path, "_1_1", [{"id": "a", "title": "A"}])
    result = save_snapshot(tmp_path, "_1_1", [{"id": "a", "title": "A2"}, {"id": "b", "title": "B"}])
    assert result["added"] == ["b"]
    assert result["changed"] == ["a"]
    assert result["removed"] == []
