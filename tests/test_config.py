from pathlib import Path

import pytest

from blackboard_mcp.client import BlackboardClient, prepare_profile
from blackboard_mcp.config import DEFAULT_BASE_URL, Settings, load_profile_config, save_profile_config


def test_profile_path_is_under_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    assert Settings.from_profile("sober").profile_dir == tmp_path / "profiles" / "sober"


@pytest.mark.parametrize("profile", ["../sober", "", "space here", ".hidden"])
def test_profile_rejects_unsafe_values(profile: str) -> None:
    with pytest.raises(ValueError):
        Settings.from_profile(profile)


def test_profile_is_owner_only(tmp_path: Path) -> None:
    profile = tmp_path / "profiles" / "sober"
    prepare_profile(profile)
    assert profile.exists()
    assert profile.stat().st_mode & 0o077 == 0


def test_login_url_falls_back_to_the_repository_institution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem configurar nada, vale a instituição do repositório (a UDF) —
    decisão do dono (2026-09-15): "deixa como mcp da udf, que eu possa clonar
    com outro default"."""
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("BLACKBOARD_BASE_URL", raising=False)
    assert BlackboardClient(Settings.from_profile("sober")).login_url() == f"{DEFAULT_BASE_URL}/ultra/course"


def test_fork_that_clears_the_default_asks_for_setup_instead_of_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("BLACKBOARD_BASE_URL", raising=False)
    monkeypatch.setattr("blackboard_mcp.config.DEFAULT_BASE_URL", "")
    with pytest.raises(ValueError, match="blackboard-mcp setup"):
        BlackboardClient(Settings.from_profile("sober")).login_url()


def test_login_url_accepts_any_institution_configured_via_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revert-check target: with the old hardcoded host comparison, this
    raises ValueError even though the institution was configured correctly
    — exactly the friction that blocked anyone outside Cruzeiro do Sul."""
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    save_profile_config(tmp_path, "outra-faculdade", {"base_url": "https://learn.outrafaculdade.edu"})
    url = BlackboardClient(Settings.from_profile("outra-faculdade")).login_url()
    assert url == "https://learn.outrafaculdade.edu/ultra/course"


def test_login_url_still_rejects_a_malformed_base_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    save_profile_config(tmp_path, "quebrado", {"base_url": "not-a-url"})
    with pytest.raises(ValueError):
        BlackboardClient(Settings.from_profile("quebrado")).login_url()


def test_login_page_is_not_an_authenticated_blackboard_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    save_profile_config(tmp_path, "sober", {"base_url": "https://bb.example.edu"})
    client = BlackboardClient(Settings.from_profile("sober"))
    with pytest.raises(Exception):
        client._require_base_url("https://bb.example.edu/?new_loc=%2Fultra%2Fcourse")


def test_save_and_load_profile_config_round_trips(tmp_path: Path) -> None:
    save_profile_config(tmp_path, "sober", {"base_url": "https://exemplo.edu"})
    assert load_profile_config(tmp_path, "sober") == {"base_url": "https://exemplo.edu"}


def test_load_profile_config_returns_empty_dict_when_absent(tmp_path: Path) -> None:
    assert load_profile_config(tmp_path, "nunca-configurado") == {}


def test_load_profile_config_tolerates_a_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "profiles" / "sober" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json")
    assert load_profile_config(tmp_path, "sober") == {}


def test_from_profile_prefers_env_var_over_persisted_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    monkeypatch.setenv("BLACKBOARD_BASE_URL", "https://do-env.edu")
    save_profile_config(tmp_path, "sober", {"base_url": "https://do-arquivo.edu"})
    assert Settings.from_profile("sober").base_url == "https://do-env.edu"


def test_from_profile_uses_persisted_config_when_no_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("BLACKBOARD_BASE_URL", raising=False)
    save_profile_config(tmp_path, "outra-faculdade", {"base_url": "https://learn.outrafaculdade.edu"})
    assert Settings.from_profile("outra-faculdade").base_url == "https://learn.outrafaculdade.edu"


def test_default_institution_is_the_repository_one_and_setup_or_env_beats_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O padrão é a UDF (o dono do repo); quem é de outra faculdade não edita
    código — `setup` grava por perfil e a variável de ambiente vence tudo."""
    monkeypatch.setenv("BLACKBOARD_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("BLACKBOARD_BASE_URL", raising=False)
    assert Settings.from_profile("novo").base_url == DEFAULT_BASE_URL.rstrip("/")

    save_profile_config(tmp_path, "novo", {"base_url": "https://learn.outra.edu"})
    assert Settings.from_profile("novo").base_url == "https://learn.outra.edu"

    monkeypatch.setenv("BLACKBOARD_BASE_URL", "https://ci.exemplo.edu")
    assert Settings.from_profile("novo").base_url == "https://ci.exemplo.edu"
