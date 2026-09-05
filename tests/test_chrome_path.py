"""Resolução do Chrome por plataforma.

O default era `/usr/bin/google-chrome` cravado — Linux-only. No macOS o
`auth-status` falhava com `executable doesn't exist`, e ele é justamente o
comando que se roda para descobrir se precisa logar (achado ao verificar o
repo numa segunda máquina, 2026-09-05).
"""
from __future__ import annotations

from pathlib import Path

from blackboard_mcp import config
from blackboard_mcp.config import Settings, resolve_chrome_path


def test_picks_the_chrome_that_exists_on_this_machine(monkeypatch, tmp_path: Path) -> None:
    mac = tmp_path / "Google Chrome"
    mac.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(config, "_CHROME_CANDIDATES", ("/nao/existe", str(mac), "/usr/bin/google-chrome"))
    assert resolve_chrome_path() == str(mac)


def test_falls_back_to_PATH_when_no_candidate_exists(monkeypatch) -> None:
    monkeypatch.setattr(config, "_CHROME_CANDIDATES", ("/nao/existe/1", "/nao/existe/2"))
    monkeypatch.setattr(config.shutil, "which", lambda nome: "/opt/bin/chromium" if nome == "chromium" else None)
    assert resolve_chrome_path() == "/opt/bin/chromium"


def test_last_resort_names_a_concrete_path_not_empty_string(monkeypatch) -> None:
    """Sem Chrome nenhum, o erro tem que nomear um caminho — string vazia
    produziria uma mensagem de falha que não ajuda ninguém."""
    monkeypatch.setattr(config, "_CHROME_CANDIDATES", ("/nao/existe",))
    monkeypatch.setattr(config.shutil, "which", lambda nome: None)
    assert resolve_chrome_path() == "/usr/bin/google-chrome"


def test_env_var_still_wins_over_detection(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BLACKBOARD_CHROME_PATH", "/meu/chrome")
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    assert Settings.from_profile("sober").chrome_path == "/meu/chrome"


def test_detection_is_used_when_env_is_absent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BLACKBOARD_CHROME_PATH", raising=False)
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    monkeypatch.setattr(config, "resolve_chrome_path", lambda: "/detectado/chrome")
    assert Settings.from_profile("sober").chrome_path == "/detectado/chrome"
