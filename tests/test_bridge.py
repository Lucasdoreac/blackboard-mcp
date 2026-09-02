import asyncio
from pathlib import Path

import pytest

from blackboard_mcp.bridge import BridgeAuth, _prepare_socket


async def _receive() -> dict:
    return {"type": "http.request"}


@pytest.mark.asyncio
async def test_bridge_refuses_missing_key() -> None:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    async def inner(*_args: object) -> None:
        raise AssertionError("MCP nao pode receber request sem chave")

    await BridgeAuth(inner, "expected")(
        {"type": "http", "headers": []}, _receive, send
    )
    assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 401


@pytest.mark.asyncio
async def test_bridge_allows_exact_key() -> None:
    called = False

    async def inner(*_args: object) -> None:
        nonlocal called
        called = True

    await BridgeAuth(inner, "expected")(
        {"type": "http", "headers": [(b"x-sober-bridge-key", b"expected")]}, _receive, lambda _: asyncio.sleep(0)
    )
    assert called


def test_prepare_socket_refuses_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "bridge.sock"
    path.write_text("not a socket")
    with pytest.raises(RuntimeError, match="nao e um socket"):
        _prepare_socket(path)
