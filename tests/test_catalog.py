from pathlib import Path

import pytest

from blackboard_mcp.catalog import bind_notebook, load_courses, register_course


def test_registered_course_survives_card_unavailability(tmp_path: Path) -> None:
    saved = register_course(tmp_path, course_id="_1169577_1", title="Linguagens Formais e Autômatos")
    assert saved["id"] == "_1169577_1"
    assert load_courses(tmp_path)[0]["title"] == "Linguagens Formais e Autômatos"
    assert (tmp_path / "catalog" / "courses.json").stat().st_mode & 0o077 == 0


def test_notebook_binding_requires_registered_course_and_uuid(tmp_path: Path) -> None:
    register_course(tmp_path, course_id="_1169577_1", title="Linguagens Formais e Autômatos")
    bound = bind_notebook(tmp_path, course_id="_1169577_1", notebook_id="c71c5106-eac1-468b-83e5-d872ecd85d80")
    assert bound["notebook_id"] == "c71c5106-eac1-468b-83e5-d872ecd85d80"
    with pytest.raises(ValueError, match="disciplina nao registrada"):
        bind_notebook(tmp_path, course_id="_999_1", notebook_id="c71c5106-eac1-468b-83e5-d872ecd85d80")


@pytest.mark.parametrize("course_id,title", [("not-a-course", "LFA"), ("_1_1", " ")])
def test_catalog_rejects_unsafe_records(tmp_path: Path, course_id: str, title: str) -> None:
    with pytest.raises(ValueError):
        register_course(tmp_path, course_id=course_id, title=title)
