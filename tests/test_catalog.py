from pathlib import Path

import pytest

import json

from blackboard_mcp.catalog import load_courses, register_course


def test_registered_course_survives_card_unavailability(tmp_path: Path) -> None:
    saved = register_course(tmp_path, course_id="_1169577_1", title="Linguagens Formais e Autômatos")
    assert saved["id"] == "_1169577_1"
    assert load_courses(tmp_path)[0]["title"] == "Linguagens Formais e Autômatos"
    assert (tmp_path / "catalog" / "courses.json").stat().st_mode & 0o077 == 0


def test_legacy_notebook_binding_is_not_exposed(tmp_path: Path) -> None:
    """O vínculo curso→caderno é da SOBER (registro único); um catálogo antigo
    com `notebook_id` gravado não pode mais vazá-lo como se fosse fonte de verdade."""
    register_course(tmp_path, course_id="_1169577_1", title="Linguagens Formais e Autômatos")
    path = tmp_path / "catalog" / "courses.json"
    rows = json.loads(path.read_text())
    rows[0]["notebook_id"] = "c71c5106-eac1-468b-83e5-d872ecd85d80"
    path.write_text(json.dumps(rows))
    course = load_courses(tmp_path)[0]
    assert "notebook_id" not in course
    assert course["id"] == "_1169577_1"


@pytest.mark.parametrize("course_id,title", [("not-a-course", "LFA"), ("_1_1", " ")])
def test_catalog_rejects_unsafe_records(tmp_path: Path, course_id: str, title: str) -> None:
    with pytest.raises(ValueError):
        register_course(tmp_path, course_id=course_id, title=title)
