from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import blackboard_mcp.bridge as bridge_module
import blackboard_mcp.cli as cli
import blackboard_mcp.session as session_module


def test_serve_http_initializes_settings_from_module_scope(monkeypatch) -> None:
    """A local import in main() must never shadow Settings at service startup."""

    settings = SimpleNamespace(base_url="https://blackboard.invalid", data_home=Path("/tmp"), profile="sober")

    class FakeSettings:
        @staticmethod
        def from_profile(profile: str):
            assert profile == "sober"
            return settings

    async def fake_serve_unix_socket(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(cli, "Settings", FakeSettings)
    monkeypatch.setattr(cli, "create_server", lambda profile: {"profile": profile})
    monkeypatch.setattr(session_module, "BlackboardSession", lambda *_args: object())
    monkeypatch.setattr(bridge_module, "serve_unix_socket", fake_serve_unix_socket)
    monkeypatch.setenv("BLACKBOARD_BRIDGE_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        ["blackboard-mcp", "serve-http", "--profile", "sober", "--socket", "/tmp/bridge.sock"],
    )

    cli.main()
