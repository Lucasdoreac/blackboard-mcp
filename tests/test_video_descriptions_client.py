"""`BlackboardClient.list_video_descriptions` orchestration: real incident
(2026-09-03) — the owner asked to extract lecture video content for
NotebookLM, and this repo's own courses had almost no native video at all,
just embedded genial.ly presentations, some carrying a professor-written
`#paratodosverem` accessibility description right in the page HTML. This
reads that text; it never touches a video player.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings


BASE_HOST = "blackboard.example.edu"


def _client(tmp_path: Path) -> BlackboardClient:
    client = BlackboardClient(
        Settings(profile="test", base_url=f"https://{BASE_HOST}", data_home=tmp_path)
    )
    client._session._cookies = {"BbRouter": "expires:1,timeout:28800,xsrf:tok"}
    return client


_DOC_ROW = {
    "id": "_1_1", "title": "Boas-vindas", "kind": "item", "depth": 1,
    "due_at": None, "mime_type": None, "content_handler": "resource/x-bb-document",
}
_FILE_ROW = {
    "id": "_2_1", "title": "Aula.pdf", "kind": "item", "depth": 1,
    "due_at": None, "mime_type": "application/pdf", "content_handler": "resource/x-bb-file",
}


@pytest.mark.asyncio
async def test_only_opens_document_pages_not_files_or_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW, _FILE_ROW]))
    rest_get = AsyncMock(return_value={"body": {"rawText": "<p>sem marcador aqui</p>"}})
    monkeypatch.setattr(client, "_rest_get", rest_get)

    result = await client.list_video_descriptions("_1189334_1")

    assert result == []
    rest_get.assert_awaited_once_with("/learn/api/v1/courses/_1189334_1/contents/_1_1")


@pytest.mark.asyncio
async def test_extracts_description_directly_from_the_document_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW]))
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value={
        "body": {"rawText": "<p>#paratodosverem: mensagem de boas-vindas em texto.</p>"}
    }))

    result = await client.list_video_descriptions("_1189334_1")

    assert result == [{
        "course_id": "_1189334_1", "content_id": "_1_1",
        "title": "Boas-vindas", "description": "mensagem de boas-vindas em texto.",
    }]


@pytest.mark.asyncio
async def test_follows_a_same_host_embed_when_the_body_itself_has_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    embed_url = f"https://{BASE_HOST}/bbcswebdav/xid-1_1"
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW]))
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value={
        "body": {"rawText": f'<a data-bbtype="embedded-unsafe-html" href="{embed_url}"></a>'}
    }))

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == embed_url
        return httpx.Response(200, text="<p>#paratodosverem: descrição dentro do embed.</p>")

    import blackboard_mcp.client as client_module
    real_client_cls = httpx.AsyncClient

    def fake_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)

    result = await client.list_video_descriptions("_1189334_1")

    assert result == [{
        "course_id": "_1189334_1", "content_id": "_1_1",
        "title": "Boas-vindas", "description": "descrição dentro do embed.",
    }]


@pytest.mark.asyncio
async def test_never_follows_an_embed_pointing_outside_blackboards_own_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check target: without the host check, the session cookies
    (via `client._session._cookies`) would be sent to an arbitrary
    third-party host referenced by a same-shaped embed block."""
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW]))
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value={
        "body": {"rawText": '<a data-bbtype="embedded-unsafe-html" href="https://evil.example/x"></a>'}
    }))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never fetch a cross-host embed URL")

    import blackboard_mcp.client as client_module
    real_client_cls = httpx.AsyncClient

    def fake_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)

    result = await client.list_video_descriptions("_1189334_1")

    assert result == []


@pytest.mark.asyncio
async def test_rejects_an_invalid_course_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with pytest.raises(ValueError, match="course_id invalido"):
        await client.list_video_descriptions("not-a-course-id")
