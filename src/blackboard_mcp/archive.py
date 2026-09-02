"""Idempotent archive of direct Blackboard PDF materials.

This module deliberately archives only resources whose *inventory title*
declares a PDF.  It never opens a video player, follows an external link, or
tries to extract media from a streaming service.  Those variants must gain
their own explicit, lawful contracts before they can join the local archive.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .downloads import verified_receipt


def is_declared_pdf(item: dict[str, Any]) -> bool:
    """Return true only for leaf inventory records that explicitly name a PDF."""
    if item.get("kind") != "item":
        return False
    title = str(item.get("title") or "").strip().casefold()
    return title.endswith(".pdf") or "arquivo em pdf" in title


def archive_report_path(data_home: Path, course_id: str) -> Path:
    directory = data_home / "archives"
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory / f"{course_id.strip('_')}.json"


async def archive_declared_pdfs(
    *,
    data_home: Path,
    course_id: str,
    items: list[dict[str, Any]],
    download: Callable[[str, str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Archive every declared PDF once and return a durable, safe report.

    Existing verified receipts are skipped; a failed candidate is recorded so
    the owner can see a gap without treating it as a successful archive.
    """
    candidates = [item for item in items if is_declared_pdf(item)]
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for item in candidates:
        content_id = str(item.get("id") or "")
        title = str(item.get("title") or "")
        if not content_id:
            continue
        if verified_receipt(data_home, course_id=course_id, content_id=content_id) is not None:
            skipped.append({"content_id": content_id, "title": title, "reason": "already_verified"})
            continue
        try:
            receipt = await download(course_id, content_id)
        except (RuntimeError, ValueError) as exc:
            # Browser/portal errors can contain URLs or implementation details.
            failed.append({"content_id": content_id, "title": title, "reason": type(exc).__name__})
        else:
            downloaded.append({
                "content_id": content_id,
                "title": title,
                "sha256": str(receipt.get("sha256") or ""),
                "size_bytes": int(receipt.get("size_bytes") or 0),
            })
    report = {
        "course_id": course_id,
        "observed_at": datetime.now(UTC).isoformat(),
        "declared_pdf_count": len(candidates),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "not_archived": {
            "reason": "Only explicitly declared PDFs are archived automatically; videos, pages and external links remain inventory references.",
            "count": len([item for item in items if item.get("kind") == "item" and not is_declared_pdf(item)]),
        },
    }
    path = archive_report_path(data_home, course_id)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return report
