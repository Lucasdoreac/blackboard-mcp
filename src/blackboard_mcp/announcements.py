"""Pure normalization of the `/learn/api/v1/courses/{id}/announcements` payload."""

from __future__ import annotations

import re
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def extract_announcements(course_id: str, raw_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in raw_results:
        title = str(row.get("title") or "")
        content_id = str(row.get("id") or "")
        created_at = str(row.get("createdDate") or "")
        if not content_id or not title or not created_at:
            continue
        body_raw = str((row.get("body") or {}).get("rawText") or "")
        rows.append({
            "course_id": course_id,
            "content_id": content_id,
            "title": title,
            "body": _strip_html(body_raw),
            "published_at": created_at,
        })
    return sorted(rows, key=lambda r: (r["published_at"], r["content_id"]), reverse=True)


__all__ = ["extract_announcements"]
