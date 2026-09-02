"""`blackboard-mcp setup` — the guided, no-code-editing onboarding flow.

The interactive orchestration (`_run_setup`: opens a real Chrome window,
polls real auth status) is validated by actual execution, not mocked here
— same discipline already used for the other `while True` loops in this
project. What's unit-tested is the pure input validation and the polling
loop's own success/timeout logic in isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from blackboard_mcp.cli import _prompt_base_url, _prompt_profile, _wait_for_login


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


@pytest.mark.asyncio
async def test_wait_for_login_returns_true_as_soon_as_authenticated() -> None:
    client = AsyncMock()
    client.auth_status = AsyncMock(return_value={"authenticated": True})
    assert await _wait_for_login(client, timeout_s=30, interval_s=1) is True
    client.auth_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_for_login_gives_up_after_the_timeout() -> None:
    client = AsyncMock()
    client.auth_status = AsyncMock(return_value={"authenticated": False})
    assert await _wait_for_login(client, timeout_s=3, interval_s=1) is False
    assert client.auth_status.await_count == 3
