"""Pure normalization of one `contents/{id}/children` REST row.

`contentHandler` classifies the node (a plain string field on every row,
confirmed against real course content): `resource/x-bb-folder` and
`resource/x-bb-lesson` are containers Blackboard also renders as expandable
in the outline UI; everything else (`resource/x-bb-file`,
`resource/x-bb-asmt-test-link`, ...) is a leaf. `genericReadOnlyData.dueDate`
is the structured ISO8601 due date Blackboard's UI renders as the
"Data de entrega: DD/MM/YY HH:MM (BRT)" string — reading it directly skips
that BR-locale text parsing entirely.

`mime_type` is the real file type for a `resource/x-bb-file` leaf, read from
`contentDetail["resource/x-bb-file"]["file"]["mimeType"]` — already present
on the `@view=Summary` row the tree walk already fetches, at no extra REST
cost. Real incident (2026-09-03): a title-only PDF heuristic (`is_declared_
pdf` in `archive.py`) missed genuine PDFs whose title carries no `.pdf`
suffix (e.g. `Aula02_Arquitetura_das_Linguagens_Formais`, confirmed PDF by
its own `mimeType`); this field lets the archiver check the actual type
instead of guessing from the title.

`content_handler` is the raw handler string, kept alongside the already-
collapsed `kind` — a consumer that needs to tell a `resource/x-bb-document`
page apart from a `resource/x-bb-file`/`resource/x-bb-asmt-test-link` (both
already `kind: "item"`) can filter on it without a second REST round-trip
per item (e.g. `video_descriptions.py` only opens document pages).

`external_url` is the target of a `resource/x-bb-externallink` leaf, read
from `contentDetail["resource/x-bb-externallink"]["url"]`. Real incident
(2026-09-04): a course ("paralela") whose real teaching material is entirely
`resource/x-bb-externallink` pointing at Blackboard's own `bbcswebdav` host
(titles like "Material Didático - Unidade I", never ending in `.pdf`) never
got archived — `is_declared_pdf`'s title heuristic is the only signal for
this content type, since it has no `mime_type`. Exposing the URL lets a
caller with the expected host (`archive.py::is_declared_pdf`, given one) do
the SAME same-host check `_download_external_link` already trusts, instead
of guessing content type from a professor-chosen label.

`parent_id` is the id of the row's own container (folder/lesson), or None at
the tree root. Real incident (2026-09-04): a "Videoaula" folder wraps a
single `resource/x-bb-document` child that embeds the actual Kaltura lecture
player — navigating to the CHILD's own document URL never loads the player
(confirmed live, zero network activity), only navigating to the PARENT
FOLDER's URL does. `client.py::list_video_transcripts` needs the parent id to
retry there when the child's own page yields nothing.
"""

from __future__ import annotations

from typing import Any

_CONTAINER_HANDLERS = {"resource/x-bb-folder": "folder", "resource/x-bb-lesson": "learning_module"}


def _file_mime_type(raw: dict[str, Any]) -> str | None:
    detail = ((raw.get("contentDetail") or {}).get("resource/x-bb-file") or {}).get("file") or {}
    mime_type = detail.get("mimeType")
    return str(mime_type) if mime_type else None


def _external_url(raw: dict[str, Any]) -> str | None:
    detail = (raw.get("contentDetail") or {}).get("resource/x-bb-externallink") or {}
    url = detail.get("url")
    return str(url) if url else None


def normalize_tree_row(raw: dict[str, Any], *, depth: int, parent_id: str | None = None) -> dict[str, Any] | None:
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
        "mime_type": _file_mime_type(raw),
        "content_handler": handler,
        "external_url": _external_url(raw),
        "parent_id": parent_id,
    }


def is_container(raw: dict[str, Any]) -> bool:
    return str(raw.get("contentHandler") or "") in _CONTAINER_HANDLERS


__all__ = ["normalize_tree_row", "is_container"]
