"""Captura do envio manual: registra a FORMA, nunca o segredo.

Este arquivo existe porque o registro é feito para ser LIDO e colado num PR —
é assim que o contrato de envio vira código. Um arquivo de captura que vaze
cookie de sessão transforma uma ferramenta de aprendizado em incidente.
"""

from __future__ import annotations

import json

from blackboard_mcp.capture import REDACTED, parse_body, record, redact_body, redact_headers

BASE = "https://bb.example.edu"


def test_credential_headers_are_never_written() -> None:
    saida = redact_headers({
        "Cookie": "BbRouter=expires:123,xsrf:SEGREDO",
        "X-Blackboard-XSRF": "SEGREDO",
        "Authorization": "Bearer SEGREDO",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    })
    assert saida["Cookie"] == REDACTED
    assert saida["X-Blackboard-XSRF"] == REDACTED
    assert saida["Authorization"] == REDACTED
    # O que NÃO é segredo fica: a implementação vai precisar reproduzir isto.
    assert saida["Content-Type"] == "application/json"
    assert saida["X-Requested-With"] == "XMLHttpRequest"
    assert "SEGREDO" not in json.dumps(saida)


def test_the_header_names_survive_because_the_implementation_needs_them() -> None:
    """Anti-oco da redação: apagar o cabeçalho inteiro esconderia que ele é
    obrigatório, e o envio seria escrito sem ele."""
    saida = redact_headers({"X-Blackboard-XSRF": "SEGREDO"})
    assert "X-Blackboard-XSRF" in saida


def test_sensitive_body_fields_are_redacted_but_the_shape_is_kept() -> None:
    corpo = {
        "attemptId": "_9_1",
        "xsrfToken": "SEGREDO",
        "submission": {"text": "minha resposta", "sessionToken": "SEGREDO"},
        "files": [{"name": "a.pdf", "uploadToken": "SEGREDO"}],
    }
    saida = redact_body(corpo)
    assert saida["attemptId"] == "_9_1", "o que ensina o contrato fica"
    assert saida["submission"]["text"] == "minha resposta"
    assert saida["xsrfToken"] == REDACTED
    assert saida["submission"]["sessionToken"] == REDACTED
    assert saida["files"][0]["uploadToken"] == REDACTED
    assert saida["files"][0]["name"] == "a.pdf"
    assert "SEGREDO" not in json.dumps(saida)


def test_only_writes_to_blackboard_are_recorded() -> None:
    """GET é ruído de página aqui — o que ensina o envio é a ESCRITA. E host de
    fora (CDN, telemetria) não entra de jeito nenhum."""
    assert record(method="GET", url=f"{BASE}/x", headers={}, body=None, base_url=BASE) is None
    assert record(method="POST", url="https://cdn.terceiro.com/t", headers={}, body=None, base_url=BASE) is None
    linha = record(method="POST", url=f"{BASE}/learn/api/v1/x", headers={}, body="{}", status=201, base_url=BASE)
    assert linha is not None and linha["method"] == "POST" and linha["status"] == 201


def test_every_write_method_is_captured() -> None:
    """Se o Ultra enviar por PATCH ou PUT e a captura só ouvir POST, o contrato
    volta incompleto e ninguém percebe até tentar implementar."""
    for metodo in ("POST", "PUT", "PATCH", "DELETE"):
        linha = record(method=metodo, url=f"{BASE}/learn/api/v1/x", headers={}, body=None, base_url=BASE)
        assert linha is not None, metodo


def test_multipart_upload_is_summarised_not_dumped() -> None:
    """O binário do PDF não ensina nada e não cabe no registro; o tamanho sim."""
    corpo = "------WebKitFormBoundary\r\nContent-Disposition: form-data" + ("x" * 50_000)
    saida = parse_body(corpo)
    assert saida["_raw_len"] == len(corpo)
    assert len(json.dumps(saida)) < 1200


def test_capture_is_not_hollow() -> None:
    """Sem corpo não se inventa corpo, e um dicionário sem nada sensível passa
    inteiro — senão a redação estaria comendo o contrato."""
    assert parse_body(None) is None
    limpo = {"attemptId": "_9_1", "status": "NEEDS_GRADING"}
    assert redact_body(limpo) == limpo


def test_missing_display_explains_itself_to_a_person(monkeypatch) -> None:
    """A captura é feita por uma PESSOA na frente da tela. Deixar o Playwright
    estourar "Missing X server" não diz a quem lê o que fazer."""
    import sys

    from blackboard_mcp.capture import display_hint

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    aviso = display_hint()
    assert aviso and "DISPLAY" in aviso and "ssh" in aviso

    monkeypatch.setenv("DISPLAY", ":0")
    assert display_hint() is None, "com tela, nada a avisar"


def test_wayland_session_talks_wayland_instead_of_xwayland(monkeypatch) -> None:
    """Medido no host do dono (2026-09-17): com `DISPLAY=:0` e o socket `X0`
    existindo, o Chrome ainda morria com "Authorization required, but no
    authorization protocol specified" — o XWayland exige um cookie que o GNOME
    não deixa em `~/.Xauthority`. Falar Wayland direto pula esse problema."""
    import sys

    from blackboard_mcp.capture import ozone_args

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert ozone_args() == ["--ozone-platform=wayland"]


def test_x11_session_gets_no_extra_args(monkeypatch) -> None:
    """Anti-oco: forçar Wayland numa sessão X11 quebraria o que funcionava."""
    import sys

    from blackboard_mcp.capture import ozone_args

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    assert ozone_args() == []

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert ozone_args() == [], "fora do Linux não existe ozone"
