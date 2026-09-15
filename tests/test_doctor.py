from __future__ import annotations

from pathlib import Path

from blackboard_mcp.cli import doctor_report


def test_doctor_reports_only_local_setup_facts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    monkeypatch.setenv("BLACKBOARD_CHROME_PATH", "/missing/chrome")

    report = doctor_report("alice")

    assert report["profile"] == "alice"
    assert report["chrome"] == {"path": "/missing/chrome", "found": False}
    assert report["profile_config"]["found"] is False
    assert report["saved_session"]["found"] is False
    assert report["next_step"] == "login"
