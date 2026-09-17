"""Grava o que o navegador faz durante um envio MANUAL, para aprender o contrato.

Por que existe (2026-09-16): o projeto é read-only e não sabe enviar atividade.
Antes de escrever qualquer envio, o contrato precisa ser MEDIDO — descobrir
endpoint de escrita por tentativa e erro contra uma conta acadêmica real, com
número limitado de tentativas e `late_attempts_blocked`, pode queimar a entrega
de alguém sem desfazer.

O jeito seguro é observar: o dono envia à mão, com a janela instrumentada, e
fica registrado exatamente quais requisições o Ultra fez. Nada aqui envia nada
— só escuta.

**Nenhum segredo vai para o arquivo.** Cookie, XSRF e afins são substituídos por
um marcador; o corpo é gravado porque é justamente ele que ensina a forma do
envio, mas passa pelo mesmo expurgo. Um arquivo de captura precisa poder ser
lido e colado num PR sem vazar sessão.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

# Cabeçalhos que carregam credencial. Guardamos que ELES EXISTEM (a implementação
# vai precisar mandá-los), nunca o valor.
SENSITIVE_HEADERS = frozenset({
    "cookie", "set-cookie", "authorization", "x-blackboard-xsrf",
    "x-sober-bridge-key", "proxy-authorization",
})
REDACTED = "<redigido>"

# Campos de corpo que parecem credencial ou token.
_SENSITIVE_KEY_RE = re.compile(
    r"(xsrf|token|senha|password|secret|cookie|session|authorization|bearer)", re.IGNORECASE
)
# Métodos que MUDAM estado — são os que interessam para aprender o envio.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_BODY = 20_000


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        nome: (REDACTED if nome.lower() in SENSITIVE_HEADERS else valor)
        for nome, valor in (headers or {}).items()
    }


def redact_body(body: Any) -> Any:
    """Expurga recursivamente valores de chave sensível, preservando a FORMA.

    A forma é o que ensina o contrato; o valor de um token não ensina nada e
    não pode sair daqui."""
    if isinstance(body, dict):
        return {
            k: (REDACTED if _SENSITIVE_KEY_RE.search(str(k)) else redact_body(v))
            for k, v in body.items()
        }
    if isinstance(body, list):
        return [redact_body(item) for item in body]
    return body


def parse_body(raw: str | None) -> Any:
    """JSON vira estrutura (expurgável); o resto vira texto truncado."""
    if not raw:
        return None
    texto = raw[:_MAX_BODY]
    try:
        return redact_body(json.loads(texto))
    except (ValueError, TypeError):
        # Multipart de upload entra por aqui: o binário não serve de nada no
        # registro, mas o tamanho e o tipo sim.
        return {"_raw_len": len(raw), "_preview": texto[:400]}


def record(
    *, method: str, url: str, headers: dict[str, str], body: str | None,
    status: int | None = None, base_url: str = "",
) -> dict[str, Any] | None:
    """Uma linha do registro, ou None quando a requisição não interessa.

    Só requisições de ESCRITA para o próprio Blackboard entram: o resto é ruído
    de página (estáticos, telemetria, CDN) e encheria o arquivo sem ensinar
    nada."""
    if method.upper() not in WRITE_METHODS:
        return None
    if base_url and not url.startswith(base_url):
        return None
    return {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": method.upper(),
        "url": url,
        "status": status,
        "headers": redact_headers(headers),
        "body": parse_body(body),
    }


__all__ = [
    "REDACTED",
    "SENSITIVE_HEADERS",
    "WRITE_METHODS",
    "parse_body",
    "record",
    "redact_body",
    "redact_headers",
]
