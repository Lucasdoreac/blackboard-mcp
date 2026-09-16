from __future__ import annotations

import json
import os
import shutil
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Institução padrão deste repositório: a UDF (Blackboard hospedado no Cruzeiro
# do Sul Virtual). Serve QUALQUER Blackboard Ultra: `blackboard-mcp setup`
# pergunta o endereço e grava por perfil, e `BLACKBOARD_BASE_URL` vence tudo
# (scripting/CI). Clonou para outra faculdade? Troque SÓ esta linha — nenhum
# outro lugar do código conhece a instituição.
DEFAULT_BASE_URL = "https://bb.cruzeirodosulvirtual.com.br"
_DIRECT_SETTINGS_TEST_URL = "https://blackboard.example.invalid"
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


# Candidatos de Chrome por plataforma, na ordem em que valem a pena tentar.
# O default era `/usr/bin/google-chrome` cravado: Linux-only, e quem falhava
# PRIMEIRO era o `auth-status` — justamente o comando que se roda para
# descobrir se precisa logar. Pior lugar possível para um default errado.
# `BLACKBOARD_CHROME_PATH` continua vencendo tudo (scripting/CI).
_CHROME_CANDIDATES: tuple[str, ...] = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
)


def resolve_chrome_path() -> str:
    """Primeiro Chrome que EXISTE nesta máquina; senão, o que estiver no PATH.

    Fallback final é o caminho Linux histórico — assim o erro, quando não há
    Chrome nenhum, continua nomeando um caminho concreto em vez de string
    vazia.
    """
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return "/usr/bin/google-chrome"


@dataclass(frozen=True)
class Settings:
    profile: str
    # Direct construction is useful for pure unit tests. Production code uses
    # `from_profile`, which deliberately resolves to an empty URL until setup.
    base_url: str = _DIRECT_SETTINGS_TEST_URL
    data_home: Path = Path.home() / ".local" / "share" / "blackboard-mcp"
    chrome_path: str = field(default_factory=resolve_chrome_path)
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
        # persisted per-profile config. A missing value is diagnosed locally
        # and rejected only when an operation needs to contact Blackboard.
        env_base_url = os.getenv("BLACKBOARD_BASE_URL")
        persisted = load_profile_config(data_home, profile)
        base_url = env_base_url or persisted.get("base_url") or DEFAULT_BASE_URL
        return cls(
            profile=profile,
            base_url=str(base_url).rstrip("/"),
            data_home=data_home,
            chrome_path=os.getenv("BLACKBOARD_CHROME_PATH") or resolve_chrome_path(),
        )
