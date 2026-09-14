"""`blackboard-mcp setup` — the guided, no-code-editing onboarding flow.

The interactive orchestration (`_run_setup`: opens a real Chrome window,
waits for the login) is validated by actual execution. What's unit-tested
here is the pure input validation; the login wait itself is covered in
`test_complete_login.py`.
"""

from __future__ import annotations

import pytest

from blackboard_mcp.cli import _prompt_base_url, _prompt_profile


def test_prompt_base_url_adds_https_when_scheme_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "bb.suafaculdade.edu")
    assert _prompt_base_url() == "https://bb.suafaculdade.edu"


def test_prompt_base_url_keeps_an_explicit_https_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "https://bb.suafaculdade.edu/")
    assert _prompt_base_url() == "https://bb.suafaculdade.edu"


def test_prompt_base_url_reprompts_on_blank_then_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["", "bb.suafaculdade.edu"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert _prompt_base_url() == "https://bb.suafaculdade.edu"


def test_prompt_base_url_reprompts_on_a_host_that_still_fails_to_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["http://", "bb.suafaculdade.edu"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert _prompt_base_url() == "https://bb.suafaculdade.edu"


def test_prompt_profile_accepts_the_default_on_blank_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert _prompt_profile("default") == "default"


def test_prompt_profile_accepts_a_custom_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "minha-faculdade")
    assert _prompt_profile("default") == "minha-faculdade"


def test_prompt_profile_reprompts_on_an_invalid_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revert-check target: without the retry loop, an invalid name (spaces,
    empty after strip, path traversal) would either crash `setup` outright
    or silently persist config under a name `Settings.from_profile` later
    rejects — someone with zero Python experience needs a clear retry, not
    a traceback."""
    answers = iter(["nome invalido", "minha-faculdade"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert _prompt_profile("default") == "minha-faculdade"
