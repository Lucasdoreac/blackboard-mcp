"""Cookie-replay session for Blackboard's internal REST API.

Playwright is only used for the interactive login (SSO/MFA needs a real
browser). Every READ after that is plain HTTPS with the extracted session
cookies — same architecture as gemini-notebook-mcp-cli's cookie replay
(see docs/AUTHENTICATION.md upstream): extract once, replay via httpx, never
re-render a page just to fetch data.

The XSRF token Blackboard's own SPA sends as `X-Blackboard-XSRF` is embedded
inside the httpOnly `BbRouter` cookie itself (`...,xsrf:<uuid>,...`) — no DOM
reading needed, `context.cookies()` already exposes it. `BbRouter` also
carries `timeout:28800` (8h) and `expires:<unix ts> = login-time + timeout`:
an INACTIVITY window, not an absolute cap. Blackboard's own keep-alive
endpoint (`timeUntilBbSessionInactive`) rotates `BbRouter` with a fresh
`expires` on every call — a periodic ping via this same session (see
`keepalive.py`) keeps the session alive indefinitely without ever opening a
browser again.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx


class SessionStale(RuntimeError):
    """The persisted cookies were rejected; a real (Playwright) login is required."""


def session_path(data_home: Path, profile: str) -> Path:
    return data_home / "profiles" / profile / "session.json"


def extract_xsrf(bbrouter_value: str) -> str | None:
    """Parse the `xsrf:<uuid>` field out of the BbRouter cookie's comma-joined value."""
    for part in bbrouter_value.split(","):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        if key == "xsrf":
            return value
    return None


class BlackboardSession:
    """Persisted cookie jar + XSRF token, replayed over plain HTTPS."""

    def __init__(self, base_url: str, data_home: Path, profile: str) -> None:
        self.base_url = base_url
        self._path = session_path(data_home, profile)
        self._cookies: dict[str, str] = {}
        self._xsrf: str | None = None
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self._cookies = dict(data.get("cookies", {}))
        self._xsrf = data.get("xsrf")

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.parent.chmod(0o700)
        payload = {"cookies": self._cookies, "xsrf": self._xsrf, "captured_at": time.time()}
        self._path.write_text(json.dumps(payload), encoding="utf-8")
        self._path.chmod(0o600)

    @property
    def configured(self) -> bool:
        return bool(self._cookies.get("BbRouter") and self._xsrf)

    def adopt(self, cookies: list[dict[str, Any]]) -> None:
        """Replace the stored cookie jar from a fresh Playwright extraction."""
        jar = {c["name"]: c["value"] for c in cookies}
        bbrouter = jar.get("BbRouter")
        if not bbrouter:
            raise SessionStale("BbRouter ausente na sessao autenticada")
        xsrf = extract_xsrf(bbrouter)
        if not xsrf:
            raise SessionStale("xsrf ausente no cookie BbRouter")
        self._cookies = jar
        self._xsrf = xsrf
        self._save()

    def clear(self) -> None:
        self._cookies = {}
        self._xsrf = None
        if self._path.exists():
            self._path.unlink()

    async def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """GET one internal `/learn/api/v1/...` path; returns decoded JSON."""
        if not self.configured:
            raise SessionStale("sessao nao configurada; faca login")
        async with httpx.AsyncClient(base_url=self.base_url, cookies=self._cookies, timeout=15.0) as client:
            response = await client.get(
                path,
                params=params,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "X-Blackboard-XSRF": self._xsrf or "",
                    "Accept": "application/json, text/plain, */*",
                },
            )
        self._absorb_rotated_cookies(response)
        if response.status_code in (401, 403):
            raise SessionStale("a sessao Blackboard foi recusada (401/403)")
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400 or "json" not in content_type:
            raise SessionStale("a API Blackboard nao retornou JSON (sessao provavelmente expirada)")
        return response.json()

    def _absorb_rotated_cookies(self, response: httpx.Response) -> None:
        """Persist any Set-Cookie rotation (BbRouter's expires rolls forward on activity)."""
        rotated = False
        for name, value in response.cookies.items():
            if self._cookies.get(name) != value:
                self._cookies[name] = value
                rotated = True
        bbrouter = self._cookies.get("BbRouter")
        if rotated and bbrouter:
            new_xsrf = extract_xsrf(bbrouter)
            if new_xsrf:
                self._xsrf = new_xsrf
        if rotated:
            self._save()


__all__ = ["BlackboardSession", "SessionStale", "extract_xsrf", "session_path"]
