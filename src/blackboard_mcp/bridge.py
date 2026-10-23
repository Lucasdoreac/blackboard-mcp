"""Authenticated MCP Streamable HTTP over a local Unix-domain socket."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import stat
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import uvicorn

from .session import BlackboardRequestRejected, BlackboardSession, SessionStale

ASGIApp = Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]

# Blackboard's own BbRouter cookie carries an 8h INACTIVITY window (not an
# absolute cap) that its own SPA keeps alive with periodic calls to this
# endpoint while a tab stays open. 20min is comfortably under 8h even if one
# ping is missed; the call itself rotates BbRouter with a fresh `expires`.
KEEPALIVE_PATH = "/learn/api/v1/utilities/timeUntilBbSessionInactive"
DEFAULT_KEEPALIVE_INTERVAL_S = 1200.0
# Depois de uma falha, re-tenta mais cedo: em 2026-10-20 um dia de WARP/DNS
# instável bastou para 8 h sem ping bem-sucedido com o intervalo fixo de 20 min.
KEEPALIVE_RETRY_INTERVAL_S = 300.0

logger = logging.getLogger("blackboard_mcp.keepalive")


def _remaining(session: BlackboardSession, now: float) -> str:
    expires_at = session.expires_at
    return "desconhecido" if expires_at is None else f"{int((expires_at - now) // 60)}min"


async def keepalive_ping(session: BlackboardSession) -> bool:
    """Renew the session's inactivity window; never raises. False = no session yet or rejected.

    Cada falha fica em `session.keepalive` e no log, com a classe (rede ×
    sessão recusada) e o tempo restante da sessão — nunca o valor do cookie.
    """
    health = session.keepalive
    try:
        if not session.configured and not session.reload_from_disk():
            raise SessionStale("sessao nao configurada")
        await session.get(KEEPALIVE_PATH, {"forceLogout": "false"})
    except Exception as exc:
        # SessionStale: `get` já releu o disco antes de desistir, então um
        # login novo copiado para cá é pego no próximo ping. Qualquer outra
        # coisa (WARP, DNS, ...) é tratada como rede e re-tentada.
        failure_class = (
            "session_stale" if isinstance(exc, SessionStale)
            else "rejected" if isinstance(exc, BlackboardRequestRejected)
            else "network"
        )
        now = time.time()
        health.last_failure_at = now
        health.last_failure_class = failure_class
        health.consecutive_failures += 1
        logger.warning(
            "keepalive falhou: classe=%s erro=%s falhas_seguidas=%d sessao_restante=%s",
            failure_class, type(exc).__name__, health.consecutive_failures, _remaining(session, now),
        )
        if session.keepalive_failing(now):
            logger.error(
                "keepalive: sessao Blackboard vence em %s e os pings estao falhando; "
                "o dono precisa refazer o login", _remaining(session, now),
            )
        return False
    now = time.time()
    if health.consecutive_failures:
        logger.warning(
            "keepalive recuperado apos %d falha(s); sessao_restante=%s",
            health.consecutive_failures, _remaining(session, now),
        )
    health.last_ok_at = now
    health.consecutive_failures = 0
    return True


async def _keepalive_loop(
    session: BlackboardSession,
    interval_s: float,
    retry_interval_s: float = KEEPALIVE_RETRY_INTERVAL_S,
) -> None:
    delay = interval_s
    while True:
        await asyncio.sleep(delay)
        delay = interval_s if await keepalive_ping(session) else min(retry_interval_s, interval_s)


class BridgeAuth:
    """Reject requests without the local bridge key before MCP sees them."""

    def __init__(self, app: ASGIApp, key: str):
        if not key:
            raise ValueError("a chave da bridge MCP nao pode ser vazia")
        self.app = app
        self.key = key.encode()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"x-sober-bridge-key", b"")
            if not hmac.compare_digest(supplied, self.key):
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def _prepare_socket(socket_path: Path) -> None:
    # Never chmod an existing directory such as /tmp. Only a directory owned
    # by this bridge is created private.
    if not socket_path.parent.exists():
        socket_path.parent.mkdir(parents=True, mode=0o700)
    try:
        mode = socket_path.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(mode):
        raise RuntimeError("o caminho da bridge existe e nao e um socket; recusando sobrescrever")
    socket_path.unlink()


async def serve_unix_socket(
    mcp: Any,
    socket_path: Path,
    bridge_key: str,
    *,
    session: BlackboardSession | None = None,
    keepalive_interval_s: float = DEFAULT_KEEPALIVE_INTERVAL_S,
) -> None:
    """Serve MCP only through a filesystem socket, never a network port."""
    _prepare_socket(socket_path)
    app = BridgeAuth(mcp.streamable_http_app(), bridge_key)
    server = uvicorn.Server(uvicorn.Config(app, uds=str(socket_path), log_level="warning"))
    serve_task = asyncio.create_task(server.serve())
    keepalive_task = asyncio.create_task(_keepalive_loop(session, keepalive_interval_s)) if session else None
    try:
        for _ in range(100):
            if socket_path.exists():
                if not stat.S_ISSOCK(socket_path.lstat().st_mode):
                    raise RuntimeError("Uvicorn criou um endpoint que nao e socket")
                os.chmod(socket_path, 0o600)
                break
            if serve_task.done():
                await serve_task
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("a bridge MCP nao criou o socket no tempo esperado")
        await serve_task
    finally:
        if keepalive_task is not None:
            keepalive_task.cancel()
        if not serve_task.done():
            server.should_exit = True
            await serve_task
        if socket_path.exists() and stat.S_ISSOCK(socket_path.lstat().st_mode):
            socket_path.unlink()
