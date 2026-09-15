"""Owner-curated course catalog, independent of Blackboard card availability.

Só o que é do Blackboard: id do curso, título, quando foi registrado. O vínculo
curso → caderno NotebookLM saiu daqui em 2026-09-15 — a SOBER é a dona dele
(registro único de cadernos, sober#406). Um catálogo antigo que ainda tenha
`notebook_id` gravado não o expõe mais: a leitura devolve só os campos do curso.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_COURSE_ID_RE = re.compile(r"^_[0-9]+_1$")
_TITLE_RE = re.compile(r"^\S(?:.{0,158}\S)?$")
_COURSE_FIELDS = ("id", "title", "registered_at")


def _path(data_home: Path) -> Path:
    return data_home / "catalog" / "courses.json"


def load_courses(data_home: Path) -> list[dict[str, str]]:
    path = _path(data_home)
    if not path.exists():
        return []
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("catalogo local invalido")
    return [
        {key: row[key] for key in _COURSE_FIELDS if key in row}
        for row in raw
        if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("title"), str)
    ]


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
