"""`get_assessment` / `read_assessment_attachment` — enunciado de atividade.

Fixture no formato medido ao vivo em 2026-09-14 (Computabilidade, "02 - Tempo
de execução"): `Assignment` com `questionCount` 0, questões numeradas no
`instructions.rawText` e prints de código como `<a data-bbfile=...>`.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from blackboard_mcp.assessment_detail import extract_instructions, parse_assessment_detail, public_view, sniff_image
from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings

BASE = "https://bb.example.edu"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _bbfile(name: str, href: str) -> str:
    meta = html.escape(json.dumps({"fileName": name, "displayName": name, "mimeType": "image/png", "fileSize": 40}))
    return f'<a href="{href}" data-bbtype="attachment" data-bbfile="{meta}">{name}</a>'


RAW = (
    "<p>1. Determine a complexidade de tempo do trecho abaixo.</p>"
    + _bbfile("Captura 1.png", f"{BASE}/bbcswebdav/pid-1-dt-asiobject-rid-2_1/xid-2_1")
    + "<p>2. Analise o algoritmo &amp; determine a complexidade.</p>"
    + _bbfile("Captura 2.png", "/bbcswebdav/pid-1-dt-asiobject-rid-3_1/xid-3_1")
)


def _item(raw: str = RAW, **overrides) -> dict:
    item = {
        "title": "02 - Tempo de execução",
        "contentHandler": "resource/x-bb-asmt-test-link",
        "visibility": "VISIBLE",
        "genericReadOnlyData": {"dueDate": "2026-08-24T02:59:00.000Z"},
        "contentDetail": {"resource/x-bb-asmt-test-link": {"test": {
            "assessment": {"subtype": "Assignment", "questionCount": 0, "totalPoints": 0.0,
                           "instructions": {"rawText": raw}, "description": {"rawText": ""}},
            "deploymentSettings": {"attemptCount": 2, "allowTextSubmission": True,
                                   "allowFileSubmission": True, "isLateAttemptCreationDisallowed": True},
        }}},
    }
    item.update(overrides)
    return item


def test_instructions_keep_question_order_with_an_attachment_marker_in_place() -> None:
    text, attachments = extract_instructions(RAW, BASE)
    assert text.index("1. Determine") < text.index("[anexo 1: Captura 1.png]") < text.index("2. Analise") \
        < text.index("[anexo 2: Captura 2.png]")
    assert "&amp;" not in text and "algoritmo & determine" in text
    assert [a["file_name"] for a in attachments] == ["Captura 1.png", "Captura 2.png"]
    assert attachments[1]["_url"] == f"{BASE}/bbcswebdav/pid-1-dt-asiobject-rid-3_1/xid-3_1"  # relativo resolvido


def test_parse_exposes_what_a_draft_needs_and_the_tool_hides_internal_urls() -> None:
    detail = parse_assessment_detail("_9_1", "_8_1", _item(), BASE)
    assert detail["kind"] == "Assignment" and detail["visible"] is True
    assert detail["attempts_allowed"] == 2 and detail["allow_text_submission"] is True
    assert detail["due_at"] == "2026-08-24T02:59:00.000Z"
    assert all("_url" not in a for a in public_view(detail)["attachments"])


def test_non_assessment_content_is_refused() -> None:
    with pytest.raises(ValueError, match="nao e uma atividade"):
        parse_assessment_detail("_9_1", "_8_1", _item(contentHandler="resource/x-bb-document"), BASE)


def test_sniff_image_proves_by_magic_byte_not_by_name() -> None:
    assert sniff_image(PNG) == "image/png"
    assert sniff_image(b"<html>login</html>") is None


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str, handler) -> BlackboardClient:
    import blackboard_mcp.client as client_module

    client = BlackboardClient(Settings(profile="sober", base_url=BASE, data_home=tmp_path))
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value=_item(raw)))
    real = httpx.AsyncClient

    def fake(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake)
    return client


@pytest.mark.asyncio
async def test_attachment_returns_proven_image_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, RAW, lambda req: httpx.Response(200, content=PNG))
    out = await client.read_assessment_attachment("_9_1", "_8_1", 2)
    assert out["mime_type"] == "image/png" and out["file_name"] == "Captura 2.png" and out["size_bytes"] == len(PNG)


@pytest.mark.asyncio
async def test_attachment_on_another_host_never_receives_the_cookie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check: sem a checagem de host, o GET com cookie de sessão iria
    para o host do anexo."""
    hits: list[str] = []
    raw = _bbfile("x.png", "https://evil.example.com/bbcswebdav/x")
    client = _client(tmp_path, monkeypatch, raw, lambda req: (hits.append(str(req.url)), httpx.Response(200, content=PNG))[1])
    with pytest.raises(ValueError, match="nao aponta para o proprio Blackboard"):
        await client.read_assessment_attachment("_9_1", "_8_1", 1)
    assert hits == []


@pytest.mark.asyncio
async def test_login_page_instead_of_image_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch, RAW, lambda req: httpx.Response(200, content=b"<html>login</html>"))
    with pytest.raises(ValueError, match="nao e imagem"):
        await client.read_assessment_attachment("_9_1", "_8_1", 1)


ALT = "https://alt-abc123.blackboard.com/bbcswebdav/pid-1-dt-asiobject-rid-3_1/xid-3_1"


@pytest.mark.asyncio
async def test_follows_blackboards_alt_host_chain_sending_the_session_cookie_only_on_the_first_hop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cadeia real de 2026-09-14: instituição → `alt-<id>.blackboard.com?hash=`
    → si mesmo → PNG. Revert-check: com `follow_redirects=True` e o jar de
    sessão, o cookie `BbRouter` chega ao host `alt-*` (e o anexo falhava na
    checagem de rota final)."""
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.host, req.headers.get("cookie", "")))
        if req.url.host == "bb.example.edu":
            return httpx.Response(302, headers={"location": ALT + "?hash=abc"})
        if "hash" in str(req.url):
            return httpx.Response(302, headers={"location": ALT})
        return httpx.Response(200, content=PNG)

    client = _client(tmp_path, monkeypatch, RAW, handler)
    client._session._cookies = {"BbRouter": "expires:9,xsrf:x"}
    out = await client.read_assessment_attachment("_9_1", "_8_1", 2)
    assert out["mime_type"] == "image/png"
    assert [host for host, _ in seen] == ["bb.example.edu", "alt-abc123.blackboard.com", "alt-abc123.blackboard.com"]
    assert "BbRouter" in seen[0][1] and all("BbRouter" not in cookie for _, cookie in seen[1:])


@pytest.mark.asyncio
async def test_redirect_off_blackboard_hosts_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "bb.example.edu":
            return httpx.Response(302, headers={"location": "https://login.example-idp.com/sso?next=x"})
        raise AssertionError("seguiu redirect para fora do Blackboard")

    client = _client(tmp_path, monkeypatch, RAW, handler)
    with pytest.raises(ValueError, match="redirecionou para fora"):
        await client.read_assessment_attachment("_9_1", "_8_1", 1)
