"""Links do Blackboard Ultra para o dono abrir direto o que foi avisado.

Só quem conhece o `base_url` da instituição é a bridge, então o link nasce
aqui. Formato da atividade medido na navegação real do dono (2026-09-14,
AS - Unidade I: `/ultra/courses/<curso>/assessment/<content_id>/overview`);
o de avisos, no link "Avisos" da própria disciplina que o dono mandou
(2026-09-15: `/ultra/courses/_1169578_1/announcements`).
"""

from __future__ import annotations

from typing import Any


def course_url(base_url: str, course_id: str) -> str:
    return f"{base_url.rstrip('/')}/ultra/courses/{course_id}/outline"


def activity_url(base_url: str, course_id: str, content_id: str) -> str:
    return f"{base_url.rstrip('/')}/ultra/courses/{course_id}/assessment/{content_id}/overview"


def announcements_url(base_url: str, course_id: str) -> str:
    return f"{base_url.rstrip('/')}/ultra/courses/{course_id}/announcements"


def with_activity_url(base_url: str, row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "url": activity_url(base_url, str(row["course_id"]), str(row["content_id"]))}


def with_announcements_url(base_url: str, row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "url": announcements_url(base_url, str(row["course_id"]))}


__all__ = ["activity_url", "announcements_url", "course_url", "with_activity_url", "with_announcements_url"]
