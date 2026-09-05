"""Acervo deixa de ser cego a formato — e o segundo gate acompanha.

Achado do dono (2026-09-05): "eu estudo computação, hora vem py, hora cpp,
hora .c". O acervo só reconhecia PDF, então esses arquivos nunca eram sequer
CANDIDATOS a download — o problema não era extração, era candidatura.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from blackboard_mcp.archive import declared_kind, is_declared_pdf
from blackboard_mcp.downloads import verify_signature


def _item(title: str, **extra) -> dict:
    return {"kind": "item", "id": "_1_1", "title": title, **extra}


@pytest.mark.parametrize(
    "titulo,esperado",
    [
        ("Aula 01.pdf", "pdf"), ("Arquivo em PDF - Unidade I", "pdf"),
        ("resumo.md", "text"), ("lista.py", "text"), ("main.cpp", "text"),
        ("kernel.c", "text"), ("consulta.sql", "text"), ("notebook.ipynb", "text"),
        ("planilha.xlsx", "office"), ("slides.pptx", "office"),
        ("Videoaula 3", None), ("aula.mp4", None), ("pagina.html", None),
    ],
)
def test_declared_kind_por_titulo(titulo: str, esperado) -> None:
    assert declared_kind(_item(titulo)) == esperado


def test_mime_type_continua_mandando_mais_que_o_titulo() -> None:
    assert declared_kind(_item("Aula02_sem_extensao", mime_type="application/pdf")) == "pdf"


def test_is_declared_pdf_continua_valendo_para_quem_ja_chamava() -> None:
    assert is_declared_pdf(_item("Aula.pdf")) is True
    assert is_declared_pdf(_item("Videoaula 3")) is False


def test_html_fica_fora_de_proposito() -> None:
    """Para `.html` a defesa do formato de texto ('não parece HTML') não teria
    como existir — e foi HTML de login que a A88 barrou."""
    assert declared_kind(_item("material.html")) is None


def test_assinatura_de_texto_recusa_pagina_de_login(tmp_path: Path) -> None:
    """A checagem de magic bytes nunca foi sobre PDF: é sobre o byte bater com
    o que foi declarado. Generalizada, jamais removida."""
    alvo = tmp_path / "resumo.md"
    alvo.write_bytes(b"<!DOCTYPE html>\n<html><body>Entrar</body></html>")
    with pytest.raises(ValueError, match="pagina de login"):
        verify_signature(alvo, "text")


def test_assinatura_aceita_texto_de_verdade(tmp_path: Path) -> None:
    alvo = tmp_path / "main.cpp"
    alvo.write_bytes("#include <iostream>\n// acentuação\n".encode("utf-8"))
    verify_signature(alvo, "text")


def test_assinatura_de_pdf_e_office_continuam_exigindo_magic(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"nao sou pdf")
    with pytest.raises(ValueError, match="PDF"):
        verify_signature(pdf, "pdf")
    doc = tmp_path / "a.xlsx"; doc.write_bytes(b"nao sou zip")
    with pytest.raises(ValueError, match="Office"):
        verify_signature(doc, "office")
    doc.write_bytes(b"PK\x03\x04resto")
    verify_signature(doc, "office")


# ---------------------------------------------------------------------------
# Terceiro gate: a ROTA (nunca foi sobre formato)
# ---------------------------------------------------------------------------
from blackboard_mcp.client import _is_blackboard_content_route


@pytest.mark.parametrize(
    "rota,aceita",
    [
        ("/ultra/courses/_1169577_1/outline/file/_123_1", True),
        ("/bbcswebdav/pid-23612017-dt-content-rid-335271614_1/xid-335271614_1", True),
        ("/ultra/courses/_OUTRO_1/outline/file/_123_1", False),
        ("/webapps/blackboard/execute/content/file", False),
        ("//evil.example.com/x", False),
        ("/", False),
    ],
)
def test_rota_de_download_e_conjunto_fechado(rota: str, aceita: bool) -> None:
    """Medido ao vivo (2026-09-05): o `.md` autoral do professor vive em
    `/bbcswebdav/`, não em `/ultra/courses/`. O gate original barrava TODO
    arquivo subido por quem dá a aula — não por formato, por rota."""
    assert _is_blackboard_content_route(rota, "_1169577_1") is aceita


# ---------------------------------------------------------------------------
# Quarto gate: a CAPTURA (PDF da CDN x Download event)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_captura_aceita_download_event_alem_da_resposta_da_cdn() -> None:
    """O código esperava só a resposta PDF da CDN — verdade para o PDF
    institucional, falso para arquivo AUTORAL do professor, que dispara um
    Download event de verdade.

    Sintoma medido ao vivo (2026-09-05): o `.md` baixava (8669 bytes no
    diretório temporário do Playwright) e o future nunca resolvia — morria em
    TimeoutError com o arquivo já em disco. Aqui provamos a corrida: com
    APENAS o download resolvendo, `asyncio.wait` devolve o vencedor em vez de
    estourar o teto.
    """
    import asyncio as aio

    loop = aio.get_running_loop()
    resposta_cdn: aio.Future = loop.create_future()   # nunca resolve (é o caso do .md)
    baixado: aio.Future = loop.create_future()
    baixado.set_result("download-event")

    pronto, pendentes = await aio.wait(
        {resposta_cdn, baixado}, timeout=1, return_when=aio.FIRST_COMPLETED
    )
    for t in pendentes:
        t.cancel()
    assert pronto and pronto.pop().result() == "download-event"
