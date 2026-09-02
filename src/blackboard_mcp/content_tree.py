"""Pure normalization of one `contents/{id}/children` REST row.

`contentHandler` classifies the node (a plain string field on every row,
confirmed against real course content): `resource/x-bb-folder` and
`resource/x-bb-lesson` are containers Blackboard also renders as expandable
in the outline UI; everything else (`resource/x-bb-file`,
`resource/x-bb-asmt-test-link`, ...) is a leaf. `genericReadOnlyData.dueDate`
is the structured ISO8601 due date Blackboard's UI renders as the
"Data de entrega: DD/MM/YY HH:MM (BRT)" string — reading it directly skips
that BR-locale text parsing entirely.
"""

from __future__ import annotations

from typing import Any

_CONTAINER_HANDLERS = {"resource/x-bb-folder": "folder", "resource/x-bb-lesson": "learning_module"}


def normalize_tree_row(raw: dict[str, Any], *, depth: int) -> dict[str, Any] | None:
    content_id = str(raw.get("id") or "")
    title = str(raw.get("title") or "")
    if not content_id or not title:
        return None
    handler = str(raw.get("contentHandler") or "")
    due_at = (raw.get("genericReadOnlyData") or {}).get("dueDate")
    return {
        "id": content_id,
        "title": title,
        "kind": _CONTAINER_HANDLERS.get(handler, "item"),
        "depth": depth,
        "due_at": str(due_at) if due_at else None,
    }


def is_container(raw: dict[str, Any]) -> bool:
    return str(raw.get("contentHandler") or "") in _CONTAINER_HANDLERS


__all__ = ["normalize_tree_row", "is_container"]
