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
`bridge.py`) keeps the session alive indefinitely without ever opening a
browser again.

A sessão é carregada do disco no `__init__` e RECARREGADA sob rejeição
(`reload_from_disk`), para que um `login` feito por fora cure o processo em
execução — sem isso o keep-alive desiste na primeira `SessionStale` e nunca
mais ajuda, mesmo com credencial nova no disco.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

# Idade máxima de sessão que o keep-alive considera "perto de vencer" quando os
# pings estão falhando: dá ao dono tempo de logar antes da janela de 8 h fechar.
EXPIRY_WARNING_S = 2 * 3600


class SessionStale(RuntimeError):
    """The persisted cookies were rejected; a real (Playwright) login is required."""


class BlackboardRequestRejected(RuntimeError):
    """A sessão está viva, mas o Blackboard recusou ESTA operação (403/404).

    Achado ao vivo (2026-09-14): `get` tratava todo 401/403/4xx como sessão
    expirada. Uma leitura sem permissão (Pensamento Computacional, coluna que o
    aluno não lê, preferência inexistente) caía no refresh de sessão via browser
    — que regravou `session.json` com cookie não provado e derrubou a sessão
    boa. Recusa de operação e sessão morta são coisas diferentes."""

    def __init__(self, status_code: int, path: str) -> None:
        super().__init__(f"o Blackboard recusou a operacao ({status_code})")
        self.status_code = status_code
        self.path = path


_HEALTH_PATH = "/learn/api/v1/users/me"


@dataclass
class KeepaliveHealth:
    """Estado observável do keep-alive, compartilhado com `auth_status`.

    Até 2026-10-23 o keep-alive engolia toda falha em silêncio: o cookie venceu
    em 2026-10-20 depois de 8 h sem nenhum ping bem-sucedido e ninguém soube
    antes. Nada aqui guarda valor de cookie — só horários e a classe da falha.
    """

    last_ok_at: float | None = None
    last_failure_at: float | None = None
    last_failure_class: str | None = None
    consecutive_failures: int = 0


def session_path(data_home: Path, profile: str) -> Path:
    return data_home / "profiles" / profile / "session.json"


def _bbrouter_field(bbrouter_value: str, name: str) -> str | None:
    for part in bbrouter_value.split(","):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        if key == name:
            return value
    return None


def extract_xsrf(bbrouter_value: str) -> str | None:
    """Parse the `xsrf:<uuid>` field out of the BbRouter cookie's comma-joined value."""
    return _bbrouter_field(bbrouter_value, "xsrf")


def extract_expires(bbrouter_value: str) -> float | None:
    """`expires:<unix ts>` do BbRouter em segundos (aceita milissegundos)."""
    raw = _bbrouter_field(bbrouter_value, "expires")
    try:
        value = float(raw) if raw is not None else None
    except ValueError:
        return None
    if value is None or value <= 0:
        return None
    return value / 1000 if value > 1e12 else value


class BlackboardSession:
    """Persisted cookie jar + XSRF token, replayed over plain HTTPS."""

    def __init__(self, base_url: str, data_home: Path, profile: str) -> None:
        self.base_url = base_url
        self._path = session_path(data_home, profile)
        self._cookies: dict[str, str] = {}
        self._xsrf: str | None = None
        self.keepalive = KeepaliveHealth()
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

    @property
    def expires_at(self) -> float | None:
        """Fim da janela de inatividade do cookie atual (unix ts), se conhecido."""
        bbrouter = self._cookies.get("BbRouter")
        return extract_expires(bbrouter) if bbrouter else None

    def keepalive_failing(self, now: float | None = None) -> bool:
        """Pings falhando E menos de 2 h de sessão: hora de chamar o dono."""
        expires_at = self.expires_at
        if self.keepalive.consecutive_failures == 0 or expires_at is None:
            return False
        return expires_at - (time.time() if now is None else now) < EXPIRY_WARNING_S

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

    def export_cookies(self) -> list[dict[str, Any]]:
        """O jar no formato que `adopt` aceita (inclui rotação absorvida em `get`)."""
        return [{"name": name, "value": value} for name, value in self._cookies.items()]

    def reload_from_disk(self) -> bool:
        """Recarrega `session.json`; True se trouxe cookie DIFERENTE e utilizável.

        A sessão é lida UMA vez, no `__init__`. Sem esta recarga, um
        `blackboard-mcp login` feito por fora não curava a bridge em execução:
        o processo seguia com o cookie morto até alguém rodar um caminho via
        Playwright que fizesse `adopt()`. E o keep-alive, que desiste ao levar
        `SessionStale`, ficava inerte para sempre — o mecanismo existia e não
        alcançava o caso real. Observado ao vivo em 2026-09-05: bridge de pé
        desde 10:02 com sessão vencida, e só às 13:25 (quando um download
        forçou o caminho com browser) o `session.json` foi reescrito.
        """
        antes = (self._cookies.get("BbRouter"), self._xsrf)
        self._load()
        depois = (self._cookies.get("BbRouter"), self._xsrf)
        return depois != antes and self.configured

    def clear(self) -> None:
        self._cookies = {}
        self._xsrf = None
        if self._path.exists():
            self._path.unlink()

    async def get(
        self, path: str, params: dict[str, str] | None = None, *, _retry_after_reload: bool = True
    ) -> Any:
        """GET one internal `/learn/api/v1/...` path; returns decoded JSON.

        A recursive tree walk fans out into dozens of these calls per
        course; a transient connect/read blip (observed live: this host's
        network proxy occasionally drops one request out of many) must not
        abort the whole walk. Retried a few times with a short backoff —
        never on 401/403/bad-JSON, which are real auth failures, not
        network noise.
        """
        if not self.configured and not self.reload_from_disk():
            raise SessionStale("sessao nao configurada; faca login")
        last_error: httpx.TransportError | None = None
        for attempt in range(3):
            try:
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
                break
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
        else:
            raise last_error  # pragma: no cover — loop always breaks or raises above
        content_type = response.headers.get("content-type", "")
        if response.status_code < 400:
            # Só resposta aceita rotaciona o jar: persistir Set-Cookie de uma
            # resposta recusada gravaria o jar velho por cima de um
            # session.json novo trazido de fora, antes da recarga abaixo.
            self._absorb_rotated_cookies(response)
        if response.status_code >= 400:
            # Antes de declarar a sessão morta, relê o disco: pode haver login
            # NOVO feito por fora enquanto este processo seguia com o cookie
            # velho. Só uma vez, e só se o cookie de fato mudou — sem isso
            # viraria laço de retry contra um 401 legítimo.
            if _retry_after_reload and self.reload_from_disk():
                return await self.get(path, params, _retry_after_reload=False)
            if response.status_code != 401 and path != _HEALTH_PATH and await self._alive():
                raise BlackboardRequestRejected(response.status_code, path)
            raise SessionStale(f"a sessao Blackboard foi recusada ({response.status_code})")
        if "json" not in content_type:
            raise SessionStale("a API Blackboard nao retornou JSON (sessao provavelmente expirada)")
        return response.json()

    async def _alive(self) -> bool:
        """A sessão responde `users/me`? Decide entre recusa e sessão morta."""
        try:
            async with httpx.AsyncClient(base_url=self.base_url, cookies=self._cookies, timeout=15.0) as client:
                response = await client.get(
                    _HEALTH_PATH,
                    headers={"X-Requested-With": "XMLHttpRequest", "X-Blackboard-XSRF": self._xsrf or "",
                             "Accept": "application/json"},
                )
        except httpx.TransportError:
            return False
        return response.status_code == 200 and "json" in response.headers.get("content-type", "")

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


__all__ = [
    "BlackboardRequestRejected", "BlackboardSession", "EXPIRY_WARNING_S", "KeepaliveHealth", "SessionStale",
    "extract_expires", "extract_xsrf", "session_path",
]
