from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://bb.cruzeirodosulvirtual.com.br"
_PROFILE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _config_path(data_home: Path, profile: str) -> Path:
    return data_home / "profiles" / profile / "config.json"


def load_profile_config(data_home: Path, profile: str) -> dict[str, Any]:
    """Per-profile settings set once via `blackboard-mcp setup`, so a
    person configuring their own institution's Blackboard never has to
    export an env var or edit a file by hand. Missing or corrupt is not an
    error — it just means nothing has been configured for this profile yet."""
    path = _config_path(data_home, profile)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_profile_config(data_home: Path, profile: str, config: dict[str, Any]) -> None:
    path = _config_path(data_home, profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(config), encoding="utf-8")
    path.chmod(0o600)


@dataclass(frozen=True)
class Settings:
    profile: str
    base_url: str = DEFAULT_BASE_URL
    data_home: Path = Path.home() / ".local" / "share" / "blackboard-mcp"
    chrome_path: str = "/usr/bin/google-chrome"
    debug_port: int = 9223

    @property
    def profile_dir(self) -> Path:
        return self.data_home / "profiles" / self.profile

    @classmethod
    def from_profile(cls, profile: str) -> "Settings":
        if not _PROFILE_RE.fullmatch(profile):
            raise ValueError("perfil invalido: use apenas letras, numeros, _ ou -")
        data_home = Path(os.getenv("BLACKBOARD_MCP_HOME", Path.home() / ".local" / "share" / "blackboard-mcp"))
        # Resolution order: env var (scripting/CI) > `blackboard-mcp setup`'s
        # persisted per-profile config > the pilot's own institution, kept
        # as the default so an existing profile with nothing configured
        # (e.g. the owner's own `sober` profile) never changes behavior.
        env_base_url = os.getenv("BLACKBOARD_BASE_URL")
        persisted = load_profile_config(data_home, profile)
        base_url = env_base_url or persisted.get("base_url") or DEFAULT_BASE_URL
        return cls(
            profile=profile,
            base_url=str(base_url).rstrip("/"),
            data_home=data_home,
            chrome_path=os.getenv("BLACKBOARD_CHROME_PATH", "/usr/bin/google-chrome"),
        )
