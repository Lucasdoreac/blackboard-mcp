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
