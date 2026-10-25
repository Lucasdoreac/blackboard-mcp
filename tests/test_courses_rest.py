"""Disciplinas e semestres pela REST (2026-10-24): sem Chrome aberto, sem esconder o que os cartões omitem."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings
from blackboard_mcp.courses_rest import course_rows, term_names

TERMS = {
    "_1068_1": {"name": "2 Semestre 2026", "startDate": "2026-07-01T03:00:00.000Z"},
    "_746_1": {"name": "1º Semestre 2026", "startDate": "2025-11-01T03:00:00.000Z"},
}


def _m(cid: str, name: str, term: str | None, *, org: bool = False, available: bool = True,
       closed: bool = False, code: str = "COD") -> dict:
    course = {"id": cid, "name": name, "courseId": code, "isOrganization": org, "isClosed": closed}
    if term:
        course["termId"] = term
    return {"course": course, "isAvailable": available}


MEMBERSHIPS = [
    _m("_1_1", "Big Data", "_1068_1", code="CVCS_1"),
    _m("_2_1", "Itinerário Extensionista 5", "_1068_1"),  # o cartão do Ultra esconde; a REST traz
    _m("_3_1", "Coordenação", None, org=True),
    _m("_4_1", "Qualidade de Software", "_746_1", available=False),
]


def test_without_a_term_it_returns_the_latest_term_and_never_organizations() -> None:
    rows = course_rows(MEMBERSHIPS, TERMS)
    assert [r["id"] for r in rows] == ["_1_1", "_2_1"]
    assert rows[0] == {"id": "_1_1", "name": "Big Data", "course_code": "CVCS_1",
                       "availability": "Aberto", "term": "2 Semestre 2026"}


def test_a_term_name_selects_exactly_that_term_and_reports_closed_ones() -> None:
    rows = course_rows(MEMBERSHIPS, TERMS, "1º Semestre")
    assert [(r["id"], r["availability"]) for r in rows] == [("_4_1", "Fechado")]


@pytest.mark.parametrize("query", ["semestre 2099", "Semestre"])
def test_unknown_or_ambiguous_term_is_refused(query: str) -> None:
    """Dois semestres casam 'Semestre': escolher um em silêncio devolveria disciplinas erradas."""
    with pytest.raises(ValueError, match="semestre nao encontrado"):
        course_rows(MEMBERSHIPS, TERMS, query)


def test_term_names_come_newest_first() -> None:
    assert term_names(TERMS) == ["2 Semestre 2026", "1º Semestre 2026"]


def _client(tmp_path: Path) -> BlackboardClient:
    return BlackboardClient(Settings(profile="sober", base_url="https://bb.example.edu", data_home=tmp_path))


@pytest.mark.asyncio
async def test_client_lists_courses_by_rest_without_touching_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REVERT-CHECK: com a leitura de página, esta chamada abria o Chrome e falhava sem a janela."""
    client = _client(tmp_path)

    async def fake_rest(path: str, params=None):
        if path.endswith("/memberships"):
            return {"results": MEMBERSHIPS}
        return TERMS[path.rsplit("/", 1)[1]]

    monkeypatch.setattr(client, "_rest_get", fake_rest)
    page = AsyncMock(side_effect=AssertionError("abriu o navegador"))
    monkeypatch.setattr(client, "_authenticated_page", page)

    assert [r["id"] for r in await client.list_courses()] == ["_1_1", "_2_1"]
    assert await client.list_terms() == ["2 Semestre 2026", "1º Semestre 2026"]
    page.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_falls_back_to_the_page_only_when_rest_returns_no_course(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(client, "_rest_get", AsyncMock(return_value={"results": [_m("_9_1", "Org", None, org=True)]}))
    monkeypatch.setattr(client, "_list_courses_from_page", AsyncMock(return_value=[{"id": "_p_1"}]))

    assert await client.list_courses() == [{"id": "_p_1"}]


@pytest.mark.asyncio
async def test_client_pages_through_memberships(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path)
    calls: list[str] = []

    async def fake_rest(path: str, params=None):
        calls.append(params["offset"])
        size = 200 if params["offset"] == "0" else 3
        return {"results": [_m(f"_{params['offset']}_{i}", "C", "_1068_1") for i in range(size)]}

    monkeypatch.setattr(client, "_rest_get", fake_rest)
    assert len(await client._rest_memberships()) == 203
    assert calls == ["0", "200"]
