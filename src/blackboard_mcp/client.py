from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

    async def begin_login(self, timeout_s: int = 600) -> dict[str, Any]:
        """Open interactive Chrome. User types credentials; no credential is observed."""
        playwright, context, attached = await self._context(headless=False)
        try:
            page = await self._page(context)
            await self._open_course(page)
            deadline = asyncio.get_running_loop().time() + timeout_s
            while asyncio.get_running_loop().time() < deadline:
                if page.url.startswith(self.settings.base_url + "/ultra"):
                    return {"authenticated": True, "profile": self.settings.profile}
                await asyncio.sleep(2)
            return {"authenticated": False, "profile": self.settings.profile, "reason": "login_timeout"}
        finally:
            await self._close(playwright, context, attached=attached)

    def login_url(self) -> str:
        """Validated entrypoint for the system Chrome login command."""
        url = f"{self.settings.base_url}/ultra/course"
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "bb.cruzeirodosulvirtual.com.br":
            raise ValueError("BLACKBOARD_BASE_URL nao e um host permitido")
        return url

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
        for raw in results:
            normalized = normalize_tree_row(raw, depth=depth)
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

    async def download_content(self, course_id: str, content_id: str) -> dict[str, str | int]:
        """Download one owner-requested leaf item without persisting its signed URL.

        Dispatches by `contentHandler`: `resource/x-bb-externallink` items
        (achado real 2026-09-02: Blackboard's own "Arquivo em PDF" material
        type) point at a URL rather than a rendered outline element, and a
        direct authenticated GET is both simpler and more reliable than
        clicking through the outline — Ultra's click-and-intercept flow for
        this content type passes through an interstitial HTML response that
        lies about its `content-type` before the real PDF bytes ever arrive.
        Every other content type keeps the existing click-and-intercept path.
        """
        if not course_id.startswith("_") or not course_id.endswith("_1"):
            raise ValueError("course_id invalido")
        if not content_id.startswith("_") or not content_id.endswith("_1"):
            raise ValueError("content_id invalido")
        item = await self._rest_get(f"/learn/api/v1/courses/{course_id}/contents/{content_id}")
        title = str(item.get("title") or "")
        if str(item.get("contentHandler") or "") == "resource/x-bb-externallink":
            return await self._download_external_link(course_id, content_id, title, item)
        return await self._download_via_playwright(course_id, content_id, title)

    async def _download_external_link(
        self, course_id: str, content_id: str, title: str, item: dict[str, Any]
    ) -> dict[str, str | int]:
        """Only followed when the link stays on Blackboard's own host — this
        content type is ALSO how a professor links to a genuinely external
        site (YouTube, an article), which must never receive our session
        cookies nor be silently treated as an archivable file."""
        from .downloads import MAX_DOWNLOAD_BYTES, download_dir, persist_download

        detail = (item.get("contentDetail") or {}).get("resource/x-bb-externallink") or {}
        url = str(detail.get("url") or "")
        expected_host = (urlparse(self.settings.base_url).hostname or "").lower()
        actual_host = (urlparse(url).hostname or "").lower()
        if not url or not actual_host or actual_host != expected_host:
            raise ValueError("link externo nao aponta para o proprio Blackboard; nao arquivado automaticamente")
        async with httpx.AsyncClient(cookies=self._session._cookies, follow_redirects=True, timeout=30.0) as hc:
            response = await hc.get(url)
            if response.status_code >= 400:
                raise ValueError("Blackboard recusou o link do material")
            declared_size = response.headers.get("content-length")
            if declared_size and declared_size.isdecimal() and int(declared_size) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
            payload = response.content
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
        directory = download_dir(self.settings.data_home, course_id)
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        return persist_download(
            self.settings.data_home, course_id=course_id, content_id=content_id,
            title=title, suggested_filename=title, temporary_path=temporary,
        )

    async def _download_via_playwright(self, course_id: str, content_id: str, title: str) -> dict[str, str | int]:
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
                if not isinstance(path, str) or not path.startswith(f"/ultra/courses/{course_id}/"):
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

            page.on("response", observe)
            await link.click(timeout=5_000)
            try:
                response = await asyncio.wait_for(pdf_response, timeout=30)
            finally:
                page.remove_listener("response", observe)
            declared_size = response.headers.get("content-length")
            from .downloads import MAX_DOWNLOAD_BYTES, download_dir
            if declared_size and declared_size.isdecimal() and int(declared_size) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
            payload = await response.body()
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
            directory = download_dir(self.settings.data_home, course_id)
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
            )
        finally:
            await page.close()
            await self._close(playwright, context, attached=attached)

    async def archive_declared_pdfs(self, course_id: str) -> dict[str, Any]:
        """Archive only item titles that explicitly declare PDF content."""
        from .archive import archive_declared_pdfs
        from .sync import save_snapshot

        items = await self.list_course_tree(course_id)
        save_snapshot(self.settings.data_home, course_id, items)
        return await archive_declared_pdfs(
            data_home=self.settings.data_home,
            course_id=course_id,
            items=items,
            download=self.download_content,
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
