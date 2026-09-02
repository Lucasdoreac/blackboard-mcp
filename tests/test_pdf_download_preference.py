import json
from pathlib import Path

from blackboard_mcp.client import ensure_pdfs_download_externally


def test_creates_preferences_with_the_flag_when_none_exists(tmp_path: Path) -> None:
    ensure_pdfs_download_externally(tmp_path)
    data = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert data["plugins"]["always_open_pdf_externally"] is True


def test_merges_into_existing_preferences_without_dropping_other_keys(tmp_path: Path) -> None:
    """Revert-check target: this profile also carries the real Blackboard
    login session — a blind overwrite (instead of merge) would be a real
    risk to unrelated Chrome state, even though the login itself lives in
    a separate cookie store, not Preferences."""
    prefs_path = tmp_path / "Default" / "Preferences"
    prefs_path.parent.mkdir(parents=True)
    prefs_path.write_text(json.dumps({"profile": {"name": "sober"}, "plugins": {"other_flag": False}}))

    ensure_pdfs_download_externally(tmp_path)

    data = json.loads(prefs_path.read_text())
    assert data["profile"]["name"] == "sober"
    assert data["plugins"]["other_flag"] is False
    assert data["plugins"]["always_open_pdf_externally"] is True


def test_is_a_noop_when_the_flag_is_already_set(tmp_path: Path) -> None:
    ensure_pdfs_download_externally(tmp_path)
    first_mtime = (tmp_path / "Default" / "Preferences").stat().st_mtime_ns
    ensure_pdfs_download_externally(tmp_path)
    second_mtime = (tmp_path / "Default" / "Preferences").stat().st_mtime_ns
    assert first_mtime == second_mtime


def test_recovers_from_corrupt_preferences_file(tmp_path: Path) -> None:
    prefs_path = tmp_path / "Default" / "Preferences"
    prefs_path.parent.mkdir(parents=True)
    prefs_path.write_text("{not valid json")

    ensure_pdfs_download_externally(tmp_path)

    data = json.loads(prefs_path.read_text())
    assert data["plugins"]["always_open_pdf_externally"] is True
