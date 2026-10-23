"""`ops/login-remote.sh`: login no Mac, session.json no host da bridge com modo 600."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "login-remote.sh"


def _fake_bin(tmp_path: Path, remote_home: Path) -> Path:
    """`ssh` falso: roda o comando remoto localmente, com HOME = remote_home."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh = bindir / "ssh"
    ssh.write_text(f'#!/usr/bin/env bash\nshift\nHOME="{remote_home}" exec bash -c "$1"\n', encoding="utf-8")
    ssh.chmod(0o755)
    uv = bindir / "uv"
    uv.write_text(f'#!/usr/bin/env bash\necho "$@" > "{tmp_path}/uv-args"\n', encoding="utf-8")
    uv.chmod(0o755)
    return bindir


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    local_home = tmp_path / "mac"
    remote_home = tmp_path / "ubuntu"
    remote_home.mkdir()
    origem = local_home / ".local/share/blackboard-mcp/profiles/sober/session.json"
    origem.parent.mkdir(parents=True)
    origem.write_text('{"cookies": {"BbRouter": "expires:1,xsrf:segredo"}, "xsrf": "segredo"}', encoding="utf-8")
    env = {**os.environ, "HOME": str(local_home), "PATH": f"{_fake_bin(tmp_path, remote_home)}:{os.environ['PATH']}"}
    env.pop("BLACKBOARD_MCP_HOME", None)
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


def test_login_remote_logs_in_and_ships_session_with_mode_600(tmp_path: Path) -> None:
    result = _run(tmp_path, "--host", "ubuntu")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "uv-args").read_text().split() == ["run", "blackboard-mcp", "login", "--profile", "sober"]
    destino = tmp_path / "ubuntu/.local/share/blackboard-mcp/profiles/sober/session.json"
    assert "segredo" in destino.read_text(encoding="utf-8")
    assert stat.S_IMODE(destino.stat().st_mode) == 0o600
    assert stat.S_IMODE(destino.parent.stat().st_mode) == 0o700
    assert list(destino.parent.glob("session.json.*")) == []   # sem temporário sobrando
    assert "segredo" not in result.stdout + result.stderr


def test_login_remote_rejects_a_profile_that_could_inject_a_remote_command(tmp_path: Path) -> None:
    result = _run(tmp_path, "--skip-login", "--profile", "x';touch pwned;'")

    assert result.returncode == 2
    assert not (tmp_path / "ubuntu/pwned").exists()
