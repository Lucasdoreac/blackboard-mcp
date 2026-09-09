"""Idempotent archive of direct Blackboard PDF materials.

This module archives resources that are, by their own record, a real
document hosted on Blackboard itself: a `resource/x-bb-file` whose
`mime_type` says PDF, an inventory title that says so, or a
`resource/x-bb-externallink` whose target stays on Blackboard's own host
(given that host to check against). It never opens a video player, never
follows a link to a genuinely third-party site, and never tries to extract
media from a streaming service. Those variants must gain their own explicit,
lawful contracts before they can join the local archive.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .downloads import verified_receipt


def is_declared_pdf(item: dict[str, Any], *, expected_host: str | None = None) -> bool:
    """Return true for leaf inventory records that are, or plausibly are, a PDF.

    `mime_type` (from the item's own Blackboard file record, when present) is
    the authoritative signal and is checked first. The title heuristic stays
    as a fallback for content types without a `mime_type` and no host to
    check (e.g. externallink titled "Arquivo em PDF..."). When `expected_host`
    is given, a `resource/x-bb-externallink` pointing at that SAME host is
    also a candidate — real incident (2026-09-04): a course whose actual
    teaching material is entirely same-host externallink items titled
    "Material Didático - Unidade I..VI" (no `.pdf`, no `mime_type` available
    for this content type) was never archived. `download_content`'s own
    dispatch (`_download_external_link`) already refuses a cross-host URL and
    `persist_download` already verifies the PDF magic bytes — this only
    widens which same-host links get a download ATTEMPT, it does not weaken
    either safety check.
    """
    return declared_kind(item, expected_host=expected_host) is not None


# Extensões que o acervo arquiva além de PDF. Curso de computação entrega
# código e texto puro tanto quanto entrega slide — e o gate anterior só
# reconhecia PDF, então `.md`, `.py` ou `.cpp` numa aba nunca eram sequer
# CANDIDATOS a download (achado do dono, 2026-09-05). Vídeo fica de fora de
# propósito: o texto útil dele é a transcrição, obtida sem baixar o arquivo.
_TEXT_EXTS = frozenset({
    ".md", ".markdown", ".txt", ".csv", ".json", ".rst", ".tex", ".log",
    ".py", ".c", ".h", ".cpp", ".hpp", ".cc", ".java", ".js", ".ts", ".sql",
    ".sh", ".r", ".m", ".go", ".rs", ".ipynb", ".yaml", ".yml",
})
# `.html`/`.xml` ficam FORA de propósito: a defesa do formato de texto é "não
# parece HTML" — que foi o que impediu uma página de login de ser arquivada
# como material quando a A88 abriu os links mesmo-host. Para um `.html`
# declarado essa checagem não existe, e o buraco voltaria pela porta nova.
_OFFICE_EXTS = frozenset({".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"})

# Tipos MIME de Office que o Blackboard reporta em `file.mimeType`. Texto usa
# o prefixo `text/` (inclui `text/x-c`, `text/plain`, `text/markdown`); PDF é
# `application/pdf`. Real incident (2026-09-09, Teoria dos Grafos): três `.cpp`
# autorais com título em prosa ("Código fonte utilizando Structs") e
# `fileName`=`StructExercicio.cpp`/`mimeType`=`text/x-c` não eram nem
# candidatos — `declared_kind` só olhava o sufixo do TÍTULO. Mesma classe da
# A88 (PDF sem `.pdf` no título), um degrau abaixo.
_OFFICE_MIME = frozenset({
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
})


def _kind_from_name(name: str) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in _TEXT_EXTS:
        return "text"
    if suffix in _OFFICE_EXTS:
        return "office"
    return None


def declared_kind(item: dict[str, Any], *, expected_host: str | None = None) -> str | None:
    """Qual FORMATO este item declara ser: 'pdf', 'text', 'office' — ou None.

    Substitui o booleano `is_declared_pdf`: o formato declarado é o que decide
    a assinatura exigida no download (`downloads.verify_signature`) e o teto de
    tamanho. Um booleano não conseguia carregar essa informação adiante, e era
    por isso que o segundo gate só sabia cobrar `%PDF-`.

    Sinais do mais forte pro mais fraco: o `mimeType` e o `fileName` do PRÓPRIO
    registro de arquivo do Blackboard, depois o sufixo do TÍTULO, e por último a
    heurística de link mesmo-host. Um título em prosa não esconde mais um
    `.cpp` cujo arquivo declara `text/x-c`.
    """
    if item.get("kind") != "item":
        return None
    mime = str(item.get("mime_type") or "").strip().lower()
    if mime == "application/pdf":
        return "pdf"
    if mime in _OFFICE_MIME:
        return "office"
    if mime.startswith("text/"):
        return "text"
    file_name = str(item.get("file_name") or "").strip()
    if file_name:
        by_file = _kind_from_name(file_name)
        if by_file is not None:
            return by_file
    title = str(item.get("title") or "").strip()
    by_title = _kind_from_name(title)
    if by_title is not None:
        return by_title
    if expected_host is not None and item.get("content_handler") == "resource/x-bb-externallink":
        url = str(item.get("external_url") or "")
        if url and (urlparse(url).hostname or "").lower() == expected_host.lower():
            return "pdf"
    if "arquivo em pdf" in title.casefold():
        return "pdf"
    return None


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
    expected_host: str | None = None,
) -> dict[str, Any]:
    """Archive every declared PDF once and return a durable, safe report.

    Existing verified receipts are skipped; a failed candidate is recorded so
    the owner can see a gap without treating it as a successful archive.
    """
    candidates = [
        (item, kind)
        for item in items
        if (kind := declared_kind(item, expected_host=expected_host)) is not None
    ]
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for item, kind in candidates:
        content_id = str(item.get("id") or "")
        title = str(item.get("title") or "")
        if not content_id:
            continue
        if verified_receipt(data_home, course_id=course_id, content_id=content_id) is not None:
            skipped.append({"content_id": content_id, "title": title, "reason": "already_verified"})
            continue
        try:
            receipt = await download(course_id, content_id, kind)
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
            "count": len([
                item for item in items
                if item.get("kind") == "item" and not is_declared_pdf(item, expected_host=expected_host)
            ]),
        },
    }
    path = archive_report_path(data_home, course_id)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return report
