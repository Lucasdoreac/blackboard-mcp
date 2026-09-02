from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://bb.cruzeirodosulvirtual.com.br"
_PROFILE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


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
        return cls(
            profile=profile,
            base_url=os.getenv("BLACKBOARD_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            data_home=Path(os.getenv("BLACKBOARD_MCP_HOME", Path.home() / ".local" / "share" / "blackboard-mcp")),
            chrome_path=os.getenv("BLACKBOARD_CHROME_PATH", "/usr/bin/google-chrome"),
        )
