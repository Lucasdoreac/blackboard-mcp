"""Plain text of a Blackboard `resource/x-bb-document` page body.

An `x-bb-document` is an Ultra "Document" — the professor's own lecture notes,
unit intro, or instructions, written straight into the page (no attachment).
Real course content, and until now captured nowhere: `archive.py` only takes
files, `video_descriptions.py` only takes the `#paratodosverem` snippet.

`body.rawText` is Blackboard's own plain-text rendering of the body when it
exists; otherwise the HTML (`body.displayText` / `body.html`) is stripped.
Nothing here fetches a URL or opens an embed — it only reads text the page
API already returns.
"""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|li|h[1-6]|tr)\b[^>]*>", re.IGNORECASE)
_WS_RE = re.compile(r"[ \t ]+")
_BLANKS_RE = re.compile(r"\n\s*\n\s*\n+")
# Ruído estrutural que o Ultra injeta em toda página, sem valor de conteúdo.
_NOISE_RE = re.compile(
    r"ultraDocumentBody|\bdata-[a-z-]+=|bb-emoji|s3\.amazonaws|xid-\d+",
    re.IGNORECASE,
)
_MIN_CHARS = 200


def clean_document_body(raw_text: str | None, display_html: str | None) -> str | None:
    """Best plain text of a document body, or None when there is too little
    to be worth a source. `raw_text` (Blackboard's own plain rendering) wins;
    the HTML is only stripped when `raw_text` is empty."""
    if raw_text and raw_text.strip():
        text = raw_text
    elif display_html and display_html.strip():
        text = display_html
    else:
        return None
    if _TAG_RE.search(text):
        # O `rawText` do editor novo do Ultra (bbml) também vem em HTML — achado
        # na SOBER (2026-09-15): páginas subiram ao NotebookLM como
        # `<div data-layout-row=…>`. Tag é sempre removida, venha de onde vier.
        text = _BLOCK_TAG_RE.sub("\n", text)
        text = html.unescape(_TAG_RE.sub(" ", text))
    if _NOISE_RE.search(text):
        # Texto que veio só com lixo estrutural (sem prosa) — descarta.
        stripped = _NOISE_RE.sub(" ", text)
        if len(_WS_RE.sub(" ", stripped).strip()) < _MIN_CHARS:
            return None
    text = _WS_RE.sub(" ", text)
    text = _BLANKS_RE.sub("\n\n", text).strip()
    return text if len(text) >= _MIN_CHARS else None


_NON_CONTENT_RE = re.compile(r"(?is)<(script|style|head|noscript|svg)\b.*?</\1>")
_MAX_EMBEDDED_CHARS = 500_000


def clean_embedded_html(page_html: str) -> str | None:
    """Plain text of a professor-uploaded HTML file embedded in a document page
    (`embedded-unsafe-html`). Real incident (2026-09-29): an activity brief
    published ONLY as such a file — the page's own body has no text — so the
    course looked empty. Scripts/styles/head are dropped before the usual
    cleaning; the input is capped so a huge file cannot balloon a source."""
    return clean_document_body(None, _NON_CONTENT_RE.sub(" ", page_html[:_MAX_EMBEDDED_CHARS]))


__all__ = ["clean_document_body", "clean_embedded_html"]
