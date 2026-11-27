"""Metadados de escritas observadas: não registra valores de conteúdo privado.

Arquivos antigos de captura podem conter credenciais ou dados acadêmicos;
não são automaticamente saneados por esta versão.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Cabeçalhos que carregam credencial. Guardamos que ELES EXISTEM (a implementação
# vai precisar mandá-los), nunca o valor.
SENSITIVE_HEADERS = frozenset({
    "cookie", "set-cookie", "authorization", "x-blackboard-xsrf",
    "x-sober-bridge-key", "proxy-authorization",
})
REDACTED = "<redigido>"

# Métodos que mudam estado.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    # Never retain arbitrary header names or values (custom headers can contain
    # secrets too). These names alone are useful to reproduce the protocol.
    known = SENSITIVE_HEADERS | {"content-type", "x-requested-with"}
    return {name: REDACTED for name in (headers or {}) if name.lower() in known}


def redact_body(body: Any) -> Any:
    # Key names and innocuous-looking fields can themselves contain secrets,
    # personal data, or submitted answers. Never try to infer safety from keys.
    return REDACTED


def parse_body(raw: str | None) -> Any:
    return None if raw is None else {"_raw_len": len(raw)}


def _origin(url: str) -> tuple[str, str, int] | None:
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        port = parsed.port
        return scheme, parsed.hostname.lower(), port if port is not None else (443 if scheme == "https" else 80)
    except ValueError:
        return None


def same_origin(url: str, base_url: str) -> bool:
    origin = _origin(base_url)
    return origin is not None and _origin(url) == origin


def record(
    *, method: str, url: str, headers: dict[str, str], body: str | None,
    status: int | None = None, base_url: str = "",
) -> dict[str, Any] | None:
    """Only same-origin writes; omit paths, query strings and body content."""
    if method.upper() not in WRITE_METHODS or not same_origin(url, base_url):
        return None
    return {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": method.upper(),
        "url": REDACTED,
        "status": status,
        "headers": redact_headers(headers),
        "body": parse_body(body),
    }


def ozone_args() -> list[str]:
    """Argumentos extras para a janela abrir na sessão gráfica do usuário.

    Numa sessão WAYLAND, falar Wayland direto evita o XWayland — que exige um
    cookie de autorização que o GNOME não deixa em `~/.Xauthority`. Medido em
    2026-09-17 no host do dono: o Chrome morria com

        Authorization required, but no authorization protocol specified
        Missing X server or $DISPLAY

    mesmo com `DISPLAY=:0` e o socket `X0` existindo. O socket existir não
    significa que se pode conectar nele."""
    import os
    import sys

    if sys.platform != "linux":
        return []
    if os.environ.get("WAYLAND_DISPLAY"):
        return ["--ozone-platform=wayland"]
    return []


def display_hint() -> str | None:
    """Motivo pelo qual a janela não abriria aqui, ou None se abriria.

    Sem isto o Playwright estoura um erro de "Missing X server" que não diz a
    quem lê o que fazer. A captura é feita por uma PESSOA, na frente da tela —
    a mensagem tem que caber nessa situação."""
    import os
    import sys

    if sys.platform in {"darwin", "win32"}:
        return None
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return None
    return (
        "sem sessão gráfica (DISPLAY vazio): a captura precisa de uma janela "
        "VISÍVEL, porque quem envia a atividade é você. Rode este comando na "
        "própria máquina, ou por acesso remoto de tela, e não por `ssh` puro. "
        "Numa sessão já aberta, costuma bastar `DISPLAY=:0` antes do comando."
    )


__all__ = [
    "REDACTED",
    "SENSITIVE_HEADERS",
    "WRITE_METHODS",
    "display_hint",
    "ozone_args",
    "parse_body",
    "record",
    "same_origin",
    "redact_body",
    "redact_headers",
]
