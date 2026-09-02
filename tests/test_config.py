from pathlib import Path

import pytest

from blackboard_mcp.client import BlackboardClient, prepare_profile
from blackboard_mcp.config import Settings


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


def test_login_url_is_fixed_to_blackboard_host() -> None:
    assert BlackboardClient(Settings.from_profile("sober")).login_url().startswith("https://bb.cruzeirodosulvirtual.com.br/")


def test_login_page_is_not_an_authenticated_blackboard_url() -> None:
    client = BlackboardClient(Settings.from_profile("sober"))
    with pytest.raises(Exception):
        client._require_base_url("https://bb.cruzeirodosulvirtual.com.br/?new_loc=%2Fultra%2Fcourse")
