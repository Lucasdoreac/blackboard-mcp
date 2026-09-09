"""`x-bb-document` page body → texto — o conteúdo autoral que o professor
escreve direto na página (notas de aula, intro de unidade)."""

from __future__ import annotations

from blackboard_mcp.document_text import clean_document_body


def test_prefere_rawtext_quando_existe() -> None:
    txt = clean_document_body("Notas da Aula 3.\n\n" + "Gramáticas livres de contexto. " * 20, "<p>ignorar</p>")
    assert txt is not None and txt.startswith("Notas da Aula 3.")
    assert "<p>" not in txt


def test_tira_html_quando_nao_ha_rawtext() -> None:
    html = "<h1>Unidade I</h1><p>" + "Introdução ao modelo relacional. " * 15 + "</p>"
    txt = clean_document_body(None, html)
    assert txt is not None
    assert "<h1>" not in txt and "Unidade I" in txt and "modelo relacional" in txt


def test_pagina_curta_ou_vazia_vira_none() -> None:
    assert clean_document_body("", "") is None
    assert clean_document_body(None, None) is None
    assert clean_document_body("oi", None) is None
    assert clean_document_body(None, "<p>curto</p>") is None


def test_rawtext_so_com_lixo_estrutural_vira_none() -> None:
    assert clean_document_body("ultraDocumentBody data-bbid=123 xid-999", None) is None


def test_colapsa_espaco_e_linhas_em_branco() -> None:
    txt = clean_document_body("Linha um.\n\n\n\n\nLinha dois com   espaços." + " palavra" * 40, None)
    assert txt is not None
    assert "\n\n\n" not in txt and "   " not in txt
