"""Pure parsing for a Kaltura caption track (WebVTT over an HLS playlist).

Real incident (2026-09-04): the owner pointed out that every "Unidade" PDF
in a Blackboard course has a companion lecture video, embedded via a Kaltura
player (`#player-gui`, `playkit-*` classes — confirmed live). Kaltura already
generates a caption track for these; fetching it is a plain authenticated GET
(no video download, no third-party scraping, no audio processing) that reuses
the SAME browser session the rest of this project already trusts.

Kaltura's `serveWebVTT` endpoint returns an HLS-style playlist (`#EXTM3U`),
not the caption text itself — each real segment is a further `segmentIndex/
N.vtt` fetch, resolved relative to the playlist's own URL. This module only
parses text already fetched by the caller; it does no I/O and does not know
about the `ks` session token or Kaltura's session API.

Real incident (2026-09-04, follow-up): passively waiting for the player to
request `serveWebVTT` on its own missed a real, ready caption — Kaltura's own
`caption_captionasset::list` action confirmed a `status: 2` ("READY") asset
that the player never auto-requested because its `displayOnPlayer` flag is
`false` (the student would have to click the player's own CC button; this
project never simulates UI clicks on a 3rd-party player). The fix queries
Kaltura's caption list directly (same domain, a session token minted the same
way the player already does) instead of waiting for the player's own choice —
`extract_kaltura_ids` and `select_ready_caption_asset` are the pure pieces of
that: identifying which video is on the page, and which of its caption
assets is actually usable, from data the caller already fetched.
"""

from __future__ import annotations

import html
import re
from typing import Any

_ARROW_RE = re.compile(r"^\s*\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")
_CUE_ID_RE = re.compile(r"^\s*\d+\s*$")
_ENTRY_ID_RE = re.compile(r"[?&]entry_id=([^&]+)|/entryId/([^/&]+)")
_PARTNER_ID_RE = re.compile(r"[?&]partner_id=(\d+)|/p/(\d+)/")
_READY_STATUS = 2


def parse_vtt_playlist(m3u8_text: str) -> list[str]:
    """Return the ordered segment paths of an HLS-style VTT playlist —
    every non-comment, non-blank line, in file order. Empty (not an error)
    when the text isn't a real `#EXTM3U` playlist — real incident
    (2026-09-04): a malformed request URL made Kaltura answer `200 OK` with
    an XML error body instead of an HTTP error; without this guard, every
    line of that XML would be misread as a "segment path" to fetch next."""
    if not m3u8_text.lstrip().startswith("#EXTM3U"):
        return []
    return [line.strip() for line in m3u8_text.splitlines() if line.strip() and not line.startswith("#")]


def parse_vtt_cues(vtt_text: str) -> str:
    """Return the plain, continuous transcript text of one WebVTT segment.

    Skips the `WEBVTT` header, any numeric cue-id line, and every timestamp
    (`-->`) line; unescapes HTML entities Kaltura's auto-captions carry
    (`&gt;&gt;` for a speaker-change marker, seen in real captions). Empty
    (not an error) when the text isn't real WebVTT — same defense as
    `parse_vtt_playlist` against a `200 OK` XML error body.
    """
    if not vtt_text.lstrip().startswith("WEBVTT"):
        return ""
    lines: list[str] = []
    for raw_line in vtt_text.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "STYLE")):
            continue
        if _ARROW_RE.match(line) or _CUE_ID_RE.match(line):
            continue
        lines.append(html.unescape(line))
    text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()


def extract_kaltura_ids(url: str) -> tuple[str | None, str | None]:
    """Return (entry_id, partner_id) found in one Kaltura-related request
    URL, or (None, None) — both id shapes seen live (query-string on the
    embed bootstrap, path segment on CDN/API calls)."""
    entry_id = None
    match = _ENTRY_ID_RE.search(url)
    if match:
        entry_id = match.group(1) or match.group(2)
    partner_id = None
    match = _PARTNER_ID_RE.search(url)
    if match:
        partner_id = match.group(1) or match.group(2)
    return entry_id, partner_id


def select_ready_caption_asset(captions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the caption asset to actually fetch: only `status == 2` ("READY")
    assets are usable — Kaltura keeps deleted/superseded ones (`status: -1`)
    in the same list. Among ready ones, prefer `isDefault`, else the first —
    this project never presents a language choice, it just wants the best
    single transcript available.
    """
    ready = [c for c in captions if c.get("status") == _READY_STATUS]
    if not ready:
        return None
    for caption in ready:
        if caption.get("isDefault"):
            return caption
    return ready[0]


__all__ = ["parse_vtt_playlist", "parse_vtt_cues", "extract_kaltura_ids", "select_ready_caption_asset"]
