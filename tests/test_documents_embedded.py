"""`list_course_documents` lê o arquivo HTML embutido quando a página não tem
texto próprio. Incidente real (2026-09-29): o enunciado de uma atividade remota
foi publicado SÓ como `embedded-unsafe-html` — a página parecia vazia, o curso
parecia sem dever e o SOBER dizia "nenhuma atividade"."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

import blackboard_mcp.client as client_module
from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.document_text import clean_embedded_html

BASE_HOST = "blackboard.example.edu"
_DOC_ROW = {
    "id": "_1_1", "title": "Aula 09", "kind": "item", "depth": 1,
    "due_at": None, "mime_type": None, "content_handler": "resource/x-bb-document",
}
_PROSE = "Etapa 1 responda as questões sobre máquinas de Turing e envie um único arquivo em PDF. " * 4


def _client(tmp_path: Path) -> BlackboardClient:
    client = BlackboardClient(Settings(profile="test", base_url=f"https://{BASE_HOST}", data_home=tmp_path))
    client._session._cookies = {"BbRouter": "expires:1,timeout:28800,xsrf:tok"}
    return client


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = httpx.AsyncClient

    def fake(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake)


def _embed_body(url: str) -> dict:
    return {"body": {"rawText": f'<a data-bbtype="embedded-unsafe-html" href="{url}"></a>'}}


def test_clean_embedded_html_drops_scripts_and_styles() -> None:
    page = f"<html><head><style>p{{}}</style></head><body><script>x()</script><p>{_PROSE}</p></body></html>"
    text = clean_embedded_html(page)
    assert text is not None and "Etapa 1" in text and "x()" not in text and "p{}" not in text


@pytest.mark.asyncio
async def test_reads_the_embedded_html_file_when_the_page_has_no_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    url = f"https://{BASE_HOST}/bbcswebdav/xid-1_1"
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW]))
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value=_embed_body(url)))
    _patch_http(monkeypatch, lambda request: httpx.Response(200, text=f"<body><p>{_PROSE}</p></body>"))

    result = await client.list_course_documents("_1169577_1")

    assert [r["content_id"] for r in result] == ["_1_1"] and "único arquivo" in result[0]["text"]


@pytest.mark.asyncio
async def test_never_follows_an_embed_outside_the_blackboard_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check: sem a checagem de host, os cookies da sessão iriam a um host arbitrário."""
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW]))
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value=_embed_body("https://evil.example.com/x")))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("não pode buscar fora do host do Blackboard")

    _patch_http(monkeypatch, handler)

    assert await client.list_course_documents("_1169577_1") == []


@pytest.mark.asyncio
async def test_a_page_with_its_own_text_never_fetches_the_embed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "list_course_tree", AsyncMock(return_value=[_DOC_ROW]))
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value={"body": {"rawText": _PROSE}}))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("página com texto próprio não busca o embed")

    _patch_http(monkeypatch, handler)

    assert len(await client.list_course_documents("_1169577_1")) == 1
