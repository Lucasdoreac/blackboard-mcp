"""`resource/x-bb-externallink` items (achado real 2026-09-02, `bigdata`
"Arquivo em PDF" materials): a direct authenticated GET on the item's own
URL, not Playwright's click-and-intercept flow, which passes through an
interstitial HTML response that lies about its `content-type`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", data_home=tmp_path))


def _mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import blackboard_mcp.client as client_module
    real_client_cls = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


EXTERNALLINK_ITEM = {
    "id": "_1_1",
    "title": "Arquivo em PDF - Unidade I",
    "contentHandler": "resource/x-bb-externallink",
    "contentDetail": {
        "resource/x-bb-externallink": {"url": "https://bb.cruzeirodosulvirtual.com.br/bbcswebdav/xid-1_1"},
    },
}


@pytest.mark.asyncio
async def test_refuses_a_link_pointing_outside_blackboards_own_host(tmp_path: Path) -> None:
    """Revert-check target: without the host check, this content type
    (ALSO how a professor links to a genuinely external site) would send
    the authenticated session cookies to an arbitrary third-party host."""
    client = _client(tmp_path)
    item = {
        "id": "_1_1", "title": "Video da aula",
        "contentDetail": {"resource/x-bb-externallink": {"url": "https://youtube.com/watch?v=evil"}},
    }
    with pytest.raises(ValueError, match="nao arquivado automaticamente"):
        await client._download_external_link("_1_1", "_1_1", "Video da aula", item)


@pytest.mark.asyncio
async def test_refuses_when_the_url_is_missing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    item = {"id": "_1_1", "title": "x", "contentDetail": {}}
    with pytest.raises(ValueError):
        await client._download_external_link("_1_1", "_1_1", "x", item)


@pytest.mark.asyncio
async def test_downloads_and_persists_a_same_host_webdav_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    client._session._cookies = {"BbRouter": "expires:1,timeout:28800,xsrf:tok"}
    pdf_bytes = b"%PDF-1.4\n" + b"x" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=pdf_bytes, headers={"content-type": "application/pdf"})

    _mock_transport(monkeypatch, handler)
    receipt = await client._download_external_link(
        "_1189334_1", "_23249666_1", "Arquivo em PDF - Unidade I", EXTERNALLINK_ITEM
    )
    assert receipt["sha256"]
    assert receipt["size_bytes"] == len(pdf_bytes)


@pytest.mark.asyncio
async def test_refuses_a_non_pdf_body_even_with_correct_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact real-world failure mode: content-type says PDF, the body
    is an HTML interstitial. `persist_download`'s magic-byte check is what
    actually catches this — this test proves the new download path reuses
    it rather than trusting the header."""
    client = _client(tmp_path)
    client._session._cookies = {"BbRouter": "expires:1,timeout:28800,xsrf:tok"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<!doctype html>\n", headers={"content-type": "application/pdf"})

    _mock_transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="PDF valido"):
        await client._download_external_link(
            "_1189334_1", "_23249666_1", "Arquivo em PDF - Unidade I", EXTERNALLINK_ITEM
        )


@pytest.mark.asyncio
async def test_download_content_dispatches_externallink_items_without_playwright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value=EXTERNALLINK_ITEM))
    monkeypatch.setattr(client, "_download_external_link", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(client, "_download_via_playwright", AsyncMock(side_effect=AssertionError("should not run")))

    result = await client.download_content("_1189334_1", "_23249666_1")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_download_content_keeps_playwright_path_for_regular_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    file_item = {"id": "_1_1", "title": "Plano.pdf", "contentHandler": "resource/x-bb-file"}
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value=file_item))
    monkeypatch.setattr(client, "_download_external_link", AsyncMock(side_effect=AssertionError("should not run")))
    monkeypatch.setattr(client, "_download_via_playwright", AsyncMock(return_value={"ok": True}))

    result = await client.download_content("_1189334_1", "_1_1")
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# `resource/x-bb-file` with a `permanentUrl`: the SAME authenticated GET,
# reached from the item's own REST metadata — no browser, so a stale Chrome
# profile session no longer blocks a download (achado ao vivo 2026-09-08: a
# sessão REST seguia viva pelo keep-alive, mas TODO PDF de aula falhava porque
# o único caminho para `x-bb-file` era o Playwright).
# ---------------------------------------------------------------------------
BASE_HOST = "bb.cruzeirodosulvirtual.com.br"


def _x_bb_file_item(permanent_url: str | None, *, mime: str = "application/pdf") -> dict:
    file_ref: dict = {"fileName": "Aula-05.pdf", "mimeType": mime, "fileSize": 109}
    if permanent_url is not None:
        file_ref["permanentUrl"] = permanent_url
    return {
        "id": "_23707539_1",
        "title": "Aula05_expressoes_regulares.pdf",
        "contentHandler": "resource/x-bb-file",
        "contentDetail": {"resource/x-bb-file": {"file": file_ref}},
    }


def test_file_permanent_url_resolves_and_gates_the_route(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ok = client._file_permanent_url(
        _x_bb_file_item("/bbcswebdav/pid-23707539-dt-content-rid-337056772_1/xid-337056772_1"),
        "_1169577_1",
    )
    assert ok == f"https://{BASE_HOST}/bbcswebdav/pid-23707539-dt-content-rid-337056772_1/xid-337056772_1"

    # No permanentUrl → None (caller falls back to Playwright).
    assert client._file_permanent_url(_x_bb_file_item(None), "_1169577_1") is None
    # Cross-host absolute URL → None: the authenticated cookie never leaves BB.
    assert client._file_permanent_url(
        _x_bb_file_item("https://evil.example.com/bbcswebdav/xid-1_1"), "_1169577_1"
    ) is None
    # Same host but off the closed content-route set → None.
    assert client._file_permanent_url(
        _x_bb_file_item(f"https://{BASE_HOST}/webapps/blackboard/execute/content/file?cmd=view"),
        "_1169577_1",
    ) is None


@pytest.mark.asyncio
async def test_x_bb_file_downloads_via_permanenturl_without_playwright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    client._session._cookies = {"BbRouter": "expires:1,timeout:28800,xsrf:tok"}
    pdf_bytes = b"%PDF-1.7\n" + b"x" * 100
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=pdf_bytes, headers={"content-type": "application/pdf"})

    _mock_transport(monkeypatch, handler)
    monkeypatch.setattr(
        client, "_rest_get",
        AsyncMock(return_value=_x_bb_file_item("/bbcswebdav/pid-23707539-dt-content-rid-337056772_1/xid-337056772_1")),
    )
    monkeypatch.setattr(
        client, "_download_via_playwright",
        AsyncMock(side_effect=AssertionError("browser must not be touched when permanentUrl works")),
    )

    receipt = await client.download_content("_1169577_1", "_23707539_1")
    assert receipt["size_bytes"] == len(pdf_bytes)
    assert seen["url"].endswith("/bbcswebdav/pid-23707539-dt-content-rid-337056772_1/xid-337056772_1")


@pytest.mark.asyncio
async def test_x_bb_file_permanenturl_login_bounce_falls_back_to_playwright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the REST cookie itself finally lapsed, `/bbcswebdav/` answers with a
    login page (200 + HTML). `persist_download`'s signature check rejects it,
    and the download must still fall through to the browser, not error out."""
    client = _client(tmp_path)
    client._session._cookies = {"BbRouter": "expires:1,timeout:28800,xsrf:tok"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<!doctype html>\n<html>login", headers={"content-type": "text/html"})

    _mock_transport(monkeypatch, handler)
    monkeypatch.setattr(
        client, "_rest_get",
        AsyncMock(return_value=_x_bb_file_item("/bbcswebdav/pid-1-dt-content-rid-1_1/xid-1_1")),
    )
    monkeypatch.setattr(client, "_download_via_playwright", AsyncMock(return_value={"ok": "via browser"}))

    result = await client.download_content("_1169577_1", "_23707539_1")
    assert result == {"ok": "via browser"}


@pytest.mark.asyncio
async def test_x_bb_file_permanenturl_carries_the_declared_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.md` handed to `archive_declared_pdfs` arrives here as kind='text';
    the signature check has to run the text rule, not demand `%PDF-`."""
    client = _client(tmp_path)
    client._session._cookies = {"BbRouter": "expires:1,timeout:28800,xsrf:tok"}
    md_bytes = "# Exercícios de Expressões Regulares\n".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=md_bytes, headers={"content-type": "text/markdown"})

    _mock_transport(monkeypatch, handler)
    item = _x_bb_file_item("/bbcswebdav/pid-1-dt-content-rid-1_1/xid-1_1", mime="application/octet-stream")
    item["title"] = "material-estudante-expressoes-regulares-vfinal.md"
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value=item))
    monkeypatch.setattr(
        client, "_download_via_playwright",
        AsyncMock(side_effect=AssertionError("text file downloaded fine via REST")),
    )

    receipt = await client.download_content("_1169577_1", "_23707539_1", "text")
    assert receipt["size_bytes"] == len(md_bytes)
