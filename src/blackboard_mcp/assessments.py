"""Filter of visible assessment deadlines out of a normalized content tree.

`due_at` is now read directly from the REST API's `genericReadOnlyData.
dueDate` field (see `content_tree.py`) — no more regex over UI-rendered
text. The tree only carries `due_at` on leaf items (containers never have
one), so this is a pure filter + reshape, not an extraction.
"""

from __future__ import annotations

from typing import Any


def extract_assessments(course_id: str, items: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        due_at = item.get("due_at")
        if not due_at:
            continue
        rows.append({
            "course_id": course_id,
            "content_id": str(item["id"]),
            "title": str(item.get("title", "")),
            "due_at": str(due_at),
            # The API proves listing and deadline, not submission state.
            "observed_status": "listed",
        })
    return sorted(rows, key=lambda row: (row["due_at"], row["content_id"]))


__all__ = ["extract_assessments"]
