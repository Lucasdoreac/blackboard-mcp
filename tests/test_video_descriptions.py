from blackboard_mcp.video_descriptions import extract_paratodosverem, find_embedded_html_urls

_REAL_SHAPE_HTML = (
    '<script class="bb-embedded-html bb-auto-resize" type="text/javascript">'
    "window.addEventListener('load', () => {});</script>"
    '<p style="text-align: justify;"><span style="color: #000000;">'
    "<strong>#paratodosverem:</strong> apresenta&ccedil;&atilde;o do Tutor, trazendo uma "
    "mensagem de acolhimento. Finaliza com tr&ecirc;s dicas importantes.</span></p>\n"
    '<div style="width: 100%;">'
    '<div style="position: relative;"><iframe width="1200" height="675" '
    'title="Boas-vindas" src="https://view.genial.ly/000000"></iframe></div>'
    "</div>"
)


def test_extracts_the_description_bounded_by_the_enclosing_block() -> None:
    text = extract_paratodosverem(_REAL_SHAPE_HTML)
    assert text == "apresentação do Tutor, trazendo uma mensagem de acolhimento. Finaliza com três dicas importantes."


def test_marker_is_case_insensitive_and_tolerates_missing_colon() -> None:
    assert extract_paratodosverem("<p>#ParaTodosVerem sem dois pontos aqui.</p>") == "sem dois pontos aqui."


def test_returns_none_when_marker_is_absent() -> None:
    """A page with no accessibility description is a correct, ordinary
    result — never treated as an error by any caller."""
    assert extract_paratodosverem("<p>Bem-vindo à disciplina.</p>") is None


def test_returns_none_for_empty_description_after_marker() -> None:
    assert extract_paratodosverem("<p>#paratodosverem:</p>") is None


def test_falls_back_to_end_of_fragment_when_no_closing_tag_found() -> None:
    assert extract_paratodosverem("#paratodosverem: sem fechamento") == "sem fechamento"


def test_finds_embedded_unsafe_html_href_ignoring_attribute_order() -> None:
    fragment = (
        '<a data-bbid="x" data-bbfile="{&quot;resourceUrl&quot;:&quot;https://bb.example/y&quot;}" '
        'data-bbtype="embedded-unsafe-html" href="https://bb.example/y"></a>'
    )
    assert find_embedded_html_urls(fragment) == ["https://bb.example/y"]


def test_ignores_anchors_that_are_not_embedded_unsafe_html() -> None:
    fragment = '<a href="https://example.com/article">Leia mais</a>'
    assert find_embedded_html_urls(fragment) == []


def test_finds_multiple_embeds_in_order() -> None:
    fragment = (
        '<a data-bbtype="embedded-unsafe-html" href="https://bb.example/a"></a>'
        '<a data-bbtype="embedded-unsafe-html" href="https://bb.example/b"></a>'
    )
    assert find_embedded_html_urls(fragment) == ["https://bb.example/a", "https://bb.example/b"]
