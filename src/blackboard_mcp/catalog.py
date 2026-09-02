"""Owner-curated course catalog, independent of Blackboard card availability."""

from __future__ import annotations

import json
import os
import re
from uuid import UUID
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_COURSE_ID_RE = re.compile(r"^_[0-9]+_1$")
_TITLE_RE = re.compile(r"^\S(?:.{0,158}\S)?$")


def _path(data_home: Path) -> Path:
    return data_home / "catalog" / "courses.json"


def load_courses(data_home: Path) -> list[dict[str, str]]:
    path = _path(data_home)
    if not path.exists():
        return []
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("catalogo local invalido")
    return [row for row in raw if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("title"), str)]


def register_course(data_home: Path, *, course_id: str, title: str) -> dict[str, str]:
    if not _COURSE_ID_RE.fullmatch(course_id):
        raise ValueError("course_id invalido")
    title = title.strip()
    if not _TITLE_RE.fullmatch(title):
        raise ValueError("titulo invalido")
    path = _path(data_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    rows = {row["id"]: row for row in load_courses(data_home)}
    record = {"id": course_id, "title": title, "registered_at": datetime.now(UTC).isoformat()}
    rows[course_id] = record
    path.write_text(json.dumps(sorted(rows.values(), key=lambda row: row["title"]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return record


def bind_notebook(data_home: Path, *, course_id: str, notebook_id: str) -> dict[str, str]:
    """Persist an owner-confirmed course → NotebookLM relation locally."""
    if not _COURSE_ID_RE.fullmatch(course_id):
        raise ValueError("course_id invalido")
    try:
        UUID(notebook_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("notebook_id invalido") from exc
    path = _path(data_home)
    rows = {row["id"]: row for row in load_courses(data_home)}
    record = rows.get(course_id)
    if record is None:
        raise ValueError("disciplina nao registrada")
    updated = {**record, "notebook_id": notebook_id}
    rows[course_id] = updated
    path.write_text(json.dumps(sorted(rows.values(), key=lambda row: row["title"]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return updated
