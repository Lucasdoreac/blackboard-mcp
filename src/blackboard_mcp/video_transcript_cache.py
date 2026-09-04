"""Local, per-course cache of what a document page's video check already found.

Real incident (2026-09-04): every `/estudos videos` run walked EVERY document
page of a course again, including pages already confirmed to have no video —
Blackboard's own SPA choked under the repeated navigation ("Cruzeiro Play"-
style bloat tabs, an always-erroring page revisited every run). Course
content inside a semester does not change (the owner's own words: getting
the videos is a one-time routine at the start of each semester) — so a page
already checked never needs a full Playwright walk again.

Two outcomes are cached per `content_id`:
  * `has_video=False` — this page (or its parent folder, already tried) has
    no Kaltura player. Skip it entirely on the next run.
  * `has_video=True` with `entry_id`/`partner_id` — the STABLE Kaltura
    identifiers for the video are known. Kaltura's own session/caption API
    (`client.py::get_video_transcript`) needs only these two public,
    long-lived ids, never a Blackboard cookie — so a future re-fetch (a
    caption re-generated, or just re-syncing) can skip the full authenticated
    Blackboard page walk and only open a bare, unauthenticated page scoped to
    Kaltura's own domain.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_COURSE_ID_RE = re.compile(r"^_[0-9]+_1$")
_CONTENT_ID_RE = re.compile(r"^_[0-9]+_1$")


def _path(data_home: Path, course_id: str) -> Path:
    return data_home / "video_cache" / f"{course_id.strip('_')}.json"


def load_cache(data_home: Path, course_id: str) -> dict[str, dict[str, Any]]:
    """Return `{content_id: entry}` for one course — `{}` if never checked."""
    path = _path(data_home, course_id)
    if not path.exists():
        return {}
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def get_entry(data_home: Path, course_id: str, content_id: str) -> dict[str, Any] | None:
    return load_cache(data_home, course_id).get(content_id)


def save_entry(
    data_home: Path, course_id: str, content_id: str, *,
    has_video: bool, entry_id: str | None = None, partner_id: str | None = None,
) -> None:
    if not _COURSE_ID_RE.fullmatch(course_id):
        raise ValueError("course_id invalido")
    if not _CONTENT_ID_RE.fullmatch(content_id):
        raise ValueError("content_id invalido")
    path = _path(data_home, course_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    cache = load_cache(data_home, course_id)
    cache[content_id] = {
        "has_video": has_video,
        "entry_id": entry_id,
        "partner_id": partner_id,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


__all__ = ["load_cache", "get_entry", "save_entry"]
