from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import blackboard_mcp.bridge as bridge_module
import blackboard_mcp.cli as cli


def test_serve_http_initializes_settings_from_module_scope(monkeypatch) -> None:
    """A local import in main() must never shadow Settings at service startup."""

    settings = SimpleNamespace(base_url="https://blackboard.invalid", data_home=Path("/tmp"), profile="sober")

    class FakeSettings:
        @staticmethod
        def from_profile(profile: str):
            assert profile == "sober"
            return settings

    served: dict = {}

    async def fake_serve_unix_socket(mcp, *_args, **kwargs) -> None:
        served.update(mcp=mcp, session=kwargs["session"])

    class FakeClient:
        def __init__(self, got) -> None:
            assert got is settings
            self.session = object()

    monkeypatch.setattr(cli, "Settings", FakeSettings)
    monkeypatch.setattr(cli, "BlackboardClient", FakeClient)
    monkeypatch.setattr(cli, "create_server", lambda profile, client: {"profile": profile, "client": client})
    monkeypatch.setattr(bridge_module, "serve_unix_socket", fake_serve_unix_socket)
    monkeypatch.setenv("BLACKBOARD_BRIDGE_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        ["blackboard-mcp", "serve-http", "--profile", "sober", "--socket", "/tmp/bridge.sock"],
    )

    cli.main()

    # Revert-check (2026-10-23): a bridge criava DUAS sessões — uma para o
    # keep-alive e outra dentro do cliente das tools. O keep-alive relia o
    # disco e se curava; `auth_status` seguia com o cookie morto até restart.
    assert served["session"] is served["mcp"]["client"].session
