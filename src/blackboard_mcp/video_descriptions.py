"""Extract owner-facing accessibility descriptions of embedded video/interactive
content from a Blackboard document page.

`#paratodosverem` ("for everyone to see") is the Brazilian screen-reader-
accessibility convention: alongside an embedded video or interactive
presentation (genial.ly, an institutional player, ...), the professor writes
a plain-text description of what the media shows, so it is legible without
playing it. This module only ever reads that already-written text — it never
opens a video player, follows a streaming manifest, or scrapes a third-party
embed (genial.ly, YouTube, ...). A page with no `#paratodosverem` marker
yields nothing; that is a correct "no accessible description available"
result, never an error.
"""

from __future__ import annotations

import html
import re

_MARKER_RE = re.compile(r"#\s*paratodosverem\s*:?", re.IGNORECASE)
_BLOCK_END_RE = re.compile(r"</p>|</div>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)


def extract_paratodosverem(body_html: str) -> str | None:
    """Return the accessibility description text after a `#paratodosverem`
    marker in one HTML fragment, or None if the marker is absent.

    The description is bounded by the first `</p>` or `</div>` after the
    marker (matches every real sample seen: the marker and its prose share
    one block-level element with the embed that follows).
    """
    match = _MARKER_RE.search(body_html)
    if match is None:
        return None
    tail = body_html[match.end():]
    end = _BLOCK_END_RE.search(tail)
    fragment = tail[: end.start()] if end else tail
    text = _TAG_RE.sub(" ", fragment)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def find_embedded_html_urls(body_html: str) -> list[str]:
    """Return the `href` of every `<a data-bbtype="embedded-unsafe-html">`
    block in one HTML fragment — Blackboard's own mechanism for nesting a
    professor-uploaded HTML snippet (often the actual video/genial.ly embed)
    inside a document page. Caller must still verify the URL stays on the
    Blackboard host before fetching it — this function does no validation.
    """
    urls: list[str] = []
    for tag in _ANCHOR_RE.findall(body_html):
        if "embedded-unsafe-html" not in tag:
            continue
        found = _HREF_RE.search(tag)
        if found:
            urls.append(html.unescape(found.group(1)))
    return urls


__all__ = ["extract_paratodosverem", "find_embedded_html_urls"]
