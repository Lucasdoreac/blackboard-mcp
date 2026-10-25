"""Disciplinas e semestres pela REST interna do Blackboard, sem navegador.

`/learn/api/v1/users/me/memberships?expand=course` devolve todas as matrículas do usuário; os
semestres vêm de `/learn/api/v1/terms/{id}`. O mesmo cookie do `session.json` que já serve a árvore
de conteúdo basta: não há Chrome aberto por usuário (~1 GiB cada), e o Ultra deixa de esconder
disciplinas que os cartões da página omitem.
"""

from __future__ import annotations

from typing import Any


def is_course(membership: dict[str, Any]) -> bool:
    course = membership.get("course")
    return isinstance(course, dict) and bool(course.get("id")) and not course.get("isOrganization")


def term_ids(memberships: list[dict[str, Any]]) -> set[str]:
    return {str(m["course"]["termId"]) for m in memberships if is_course(m) and m["course"].get("termId")}


def term_names(terms: dict[str, dict[str, Any]]) -> list[str]:
    """Nomes dos semestres, do mais recente ao mais antigo (a ordem do filtro do Ultra)."""
    ordered = sorted(terms.values(), key=lambda t: str(t.get("startDate") or ""), reverse=True)
    names: list[str] = []
    for term in ordered:
        name = str(term.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _select_term(terms: dict[str, dict[str, Any]], query: str | None) -> str | None:
    if query:
        wanted = query.casefold()
        found = [tid for tid, t in terms.items() if wanted in str(t.get("name") or "").casefold()]
        if len(found) != 1:
            raise ValueError(f"semestre nao encontrado: {query}")
        return found[0]
    if not terms:
        return None
    return max(terms, key=lambda tid: str(terms[tid].get("startDate") or ""))


def course_rows(
    memberships: list[dict[str, Any]], terms: dict[str, dict[str, Any]], query: str | None = None
) -> list[dict[str, str]]:
    """Disciplinas do semestre pedido; sem pedido, as do semestre mais recente com disciplinas."""
    wanted = _select_term(terms, query)
    rows: list[dict[str, str]] = []
    for membership in memberships:
        if not is_course(membership):
            continue
        course = membership["course"]
        if wanted is not None and str(course.get("termId") or "") != wanted:
            continue
        open_now = membership.get("isAvailable") is True and not course.get("isClosed")
        rows.append({
            "id": str(course["id"]),
            "name": str(course.get("name") or course.get("displayName") or ""),
            "course_code": str(course.get("courseId") or ""),
            "availability": "Aberto" if open_now else "Fechado",
            "term": str(terms.get(str(course.get("termId") or ""), {}).get("name") or ""),
        })
    return rows
