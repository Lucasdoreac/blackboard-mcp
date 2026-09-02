"""Authenticated MCP Streamable HTTP over a local Unix-domain socket."""

from __future__ import annotations

import asyncio
import hmac
import os
import stat
from pathlib import Path
from typing import Any, Awaitable, Callable

import uvicorn

from .session import BlackboardSession, SessionStale

ASGIApp = Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]

# Blackboard's own BbRouter cookie carries an 8h INACTIVITY window (not an
# absolute cap) that its own SPA keeps alive with periodic calls to this
# endpoint while a tab stays open. 20min is comfortably under 8h even if one
# ping is missed; the call itself rotates BbRouter with a fresh `expires`.
KEEPALIVE_PATH = "/learn/api/v1/utilities/timeUntilBbSessionInactive"
DEFAULT_KEEPALIVE_INTERVAL_S = 1200.0


async def keepalive_ping(session: BlackboardSession) -> bool:
    """Renew the session's inactivity window; never raises. False = no session yet or rejected."""
    if not session.configured:
        return False
    try:
        await session.get(KEEPALIVE_PATH, {"forceLogout": "false"})
        return True
    except SessionStale:
        # A real read will surface a clear re-login error to the owner;
        # the keep-alive loop just stops helping until that happens.
        return False
    except Exception:
        # Network blip (WARP, DNS, ...). Try again next interval.
        return False


async def _keepalive_loop(session: BlackboardSession, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await keepalive_ping(session)


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
