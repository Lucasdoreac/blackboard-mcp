from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import BrowserContext, Page, async_playwright

from .config import Settings
from .content_tree import is_container, normalize_tree_row
from .session import BlackboardSession, SessionStale


class AuthenticationRequired(RuntimeError):
    """No valid Blackboard session is available in the local profile."""


def prepare_profile(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    os.chmod(path, 0o700)
    ensure_pdfs_download_externally(path)


def ensure_pdfs_download_externally(profile_dir: Path) -> None:
    """Chrome's built-in PDF viewer intercepts `application/pdf` responses to
    render them inline; when it does, what Playwright's `response.body()`
    captures for that same response is not reliably the raw file bytes.

    Achado real (2026-09-02): 5 PDFs in one course downloaded as non-PDF
    content (`persist_download` rejects on the missing `%PDF-` magic bytes)
    despite a correct `application/pdf` content-type and a genuine
    `*.content.blackboardcdn.com` host — the network layer was fine, the
    browser's own viewer was consuming the stream. Setting this Chrome
    preference makes the browser treat PDFs as a download instead, which
    keeps the response Playwright observes as the untouched file.

    Merges into the existing `Preferences` JSON rather than overwriting it —
    this profile also carries the real Blackboard login session.
    """
    prefs_path = profile_dir / "Default" / "Preferences"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if prefs_path.exists():
        try:
            data = json.loads(prefs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    plugins = data.setdefault("plugins", {})
    if plugins.get("always_open_pdf_externally") is True:
        return
    plugins["always_open_pdf_externally"] = True
    prefs_path.write_text(json.dumps(data), encoding="utf-8")
    prefs_path.chmod(0o600)


# Rotas de conteúdo do PRÓPRIO Blackboard, conjunto FECHADO. A checagem
# original só aceitava `/ultra/courses/<id>/` — e isso nunca foi sobre formato,
# era sobre ROTA: arquivo autoral do professor é servido em `/bbcswebdav/`
# (medido ao vivo em 2026-09-05: `Exercicio1_2.md` ->
# `/bbcswebdav/pid-23612017-dt-content-rid-335271614_1/xid-335271614_1`), então
# TODO material subido por quem dá a aula caía fora, independentemente da
# extensão. A intenção ("nunca sair do Blackboard") continua intacta: o path é
# resolvido contra a página atual, mesma origem, e o conjunto segue fechado.
def _is_blackboard_content_route(path: str, course_id: str) -> bool:
    return path.startswith(f"/ultra/courses/{course_id}/") or path.startswith("/bbcswebdav/")


def login_stage(urls: list[str], base_url: str) -> tuple[str, str | None]:
    """Onde está o login, lido só das URLs das abas (nunca navega).

    `("blackboard", host)` se alguma aba chegou ao Ultra do host configurado;
    `("other_host", host)` se há aba web em OUTRO host — o portal da
    instituição, onde o dono parou em 2026-09-14 achando que já estava logado;
    `("waiting", None)` caso contrário. Só o host é devolvido: URL de SSO
    carrega token no path/query e não pode ir para o terminal.
    """
    expected = urlparse(base_url)
    other: str | None = None
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.scheme == expected.scheme and parsed.netloc == expected.netloc and parsed.path.startswith("/ultra"):
            return "blackboard", parsed.netloc
        if parsed.netloc != expected.netloc and other is None:
            other = parsed.netloc
    return ("other_host", other) if other else ("waiting", None)


class BlackboardClient:
    """Keeps authentication inside a dedicated, persistent local Chrome profile."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._session = BlackboardSession(settings.base_url, settings.data_home, settings.profile)

    async def _context(self, *, headless: bool) -> tuple[Any, BrowserContext, bool]:
        prepare_profile(self.settings.profile_dir)
        playwright = await async_playwright().start()
        try:
            await asyncio.to_thread(
                urllib.request.urlopen,
                f"http://127.0.0.1:{self.settings.debug_port}/json/version",
                timeout=0.25,
            )
            browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.settings.debug_port}")
            if not browser.contexts:
                raise RuntimeError("Chrome remoto nao disponibilizou um contexto")
            return playwright, browser.contexts[0], True
        except Exception:
            pass
        context = await playwright.chromium.launch_persistent_context(
            str(self.settings.profile_dir),
            executable_path=self.settings.chrome_path,
            headless=headless,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        return playwright, context, False

    async def _close(self, playwright: Any, context: BrowserContext, *, attached: bool) -> None:
        if not attached:
            await context.close()
        await playwright.stop()

    async def _page(self, context: BrowserContext) -> Page:
        # Never navigate the user's visible Blackboard tab. Every read gets a
        # disposable page in the same authenticated browser context.
        return await context.new_page()

    async def _open_course(self, page: Page) -> None:
        """WARP can briefly replace the host route while Chrome starts."""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                await page.goto(f"{self.settings.base_url}/ultra/course", wait_until="domcontentloaded")
                # An expired session bounces via a CLIENT-SIDE redirect (to
                # "?new_loc=...") that fires AFTER domcontentloaded, not
                # before. Without this settle window, page.url still reads
                # "/ultra/course" for a few seconds even when the session is
                # dead, making every caller of _require_base_url (including
                # auth_status) report a false "authenticated".
                await page.wait_for_timeout(3000)
                return
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    break
                await asyncio.sleep(2 * (attempt + 1))
        raise RuntimeError("nao foi possivel abrir o Blackboard; verifique a conexao e tente novamente") from last_error

    def _require_base_url(self, url: str) -> None:
        parsed = urlparse(url)
        expected = urlparse(self.settings.base_url)
        if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc or not parsed.path.startswith("/ultra"):
            raise AuthenticationRequired("a sessao redirecionou para login")

    async def complete_login(
        self,
        timeout_s: float = 600,
        interval_s: float = 3,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Mesmo formato do `nlm login`: espera o dono concluir o login na janela
        CDP, captura o cookie UMA vez, prova por REST e só então grava
        `session.json`. Depois disso o Chrome pode ser fechado.

        Antes, `login` só abria a janela e saía: o cookie era capturado de forma
        preguiçosa, no primeiro comando que precisasse do Blackboard — e só se a
        janela ainda estivesse aberta. O poll aqui LÊ as URLs das abas, nunca
        navega: abrir uma aba a cada poll (o que `auth_status` faz) atropelaria
        o SSO/MFA em andamento na janela do dono.
        """
        notify = on_progress or (lambda _msg: None)
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline = started + timeout_s
        next_heartbeat = started + 30
        hinted_host: str | None = None
        browser = None
        playwright = await async_playwright().start()
        try:
            while loop.time() < deadline:
                if browser is None or not browser.is_connected():
                    try:
                        browser = await playwright.chromium.connect_over_cdp(
                            f"http://127.0.0.1:{self.settings.debug_port}"
                        )
                    except Exception:
                        browser = None
                if browser is not None and browser.contexts:
                    context = browser.contexts[0]
                    stage, host = login_stage([page.url for page in context.pages], self.settings.base_url)
                    if stage == "blackboard":
                        try:
                            await self._adopt_verified_session(await context.cookies(self.settings.base_url))
                            return {"authenticated": True, "profile": self.settings.profile, "session_saved": True}
                        except SessionStale:
                            # A aba pode estar em /ultra por instantes antes do
                            # redirect client-side de uma sessão vencida — a
                            # prova por REST é quem decide; segue esperando.
                            pass
                    elif stage == "other_host" and host != hinted_host:
                        hinted_host = host
                        notify(
                            f"A janela esta em {host}, que nao e o Blackboard. Entrar no portal nao basta: "
                            f"abra {self.settings.base_url}/ultra/course nesta mesma janela."
                        )
                if loop.time() >= next_heartbeat:
                    notify(f"ainda aguardando o login... ({int(loop.time() - started)}s)")
                    next_heartbeat += 30
                await asyncio.sleep(interval_s)
            return {"authenticated": False, "profile": self.settings.profile, "reason": "login_timeout"}
        finally:
            # Só desconecta o NOSSO cliente CDP; a janela do dono fica como está.
            await playwright.stop()

    async def _adopt_verified_session(self, cookies: list[dict[str, Any]]) -> None:
        """Prova o cookie num jar descartável antes de sobrescrever `session.json`."""
        with tempfile.TemporaryDirectory() as scratch:
            probe = BlackboardSession(self.settings.base_url, Path(scratch), self.settings.profile)
            probe.adopt(cookies)
            await probe.get("/learn/api/v1/users/me", _retry_after_reload=False)
            self._session.adopt(probe.export_cookies())

    def login_url(self) -> str:
        """Validated entrypoint for the system Chrome login command.

        `base_url` is admin-configured (env var, or `blackboard-mcp setup`'s
        persisted per-profile config), never third-party or network input —
        so this only needs to reject a malformed value (missing scheme/host),
        not compare against one specific institution. Any Blackboard Ultra
        instance the person configures for their own profile is valid.
        """
        parsed = urlparse(self.settings.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("BLACKBOARD_BASE_URL invalido: use https://<host-do-blackboard>")
        return f"{self.settings.base_url}/ultra/course"

    def open_login_window(self) -> dict[str, str | bool]:
        """Open the owner-visible, CDP-enabled browser used for manual reauth."""
        prepare_profile(self.settings.profile_dir)
        subprocess.Popen(
            [
                self.settings.chrome_path,
                f"--user-data-dir={self.settings.profile_dir}",
                f"--remote-debugging-port={self.settings.debug_port}",
                "--remote-debugging-address=127.0.0.1",
                "--new-window",
                self.login_url(),
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "opened": True,
            "profile": self.settings.profile,
            "next_step": "conclua o login no Chrome e use auth_status",
        }

    async def _authenticated_page(self) -> tuple[Any, BrowserContext, Page, bool]:
        playwright, context, attached = await self._context(headless=True)
        page = await self._page(context)
        try:
            await self._open_course(page)
            self._require_base_url(page.url)
            return playwright, context, page, attached
        except Exception:
            # Real incident (2026-09-04): when `attached=True` (CDP-attached
            # to a real, externally-managed Chrome — every non-headless call
            # today), `_close()` deliberately never closes the shared
            # CONTEXT, and `playwright.stop()` only disconnects OUR client,
            # it does not close a tab already open in that real browser. A
            # stale session made every subsequent call hit this except
            # branch, and 15 orphaned tabs accumulated in the owner's own
            # window before anyone noticed. The page THIS call opened is
            # ours to close either way.
            await page.close()
            await self._close(playwright, context, attached=attached)
            raise

    async def _refresh_session_from_browser(self) -> None:
        """The only place Playwright still runs for a READ path: extract a
        fresh cookie jar (and the XSRF embedded in BbRouter) from the
        persistent Chrome profile. Only needed on first use after login, or
        after the REST session goes genuinely stale."""
        playwright, context, page, attached = await self._authenticated_page()
        try:
            cookies = await context.cookies(self.settings.base_url)
        finally:
            await page.close()
            await self._close(playwright, context, attached=attached)
        self._session.adopt(cookies)

    async def _rest_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """GET one internal `/learn/api/v1/...` endpoint, no browser in the
        common case. Retries exactly once through a fresh Playwright cookie
        extraction if the persisted session was rejected."""
        if not self._session.configured:
            await self._refresh_session_from_browser()
        try:
            return await self._session.get(path, params)
        except SessionStale:
            await self._refresh_session_from_browser()
            try:
                return await self._session.get(path, params)
            except SessionStale as exc:
                raise AuthenticationRequired("a sessao Blackboard expirou; refaca o login") from exc

    async def auth_status(self) -> dict[str, Any]:
        try:
            await self._rest_get("/learn/api/v1/users/me")
        except (AuthenticationRequired, SessionStale) as exc:
            return {"authenticated": False, "profile": self.settings.profile, "reason": type(exc).__name__}
        return {"authenticated": True, "profile": self.settings.profile}

    async def list_terms(self) -> list[str]:
        """List the terms exposed by the Ultra course filter without selecting one."""
        playwright, context, page, attached = await self._authenticated_page()
        try:
            await page.wait_for_selector('[role="combobox"]', timeout=15_000)
            combo = page.locator('[role="combobox"]').first
            await combo.click(timeout=3_000)
            await page.wait_for_timeout(250)
            terms = await page.evaluate(
                """() => Array.from(document.querySelectorAll('[role="option"]'))
                    .map(x => (x.textContent || '').trim()).filter(Boolean)"""
            )
            return [term for term in terms if isinstance(term, str)]
        finally:
            await page.close()
            await self._close(playwright, context, attached=attached)

    async def list_courses(self, term: str | None = None) -> list[dict[str, str]]:
        """Read the Ultra course cards; public REST needs a separate app credential."""
        playwright, context, page, attached = await self._authenticated_page()
        try:
            if term:
                await page.wait_for_selector('[role="combobox"]', timeout=15_000)
                await page.locator('[role="combobox"]').first.click(timeout=3_000)
                option = page.locator('[role="option"]').filter(has_text=term)
                if await option.count() != 1:
                    raise ValueError(f"semestre nao encontrado: {term}")
                await option.click(timeout=3_000)
                await page.wait_for_function(
                    "term => document.querySelector('[role=combobox]')?.textContent?.includes(term)",
                    arg=term,
                    timeout=10_000,
                )
            await page.wait_for_selector("article[data-course-id]", timeout=15_000)
            await page.wait_for_function(
                """() => Array.from(document.querySelectorAll('article[data-course-id]'))
                    .some(card => (card.querySelector('.js-course-title-element')?.textContent || '').trim())""",
                timeout=15_000,
            )
            rows = await page.evaluate(
                """() => Array.from(document.querySelectorAll('article[data-course-id]')).map(card => ({
                    id: card.getAttribute('data-course-id') || '',
                    name: (card.querySelector('.js-course-title-element')?.textContent || '').trim(),
                    course_code: (card.querySelector('.multi-column-course-id')?.textContent || '').trim(),
                    availability: (card.querySelector('.status-text')?.textContent || '').trim(),
                })).filter(row => row.id && row.name)"""
            )
            if not isinstance(rows, list):
                raise RuntimeError("a lista de cursos nao carregou no formato esperado")
            return rows
        finally:
            await page.close()
            await self._close(playwright, context, attached=attached)

    async def _walk_content_tree(self, course_id: str, node_id: str, depth: int) -> list[dict[str, Any]]:
        """Recurse `contents/{id}/children` — the same internal REST endpoint
        Blackboard's own outline page calls to render the folder/lesson
        expansion, confirmed against real course content. `hasChildren` is
        unreliable in the `@view=Summary` response (observed `None` on real
        folders that do have children), so recursion is driven by
        `contentHandler` (folder/lesson) instead."""
        data = await self._rest_get(
            f"/learn/api/v1/courses/{course_id}/contents/{node_id}/children",
            params={"@view": "Summary", "limit": "200"},
        )
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise RuntimeError("a arvore de conteudo nao carregou no formato esperado")
        rows: list[dict[str, Any]] = []
        parent_id = node_id if node_id != "ROOT" else None
        for raw in results:
            normalized = normalize_tree_row(raw, depth=depth, parent_id=parent_id)
            if normalized is None:
                continue
            rows.append(normalized)
            if is_container(raw):
                rows.extend(await self._walk_content_tree(course_id, normalized["id"], depth + 1))
        return rows

    async def list_course_tree(self, course_id: str) -> list[dict[str, str | int]]:
        """Full course inventory (folders, lessons, files, assignments) via
        the internal REST API — no page render, no toggle-clicking."""
        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        return await self._walk_content_tree(course_id, "ROOT", 0)

    async def list_course_content(self, course_id: str) -> list[dict[str, str]]:
        """Flat legacy shape (id/title/text). `text` is now just the title —
        the REST tree has no innerText-preview equivalent; kept only for the
        CLI's `content` command, not consumed by the SOBER bridge."""
        tree = await self.list_course_tree(course_id)
        return [{"id": row["id"], "title": row["title"], "text": row["title"]} for row in tree]

    async def sync_course(self, course_id: str) -> dict[str, Any]:
        """Persist a local inventory snapshot and return only its deterministic diff."""
        from .sync import save_snapshot

        items = await self.list_course_tree(course_id)
        return save_snapshot(self.settings.data_home, course_id, items)

    async def download_content(
        self, course_id: str, content_id: str, kind: str = "pdf"
    ) -> dict[str, str | int]:
        """Download one owner-requested leaf item without persisting its signed URL.

        Order of preference, most robust first:

        1. `resource/x-bb-externallink` (achado real 2026-09-02: Blackboard's
           own "Arquivo em PDF" material type) — a direct authenticated GET on
           the item's own URL. Ultra's click-and-intercept flow for this type
           passes through an interstitial HTML response that lies about its
           `content-type` before the real bytes arrive.
        2. `resource/x-bb-file` with a `permanentUrl` — the item's REST
           metadata already carries a same-host `/bbcswebdav/` path. The SAME
           authenticated GET (path 1's mechanism) fetches it: **no browser**,
           so it survives a stale Chrome profile session. That session only
           the interactive `blackboard-mcp login` refreshes, while the REST
           cookie is kept alive indefinitely by `bridge.py`'s keep-alive —
           making the browser the fragile part of the old download path.
        3. Playwright click-and-intercept — the fallback, for an item with no
           usable `permanentUrl`, or when path 2's GET is rejected (e.g. the
           REST cookie itself finally lapsed and `/bbcswebdav/` bounced to a
           login page, caught by `persist_download`'s signature check).
        """
        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        if not content_id.startswith("_") or not content_id.endswith("_1"):
            raise ValueError("content_id invalido")
        item = await self._rest_get(f"/learn/api/v1/courses/{course_id}/contents/{content_id}")
        title = str(item.get("title") or "")
        if str(item.get("contentHandler") or "") == "resource/x-bb-externallink":
            return await self._download_external_link(course_id, content_id, title, item, kind)
        file_url = self._file_permanent_url(item, course_id)
        if file_url is not None:
            try:
                return await self._get_same_host_material(
                    course_id, content_id, title, file_url, kind
                )
            except (RuntimeError, ValueError):
                # The permanentUrl GET did not yield the material (REST cookie
                # finally lapsed, an unexpected redirect, a signature
                # mismatch). Fall through to the browser rather than fail —
                # worst case is the pre-existing behaviour.
                pass
        return await self._download_via_playwright(course_id, content_id, title, kind)

    def _file_permanent_url(self, item: dict[str, Any], course_id: str) -> str | None:
        """The absolute, same-host `/bbcswebdav/` URL of a `resource/x-bb-file`
        item's declared file — or None when the item does not carry one.

        `permanentUrl` is a site-relative path in the item's own REST
        metadata; it is resolved against `base_url` and then held to the SAME
        closed set of Blackboard content routes the browser path enforces
        (`_is_blackboard_content_route`) and the same host `_download_external_
        link` trusts. Anything else returns None → Playwright fallback."""
        file_ref = ((item.get("contentDetail") or {}).get("resource/x-bb-file") or {}).get("file") or {}
        raw = str(file_ref.get("permanentUrl") or "").strip()
        if not raw:
            return None
        resolved = urljoin(self.settings.base_url.rstrip("/") + "/", raw.lstrip("/"))
        parsed = urlparse(resolved)
        expected_host = (urlparse(self.settings.base_url).hostname or "").lower()
        if (parsed.hostname or "").lower() != expected_host:
            return None
        if not _is_blackboard_content_route(parsed.path, course_id):
            return None
        return resolved

    async def _get_same_host_material(
        self, course_id: str, content_id: str, title: str, url: str, kind: str = "pdf"
    ) -> dict[str, str | int]:
        """Authenticated GET of a same-host Blackboard file URL, then a
        signature-verified persist. No browser — works whenever the REST
        session cookie is valid. Shared by the externallink path and the
        `x-bb-file` `permanentUrl` fast path; the caller is responsible for
        proving `url` stays on Blackboard's own host first."""
        from .downloads import MAX_BYTES_BY_KIND, MAX_DOWNLOAD_BYTES, download_dir, persist_download

        teto = MAX_BYTES_BY_KIND.get(kind, MAX_DOWNLOAD_BYTES)
        async with httpx.AsyncClient(cookies=self._session._cookies, follow_redirects=True, timeout=30.0) as hc:
            response = await hc.get(url)
            if response.status_code >= 400:
                raise ValueError("Blackboard recusou o material")
            declared_size = response.headers.get("content-length")
            if declared_size and declared_size.isdecimal() and int(declared_size) > teto:
                raise ValueError(f"material {kind} excede o limite de {teto // 1024 // 1024} MiB")
            payload = response.content
        if len(payload) > teto:
            raise ValueError(f"material {kind} excede o limite de {teto // 1024 // 1024} MiB")
        directory = download_dir(self.settings.data_home, course_id)
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        return persist_download(
            self.settings.data_home, course_id=course_id, content_id=content_id,
            title=title, suggested_filename=title, temporary_path=temporary, kind=kind,
        )

    async def _download_external_link(
        self, course_id: str, content_id: str, title: str, item: dict[str, Any], kind: str = "pdf"
    ) -> dict[str, str | int]:
        """Only followed when the link stays on Blackboard's own host — this
        content type is ALSO how a professor links to a genuinely external
        site (YouTube, an article), which must never receive our session
        cookies nor be silently treated as an archivable file."""
        detail = (item.get("contentDetail") or {}).get("resource/x-bb-externallink") or {}
        url = str(detail.get("url") or "")
        expected_host = (urlparse(self.settings.base_url).hostname or "").lower()
        actual_host = (urlparse(url).hostname or "").lower()
        if not url or not actual_host or actual_host != expected_host:
            raise ValueError("link externo nao aponta para o proprio Blackboard; nao arquivado automaticamente")
        return await self._get_same_host_material(course_id, content_id, title, url, kind)

    async def _download_via_playwright(
        self, course_id: str, content_id: str, title: str, kind: str = "pdf"
    ) -> dict[str, str | int]:
        from .downloads import persist_download

        playwright, context, page, attached = await self._authenticated_page()
        try:
            await page.goto(f"{self.settings.base_url}/ultra/courses/{course_id}/outline", wait_until="domcontentloaded")
            self._require_base_url(page.url)
            await page.wait_for_selector("[data-content-id]", timeout=15_000)
            # A leaf may be inside one or more folders.  Expand containers only;
            # this cannot open a learning resource or mark it complete.
            for _round in range(20):
                item = page.locator(f'[data-content-id="{content_id}"]')
                if await item.count():
                    break
                toggle = page.locator(
                    'button[aria-expanded="false"][aria-controls^="learning-module-contents-"], '
                    'button[aria-expanded="false"][aria-controls^="folder-contents-"]'
                ).first
                if not await toggle.count():
                    break
                await toggle.click(timeout=2_000)
                await page.wait_for_timeout(250)
            item = page.locator(f'[data-content-id="{content_id}"]')
            if await item.count() != 1:
                raise ValueError("material nao encontrado no curso")
            # Blackboard uses either an anchor (course-authored file) or a
            # button carrying an href (institutional PDF unit) for a leaf.
            # Both are navigation controls; never use the progress checkbox.
            link = item.locator("a[href], button[href]").first
            if await link.count() != 1:
                raise ValueError("item nao oferece download direto")
            raw_href = await link.get_attribute("href")
            if raw_href:
                path = await link.evaluate("(node, href) => new URL(href, location.href).pathname", raw_href)
                if not isinstance(path, str) or not _is_blackboard_content_route(path, course_id):
                    raise ValueError("rota de download fora do Blackboard nao permitida")
            elif await link.evaluate("node => node.tagName") != "BUTTON":
                raise ValueError("item nao oferece rota de download")
            if not title:
                title_node = item.locator('[id^="content-title-"], [id^="learning-module-title-"], [id^="folder-title-"]').first
                title = (await title_node.inner_text()).strip() if await title_node.count() else ""
                if not title:
                    title = ((await item.inner_text()).split("\n")[-1]).strip()
            # Ultra renders the resource in a short-lived content-CDN frame,
            # not through a browser Download event.  Capture precisely the PDF
            # response the page receives; a second request can lose the signed
            # redirect chain.  The response URL is never logged or persisted.
            loop = asyncio.get_running_loop()
            pdf_response: asyncio.Future[Any] = loop.create_future()

            def observe(response: Any) -> None:
                host = (urlparse(response.url).hostname or "").lower()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if (
                    not pdf_response.done()
                    and response.ok
                    and host.endswith(".content.blackboardcdn.com")
                    and content_type == "application/pdf"
                ):
                    pdf_response.set_result(response)

            # DOIS caminhos, não um. O comentário acima vale para o PDF
            # institucional (frame da CDN); arquivo AUTORAL do professor, servido
            # em `/bbcswebdav/`, dispara um Download event de verdade. Esperar só
            # pela resposta da CDN fazia o `.md` baixar e o código não pegar: o
            # future nunca resolvia e morria em TimeoutError com o arquivo já em
            # disco no diretório temporário do Playwright (medido ao vivo,
            # 2026-09-05: `Lista de Exercícios — AFD`, 8669 bytes). Fica quem
            # resolver primeiro.
            baixado: asyncio.Future[Any] = loop.create_future()

            def observe_download(download: Any) -> None:
                if not baixado.done():
                    baixado.set_result(download)

            page.on("response", observe)
            page.on("download", observe_download)
            await link.click(timeout=5_000)
            try:
                pronto, pendentes = await asyncio.wait(
                    {pdf_response, baixado},
                    timeout=30,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for tarefa in pendentes:
                    tarefa.cancel()
                if not pronto:
                    raise TimeoutError("Blackboard nao entregou o material em 30s")
                vencedor = pronto.pop()
            finally:
                page.remove_listener("response", observe)
                page.remove_listener("download", observe_download)

            from .downloads import MAX_DOWNLOAD_BYTES, download_dir
            directory = download_dir(self.settings.data_home, course_id)

            if vencedor is baixado:
                # Download event: o Playwright já gravou num temporário próprio.
                origem = Path(await vencedor.result().path())
                if origem.stat().st_size > MAX_DOWNLOAD_BYTES:
                    origem.unlink(missing_ok=True)
                    raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
                    handle.write(origem.read_bytes())
                    temporary = Path(handle.name)
            else:
                response = vencedor.result()
                declared_size = response.headers.get("content-length")
                if declared_size and declared_size.isdecimal() and int(declared_size) > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
                payload = await response.body()
                if len(payload) > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
                    handle.write(payload)
                    temporary = Path(handle.name)
            return persist_download(
                self.settings.data_home,
                course_id=course_id,
                content_id=content_id,
                title=title,
                suggested_filename=title,
                temporary_path=temporary,
                kind=kind,
            )
        finally:
            await page.close()
            await self._close(playwright, context, attached=attached)

    async def archive_declared_pdfs(self, course_id: str) -> dict[str, Any]:
        """Archive item files/titles that declare PDF content, plus any
        same-host externallink (real document, never a third-party page)."""
        from .archive import archive_declared_pdfs
        from .sync import save_snapshot

        items = await self.list_course_tree(course_id)
        save_snapshot(self.settings.data_home, course_id, items)
        return await archive_declared_pdfs(
            data_home=self.settings.data_home,
            course_id=course_id,
            items=items,
            download=self.download_content,
            expected_host=(urlparse(self.settings.base_url).hostname or "").lower() or None,
        )

    def read_download_chunk(self, course_id: str, content_id: str, offset: int, length: int) -> dict[str, str | int | bool]:
        """Return a bounded verified artifact block for a local MCP client."""
        from .downloads import read_download_chunk
        return read_download_chunk(
            self.settings.data_home,
            course_id=course_id,
            content_id=content_id,
            offset=offset,
            length=length,
        )

    def list_downloads(self, course_id: str) -> list[dict[str, Any]]:
        """Return safe receipts for verified local materials in one course."""
        from .downloads import list_verified_receipts
        return list_verified_receipts(self.settings.data_home, course_id=course_id)

    async def list_assessments(self, course_id: str) -> list[dict[str, str]]:
        from .assessments import extract_assessments

        return extract_assessments(course_id, await self.list_course_tree(course_id))

    _MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

    async def _assessment_detail(self, course_id: str, content_id: str) -> dict[str, Any]:
        from .assessment_detail import parse_assessment_detail

        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        if not content_id.startswith("_") or not content_id.endswith("_1"):
            raise ValueError("content_id invalido")
        item = await self._rest_get(f"/learn/api/v1/courses/{course_id}/contents/{content_id}")
        return parse_assessment_detail(course_id, content_id, item, self.settings.base_url)

    async def get_assessment(self, course_id: str, content_id: str) -> dict[str, Any]:
        """Enunciado, prazo, tentativas e anexos de UMA atividade — só GET.
        Nunca abre tentativa: questões de um `Test` só existem dentro dela."""
        from .assessment_detail import public_view

        return public_view(await self._assessment_detail(course_id, content_id))

    async def list_course_activities(self, course_id: str) -> list[dict[str, Any]]:
        """`get_assessment` de TODA atividade do curso (inclusive sem prazo e
        vencida) — base para levar a seção de atividades ao caderno."""
        from .assessment_detail import activity_ids, public_view

        results = []
        for content_id in activity_ids(await self.list_course_tree(course_id)):
            results.append(public_view(await self._assessment_detail(course_id, content_id)))
        return results

    async def read_assessment_attachment(self, course_id: str, content_id: str, index: int) -> dict[str, Any]:
        """Bytes de UM anexo de imagem do enunciado (print de código), base64.

        Mesmo host + rota `/bbcswebdav/` provados antes do GET (o cookie nunca
        sai do Blackboard); só imagem, provada por magic byte; teto de 5 MiB."""
        import base64
        import hashlib

        from .assessment_detail import is_blackboard_redirect_hop, is_same_host_file_route, sniff_image

        detail = await self._assessment_detail(course_id, content_id)
        match = next((a for a in detail["attachments"] if a["index"] == index), None)
        if match is None:
            raise ValueError("anexo inexistente nesta atividade")
        url = match["_url"]
        if not is_same_host_file_route(url, self.settings.base_url):
            raise ValueError("anexo nao aponta para o proprio Blackboard; nao baixado")
        # Cadeia medida ao vivo (2026-09-14): host da instituição (com cookie)
        # → 302 `alt-<id>.blackboard.com/bbcswebdav/...?hash=` → 302 para si
        # mesmo → 200 PNG. Os saltos são seguidos à mão: o cookie de sessão só
        # vai no PRIMEIRO (jar sem domínio do httpx iria para todo host), e cada
        # salto seguinte precisa continuar em host do próprio Blackboard.
        async with httpx.AsyncClient(cookies=self._session._cookies, follow_redirects=False, timeout=30.0) as hc:
            response = await hc.get(url)
        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as hop_client:
            for _hop in range(5):
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                url = urljoin(url, response.headers.get("location", ""))
                if not is_blackboard_redirect_hop(url, self.settings.base_url):
                    raise ValueError("anexo redirecionou para fora do Blackboard (sessao expirada?)")
                response = await hop_client.get(url)
            else:
                raise ValueError("anexo redirecionou demais")
        if response.status_code >= 400:
            raise ValueError("Blackboard recusou o anexo")
        payload = response.content
        if len(payload) > self._MAX_ATTACHMENT_BYTES:
            raise ValueError("anexo excede o limite de 5 MiB")
        mime = sniff_image(payload)
        if mime is None:
            raise ValueError("anexo nao e imagem (png/jpeg/gif/webp)")
        return {
            "course_id": course_id,
            "content_id": content_id,
            "index": index,
            "file_name": match["file_name"],
            "mime_type": mime,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "data_b64": base64.b64encode(payload).decode("ascii"),
        }

    async def list_announcements(self, course_id: str) -> list[dict[str, str]]:
        """Full-text course announcements (title, body, published date) via
        the same internal REST API — the professor's actual text, not a
        system-generated notification."""
        from .announcements import extract_announcements

        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        data = await self._rest_get(f"/learn/api/v1/courses/{course_id}/announcements")
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise RuntimeError("os avisos do curso nao carregaram no formato esperado")
        return extract_announcements(course_id, results)

    async def list_video_descriptions(self, course_id: str) -> list[dict[str, str]]:
        """Accessibility descriptions ("#paratodosverem") already written by
        the professor next to embedded video/interactive content, on every
        document page of a course. Never opens a video player or scrapes a
        third-party embed (genial.ly, YouTube, ...) — only reads text that is
        already plain HTML the page itself renders. Checks the document's
        own body first; if that has no marker, follows any same-host
        embedded-unsafe-html block it references (mirrors
        `_download_external_link`'s host check — cookies never leave this
        host) and checks that fragment too.
        """
        from .video_descriptions import extract_paratodosverem, find_embedded_html_urls

        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        expected_host = (urlparse(self.settings.base_url).hostname or "").lower()
        results: list[dict[str, str]] = []
        for row in await self.list_course_tree(course_id):
            if row.get("content_handler") != "resource/x-bb-document":
                continue
            content_id = str(row["id"])
            detail = await self._rest_get(f"/learn/api/v1/courses/{course_id}/contents/{content_id}")
            body = detail.get("body") or {}
            text = str(body.get("rawText") or body.get("displayText") or "")
            description = extract_paratodosverem(text)
            if description is None:
                for url in find_embedded_html_urls(text):
                    if (urlparse(url).hostname or "").lower() != expected_host:
                        continue
                    async with httpx.AsyncClient(
                        cookies=self._session._cookies, follow_redirects=True, timeout=20.0
                    ) as hc:
                        response = await hc.get(url)
                    if response.status_code >= 400:
                        continue
                    description = extract_paratodosverem(response.text)
                    if description is not None:
                        break
            if description is not None:
                results.append({
                    "course_id": course_id, "content_id": content_id,
                    "title": str(row.get("title") or ""), "description": description,
                })
        return results

    async def list_course_documents(self, course_id: str) -> list[dict[str, str]]:
        """Plain text of every `resource/x-bb-document` page body in a course
        — the professor's own lecture notes / unit intro / instructions,
        written straight into the page. Reads only the body text the content
        API returns; never fetches a URL or opens an embed. Pages with too
        little text (or none) are skipped, not errors."""
        from .document_text import clean_document_body

        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        results: list[dict[str, str]] = []
        for row in await self.list_course_tree(course_id):
            if row.get("content_handler") != "resource/x-bb-document":
                continue
            content_id = str(row["id"])
            detail = await self._rest_get(
                f"/learn/api/v1/courses/{course_id}/contents/{content_id}"
            )
            body = detail.get("body") or {}
            text = clean_document_body(
                body.get("rawText"),
                body.get("displayText") or body.get("html"),
            )
            if text is None:
                continue
            results.append({
                "course_id": course_id,
                "content_id": content_id,
                "title": str(row.get("title") or ""),
                "text": text,
            })
        return results

    _MAX_TRANSCRIPT_SEGMENTS = 60  # ~5h of captions at 300s/segment — generous, still bounded
    _PAGE_VISIT_PACE_S = 2.0  # gap between consecutive document-page navigations in list_video_transcripts

    _KALTURA_MULTIREQUEST_URL = "https://cdnapisec.kaltura.com/api_v3/service/multirequest"
    # The trailing `/a.m3u8` is NOT decorative — matches the exact shape
    # Kaltura's own player requests (confirmed live by network capture) and
    # is load-bearing for `urljoin` below: without a filename after `ks/
    # {ks}`, `urljoin(playlist_url, "segmentIndex/1.vtt")` treats the KS
    # token itself as "the file" and replaces it, producing a URL with the
    # LITERAL STRING "segmentIndex" as the KS — a real incident (2026-09-04):
    # Kaltura's API answered `200 OK` with an `INVALID_KS` XML error body,
    # not an HTTP error, so `response.ok` alone doesn't catch this class of
    # mistake — the URL shape has to be right in the first place.
    _KALTURA_SERVE_VTT_URL = (
        "https://cfvod.kaltura.com/api_v3/index.php/service/caption_captionasset/"
        "action/serveWebVTT/captionAssetId/{caption_id}/segmentDuration/300/ks/{ks}/a.m3u8"
    )

    async def _fetch_transcript_from_kaltura(self, page: Page, *, entry_id: str, partner_id: str) -> str | None:
        """Fetch a transcript given ALREADY-KNOWN, stable Kaltura ids — the
        one part of this flow with no Blackboard dependency at all: entry_id/
        partner_id are public identifiers for an embeddable widget, and the
        session token is minted fresh here via Kaltura's own
        `session::startWidgetSession`, scoped to `partner_id`, not to any
        Blackboard cookie. `page` only needs to be a real browser context —
        it does not need to be logged into Blackboard, or even ever have
        visited Blackboard (real incident 2026-09-04: a plain, non-browser
        `httpx` call to this exact same endpoint hung indefinitely — Kaltura
        appears to require a genuine browser networking stack).

        Every Kaltura request below carries a `Referer` for our own
        institution's Blackboard domain. Real incident (2026-09-04): without
        it, `caption_captionasset::list`/`serveWebVTT` still answer `200 OK`
        but with an EMPTY playlist/body — no error, just silent degradation
        (Kaltura's domain access-control checks the referring domain, not
        session privilege as first suspected). `page.request` is Playwright's
        APIRequestContext, which — unlike a real in-page `fetch()` — never
        auto-sets `Referer` to the page's current URL, so this has to be
        explicit. Confirmed live: a BARE domain (no course/content path) is
        enough — the check is domain-level, not path-level.
        """
        from .video_transcripts import parse_vtt_cues, parse_vtt_playlist, select_ready_caption_asset

        referer = {"Referer": f"{self.settings.base_url}/"}
        caption_response = await page.request.post(
            self._KALTURA_MULTIREQUEST_URL,
            form={
                "1:service": "session", "1:action": "startWidgetSession", "1:widgetId": f"_{partner_id}",
                "2:service": "caption_captionasset", "2:action": "list",
                "2:filter:entryIdEqual": entry_id, "2:ks": "{1:result:ks}",
                "format": "1",
            },
            headers=referer,
        )
        if not caption_response.ok:
            return None
        try:
            session_result, captions_result = await caption_response.json()
        except (ValueError, TypeError):
            return None
        ks = session_result.get("ks") if isinstance(session_result, dict) else None
        captions = captions_result.get("objects") if isinstance(captions_result, dict) else None
        if not ks or not isinstance(captions, list):
            return None
        caption = select_ready_caption_asset(captions)
        if caption is None or not caption.get("id"):
            return None
        playlist_url = self._KALTURA_SERVE_VTT_URL.format(caption_id=caption["id"], ks=ks)
        playlist_response = await page.request.get(playlist_url, headers=referer)
        if not playlist_response.ok:
            return None
        segments = parse_vtt_playlist(await playlist_response.text())[: self._MAX_TRANSCRIPT_SEGMENTS]
        chunks: list[str] = []
        for segment in segments:
            segment_response = await page.request.get(urljoin(playlist_url, segment), headers=referer)
            if segment_response.ok:
                chunks.append(parse_vtt_cues(await segment_response.text()))
        transcript = " ".join(chunk for chunk in chunks if chunk).strip()
        return transcript or None

    async def _discover_kaltura_ids(self, page: Page, *, course_id: str, content_id: str) -> tuple[str, str] | None:
        """Navigate an AUTHENTICATED Blackboard page and observe which
        Kaltura video (if any) it embeds — `entry_id`/`partner_id` fire
        within the first second or two of any Kaltura embed bootstrapping,
        regardless of caption settings (unlike the caption request itself,
        which the player may never issue — see `_fetch_transcript_from_
        kaltura`'s docstring). Returns None (not an error) for the common
        case: most document pages embed no video at all.
        """
        from .video_transcripts import extract_kaltura_ids

        entry_id: str | None = None
        partner_id: str | None = None

        def observe(request: Any) -> None:
            nonlocal entry_id, partner_id
            if entry_id and partner_id:
                return
            found_entry, found_partner = extract_kaltura_ids(request.url)
            entry_id = entry_id or found_entry
            partner_id = partner_id or found_partner

        page.on("request", observe)
        try:
            await page.goto(
                f"{self.settings.base_url}/ultra/courses/{course_id}/document/{content_id}?view=content&state=view",
                wait_until="domcontentloaded",
            )
            self._require_base_url(page.url)
            for _ in range(10):
                if entry_id and partner_id:
                    break
                await page.wait_for_timeout(1000)
        finally:
            page.remove_listener("request", observe)
        if entry_id and partner_id:
            return entry_id, partner_id
        return None

    async def get_video_transcript(self, course_id: str, content_id: str) -> str | None:
        """Fetch the Kaltura caption transcript embedded in one document
        page, if any — None (not an error) when the page has no Kaltura
        video, which is most document pages. Real incident (2026-09-04): the
        owner identified that every "Unidade" PDF has a companion lecture
        video, embedded via Kaltura (`#player-gui`), confirmed live by
        network capture.

        Real incident (2026-09-04, follow-up #1): passively waiting for the
        player to request its caption track missed a REAL, ready caption —
        confirmed via Kaltura's own `caption_captionasset::list` action that
        a `status: 2` asset existed, but the player's own `displayOnPlayer`
        flag was `false` for it, so it never auto-requested it (a student
        would have to click the player's CC button; this project never
        simulates UI clicks on a 3rd-party player). Fixed by querying
        Kaltura's caption list directly instead of waiting on the player.

        Real incident (2026-09-04, follow-up #2): a full course re-check
        re-walked EVERY document page every time, including pages already
        confirmed empty — the owner's own semester never changes this
        content after the fact. `video_transcript_cache` remembers the
        verdict per `content_id`: `has_video=False` skips this page with NO
        browser work at all; `has_video=True` with `entry_id`/`partner_id`
        known skips the (expensive, Blackboard-login-dependent) discovery
        navigation and only opens a BARE page scoped to Kaltura's own
        domain — no Blackboard session required for that part at all.
        """
        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        if not content_id.startswith("_") or not content_id.endswith("_1"):
            raise ValueError("content_id invalido")
        from . import video_transcript_cache

        cached = video_transcript_cache.get_entry(self.settings.data_home, course_id, content_id)
        if cached is not None:
            if not cached.get("has_video"):
                return None
            entry_id, partner_id = cached.get("entry_id"), cached.get("partner_id")
            if entry_id and partner_id:
                playwright, context, attached = await self._context(headless=True)
                page = await self._page(context)
                try:
                    return await self._fetch_transcript_from_kaltura(page, entry_id=entry_id, partner_id=partner_id)
                finally:
                    await page.close()
                    await self._close(playwright, context, attached=attached)

        playwright, context, page, attached = await self._authenticated_page()
        try:
            ids = await self._discover_kaltura_ids(page, course_id=course_id, content_id=content_id)
            # Real incident (2026-09-04): back-to-back FULL DISCOVERY
            # navigations (real Playwright page loads against Blackboard's
            # own SPA, not a REST call) made Ultra throw its own error
            # screen mid-walk. Only a genuine navigation pays this pace — a
            # cache hit (skip, or the bare Kaltura-only fetch above) never
            # touches Blackboard's SPA at all and has nothing to be gentle
            # about.
            await asyncio.sleep(self._PAGE_VISIT_PACE_S)
            if ids is None:
                video_transcript_cache.save_entry(self.settings.data_home, course_id, content_id, has_video=False)
                return None
            entry_id, partner_id = ids
            video_transcript_cache.save_entry(
                self.settings.data_home, course_id, content_id,
                has_video=True, entry_id=entry_id, partner_id=partner_id,
            )
            return await self._fetch_transcript_from_kaltura(page, entry_id=entry_id, partner_id=partner_id)
        finally:
            await page.close()
            await self._close(playwright, context, attached=attached)

    async def list_video_transcripts(self, course_id: str) -> list[dict[str, str]]:
        """Kaltura caption transcripts for every document page of a course
        that has one — companion to `list_video_descriptions` (the
        accessibility-text path), used when the page instead embeds a real
        Kaltura lecture video.

        Real incident (2026-09-04): a "Videoaula" FOLDER wraps a single
        `resource/x-bb-document` child that embeds the player — the player
        only initializes when the FOLDER's own URL is visited (Ultra
        collapses a single-item folder into that view); navigating to the
        child document's own URL loads nothing (confirmed live, zero
        network activity). So a document page that yields no transcript on
        its own URL gets ONE retry on its parent folder's URL, when it has
        one — cheap when the retry also finds nothing (a page can genuinely
        have no video), necessary when the video only ever renders there.
        """
        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        results: list[dict[str, str]] = []
        for row in await self.list_course_tree(course_id):
            if row.get("content_handler") != "resource/x-bb-document":
                continue
            content_id = str(row["id"])
            transcript = await self._get_video_transcript_safe(course_id, content_id)
            if transcript is None:
                parent_id = row.get("parent_id")
                if parent_id:
                    transcript = await self._get_video_transcript_safe(course_id, str(parent_id))
            if transcript is not None:
                results.append({
                    "course_id": course_id, "content_id": content_id,
                    "title": str(row.get("title") or ""), "transcript": transcript,
                })
        return results

    async def _get_video_transcript_safe(self, course_id: str, content_id: str) -> str | None:
        """Same contract as `get_video_transcript`, but a real failure on ONE
        page (a slow/broken Blackboard render, a network hiccup talking to
        Kaltura) degrades to "no transcript found" instead of aborting the
        whole course walk — real incident (2026-09-04): a single page's
        `TimeoutError` killed `list_video_transcripts` before it reached any
        of the course's other, healthy pages.

        Also CACHES the failure as `has_video=False` — real incident
        (2026-09-04, follow-up): a page that always errors (institution
        bloat unrelated to any lecture) was walked again on every single
        run, forever, because an exception short-circuits `get_video_
        transcript` before it reaches its own cache-write. Course content is
        stable within a semester (the owner's own words), so a page broken
        today is expected to be the same page tomorrow — deliberate
        trade-off: a genuinely transient failure (one bad network blip) also
        gets skipped from then on, same as a permanently broken page. Never
        caches a `ValueError` (a real bug in the caller, not a fact about
        the page) — that still propagates uncaught.
        """
        from . import video_transcript_cache

        try:
            return await self.get_video_transcript(course_id, content_id)
        except ValueError:
            raise
        except Exception:
            video_transcript_cache.save_entry(self.settings.data_home, course_id, content_id, has_video=False)
            return None

    async def sync_available_courses(self, term: str | None = None) -> list[dict[str, Any]]:
        """Synchronize each visible, available course one at a time."""
        results: list[dict[str, Any]] = []
        for course in await self.list_courses(term):
            if course.get("availability") != "Aberto":
                continue
            result = await self.sync_course(course["id"])
            results.append({"course": course, "sync": result})
        return results

    def register_course(self, course_id: str, title: str) -> dict[str, str]:
        """Remember an owner-confirmed course even if Ultra hides its card."""
        from .catalog import register_course
        return register_course(self.settings.data_home, course_id=course_id, title=title)

    def list_registered_courses(self) -> list[dict[str, str]]:
        from .catalog import load_courses
        return load_courses(self.settings.data_home)

    def bind_notebook(self, course_id: str, notebook_id: str) -> dict[str, str]:
        from .catalog import bind_notebook
        return bind_notebook(self.settings.data_home, course_id=course_id, notebook_id=notebook_id)

    async def sync_registered_courses(self) -> list[dict[str, Any]]:
        return [
            {"course": course, "sync": await self.sync_course(course["id"])}
            for course in self.list_registered_courses()
        ]
