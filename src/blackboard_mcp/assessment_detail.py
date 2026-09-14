"""Detalhe de UMA atividade (`resource/x-bb-asmt-test-link`) — só leitura.

Achado ao vivo (2026-09-14): numa atividade do subtipo `Assignment` o
enunciado inteiro vive em `assessment.instructions.rawText` (HTML), com as
questões numeradas e os prints de código como anexos embutidos
(`<a data-bbfile=...>`). `questionCount` é 0 nesse caso — não há banco de
questões, e o endpoint `/assessments/{id}/questions` responde 403 para aluno.
Um `Test` com questões (ex.: "AS - Unidade I") só expõe as questões DENTRO de
uma tentativa, o que consome tentativa — nada aqui abre tentativa.

Este módulo é puro: recebe o JSON que o REST já devolveu e produz o texto do
enunciado (com marcador `[anexo N: nome]` na posição de cada anexo) e a lista
de anexos. A URL de cada anexo fica interna (`_url`) e só é seguida pelo
client depois de provar mesmo host + rota `/bbcswebdav/`.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

ASSESSMENT_HANDLER = "resource/x-bb-asmt-test-link"

_BBFILE_ANCHOR_RE = re.compile(
    r"<a\b(?P<attrs>[^>]*\bdata-bbfile=\"[^\"]*\"[^>]*)>(?:.*?</a>)?", re.IGNORECASE | re.DOTALL
)
_ATTR_RE = re.compile(r"([\w-]+)=\"([^\"]*)\"")
_BREAK_RE = re.compile(r"<\s*(?:br|/p|/div|/li|/h[1-6]|/tr)\b[^>]*>", re.IGNORECASE)
_LI_RE = re.compile(r"<\s*li\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"[ \t ]+")
_BLANKS_RE = re.compile(r"\n\s*\n+")


def _raw(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("rawText") or value.get("displayText") or "")
    return str(value or "")


def _html_to_text(fragment: str) -> str:
    text = _LI_RE.sub("\n- ", fragment)
    text = _BREAK_RE.sub("\n", text)
    text = html.unescape(_TAG_RE.sub(" ", text))
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def extract_instructions(raw_html: str, base_url: str) -> tuple[str, list[dict[str, Any]]]:
    """Texto do enunciado + anexos em ordem de aparição."""
    attachments: list[dict[str, Any]] = []

    def _replace(match: re.Match[str]) -> str:
        attrs = dict(_ATTR_RE.findall(match.group("attrs")))
        try:
            meta = json.loads(html.unescape(attrs.get("data-bbfile", "")))
        except (json.JSONDecodeError, TypeError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        index = len(attachments) + 1
        name = str(meta.get("fileName") or meta.get("displayName") or f"anexo-{index}")
        size = meta.get("fileSize")
        attachments.append({
            "index": index,
            "file_name": name,
            "mime_type": str(meta.get("mimeType") or ""),
            "size_bytes": size if isinstance(size, int) else None,
            "_url": urljoin(base_url.rstrip("/") + "/", html.unescape(attrs.get("href", "")).lstrip("/"))
            if attrs.get("href") else "",
        })
        return f"\n[anexo {index}: {name}]\n"

    body = _BBFILE_ANCHOR_RE.sub(_replace, raw_html)
    return _html_to_text(body), attachments


def is_same_host_file_route(url: str, base_url: str) -> bool:
    parsed, expected = urlparse(url), urlparse(base_url)
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == (expected.hostname or "").lower()
        and parsed.path.startswith("/bbcswebdav/")
    )


def is_blackboard_redirect_hop(url: str, base_url: str) -> bool:
    """Salto de redirect aceitável para um anexo: https, rota `/bbcswebdav/`,
    no host da instituição ou num host `*.blackboard.com` (o `alt-<id>` que o
    próprio Blackboard usa para servir arquivo com `hash` assinado)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.path.startswith("/bbcswebdav/")
        and (host == (urlparse(base_url).hostname or "").lower() or host.endswith(".blackboard.com"))
    )


def parse_assessment_detail(
    course_id: str, content_id: str, item: dict[str, Any], base_url: str
) -> dict[str, Any]:
    """Visão estável de uma atividade; anexos ainda carregam `_url` interno."""
    if str(item.get("contentHandler") or "") != ASSESSMENT_HANDLER:
        raise ValueError("o conteudo nao e uma atividade (x-bb-asmt-test-link)")
    test = ((item.get("contentDetail") or {}).get(ASSESSMENT_HANDLER) or {}).get("test") or {}
    assessment = test.get("assessment") or {}
    deploy = test.get("deploymentSettings") or {}
    question_count = assessment.get("questionCount")
    subtype = assessment.get("subtype")
    kind = str(subtype) if subtype else ("Test" if isinstance(question_count, int) and question_count > 0 else "Unknown")
    instructions_text, attachments = extract_instructions(_raw(assessment.get("instructions")), base_url)
    description_text, _ = extract_instructions(_raw(assessment.get("description")), base_url)
    return {
        "course_id": course_id,
        "content_id": content_id,
        "title": str(item.get("title") or ""),
        "due_at": str((item.get("genericReadOnlyData") or {}).get("dueDate") or ""),
        "visible": str(item.get("visibility") or "") == "VISIBLE",
        "kind": kind,
        "question_count": question_count if isinstance(question_count, int) else None,
        "total_points": assessment.get("totalPoints"),
        "attempts_allowed": deploy.get("attemptCount"),
        "allow_text_submission": bool(deploy.get("allowTextSubmission")),
        "allow_file_submission": bool(deploy.get("allowFileSubmission")),
        "late_attempts_blocked": bool(deploy.get("isLateAttemptCreationDisallowed")),
        "instructions_text": instructions_text,
        "description_text": description_text,
        "attachments": attachments,
    }


def activity_ids(tree_rows: list[dict[str, Any]]) -> list[str]:
    """Toda atividade da árvore pelo TIPO, com ou sem prazo — `extract_assessments`
    filtra por `due_at` e perde atividade sem data."""
    return [str(row["id"]) for row in tree_rows if row.get("content_handler") == ASSESSMENT_HANDLER and row.get("id")]


def public_view(detail: dict[str, Any]) -> dict[str, Any]:
    """O que sai pela tool: sem a URL interna dos anexos."""
    return {
        **detail,
        "attachments": [{k: v for k, v in a.items() if not k.startswith("_")} for a in detail["attachments"]],
    }


_IMAGE_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


def sniff_image(payload: bytes) -> str | None:
    """Tipo provado por magic byte; WEBP é RIFF....WEBP."""
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime in _IMAGE_MAGIC.items():
        if payload.startswith(magic):
            return mime
    return None


__all__ = [
    "ASSESSMENT_HANDLER", "activity_ids", "extract_instructions", "is_blackboard_redirect_hop", "is_same_host_file_route",
    "parse_assessment_detail", "public_view", "sniff_image",
]
