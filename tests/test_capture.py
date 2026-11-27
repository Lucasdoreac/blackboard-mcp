"""Captura do envio manual: registra a FORMA, nunca o segredo.

Este arquivo existe porque o registro é feito para ser LIDO e colado num PR —
é assim que o contrato de envio vira código. Um arquivo de captura que vaze
cookie de sessão transforma uma ferramenta de aprendizado em incidente.
"""

from __future__ import annotations

import json


from blackboard_mcp.capture import REDACTED, parse_body, record, redact_body, redact_headers

BASE = "https://bb.example.edu"


def test_headers_keep_only_known_names_never_values() -> None:
    headers = redact_headers({"Cookie": "secret", "X-Blackboard-XSRF": "secret", "Content-Type": "application/json; secret=secret", "X-Custom-secret": "secret"})
    assert headers == {"Cookie": REDACTED, "X-Blackboard-XSRF": REDACTED, "Content-Type": REDACTED}
    assert "secret" not in json.dumps(headers).lower()


def test_body_never_writes_json_values_or_raw_preview() -> None:
    for raw in ('{"text":"secret", "secret":"anything"}', 'password=secret', '--multipart secret', '{"broken":"secret', '"secret"'):
        result = parse_body(raw)
        assert result == {"_raw_len": len(raw)}
        assert "secret" not in json.dumps(result)
    assert parse_body(None) is None
    assert redact_body({"secret": "x"}) == REDACTED


def test_record_only_same_origin_and_no_url_or_query_secrets() -> None:
    for url in (BASE + '.evil.test/path', BASE + '@evil.test/path', 'http://bb.example.edu/x', 'https://bb.example.edu:444/x', 'https://evil.test/x', 'not a url'):
        assert record(method="POST", url=url, headers={}, body=None, base_url=BASE) is None
    assert record(method="GET", url=BASE + '/x', headers={}, body=None, base_url=BASE) is None
    assert record(method="POST", url=BASE+'/x', headers={}, body=None, base_url='') is None
    for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        row = record(method=method, url='https://BB.EXAMPLE.EDU:443/secret?token=secret#secret', headers={'Authorization':'secret'}, body='secret', status=201, base_url=BASE)
        assert row and row['method'] == method and row['status'] == 201
        assert 'secret' not in json.dumps(row).lower()


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
