"""Deterministic local snapshots for read-only Blackboard inventory."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def manifest_path(data_home: Path, course_id: str) -> Path:
    return data_home / "manifests" / f"{course_id}.json"


def diff_items(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, list[str]]:
    old = {str(row["id"]): row for row in previous}
    new = {str(row["id"]): row for row in current}
    return {
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "changed": sorted(item_id for item_id in new.keys() & old.keys() if new[item_id] != old[item_id]),
        "unchanged": sorted(item_id for item_id in new.keys() & old.keys() if new[item_id] == old[item_id]),
    }


def save_snapshot(data_home: Path, course_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    path = manifest_path(data_home, course_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    previous: list[dict[str, Any]] = []
    if path.exists():
        previous_data = json.loads(path.read_text(encoding="utf-8"))
        previous = previous_data.get("items", []) if isinstance(previous_data, dict) else []
    normalized = sorted(items, key=lambda row: str(row["id"]))
    diff = diff_items(previous, normalized)
    payload = {
        "course_id": course_id,
        "observed_at": datetime.now(UTC).isoformat(),
        "items": normalized,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return {"course_id": course_id, "item_count": len(normalized), **diff}
