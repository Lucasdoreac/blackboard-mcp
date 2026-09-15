from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .client import BlackboardClient
from .config import Settings


def create_server(profile: str) -> FastMCP:
    client = BlackboardClient(Settings.from_profile(profile))
    server = FastMCP("blackboard-mcp")

    @server.tool()
    async def auth_status() -> dict:
        """Check whether the local Blackboard profile has a valid session."""
        return await client.auth_status()

    @server.tool()
    async def reauthenticate() -> dict:
        """Recover an expired session automatically (profile SSO in the dedicated
        Chrome, cookie proven by REST before saving); needs_owner=True when MFA
        is required. No credential is ever read or typed."""
        return await client.reauthenticate()

    @server.tool()
    async def list_courses(term: str = "") -> list[dict[str, str]]:
        """List courses available to the signed-in account, read-only."""
        return await client.list_courses(term or None)

    @server.tool()
    async def register_course(course_id: str, title: str) -> dict:
        """Register an owner-confirmed course that Ultra may hide from cards."""
        return client.register_course(course_id, title)

    @server.tool()
    async def list_registered_courses() -> list[dict]:
        """List owner-registered courses, including hidden-but-accessible ones."""
        return client.list_registered_courses()

    @server.tool()
    async def sync_registered_courses() -> list[dict]:
        """Synchronize owner-registered courses only; no material is downloaded."""
        return await client.sync_registered_courses()

    @server.tool()
    async def list_terms() -> list[str]:
        """List Blackboard terms available to the signed-in account."""
        return await client.list_terms()

    @server.tool()
    async def list_course_content(course_id: str) -> list[dict[str, str]]:
        """List a course's Blackboard content records, read-only."""
        return await client.list_course_content(course_id)

    @server.tool()
    async def list_course_tree(course_id: str) -> list[dict]:
        """Expand folders only and return the hierarchical course inventory."""
        return await client.list_course_tree(course_id)

    @server.tool()
    async def sync_course(course_id: str) -> dict:
        """Snapshot a course tree locally and return additions, changes and removals."""
        return await client.sync_course(course_id)

    @server.tool()
    async def download_content(course_id: str, content_id: str) -> dict:
        """Download one explicit course material to private local storage; no signed URL is returned."""
        return await client.download_content(course_id, content_id)

    @server.tool()
    async def archive_declared_pdfs(course_id: str) -> dict:
        """Archive every inventory item explicitly declared as a PDF, idempotently."""
        return await client.archive_declared_pdfs(course_id)

    @server.tool()
    async def read_download_chunk(course_id: str, content_id: str, offset: int, length: int) -> dict:
        """Read a verified download in bounded blocks for a local adapter; never call from chat."""
        return client.read_download_chunk(course_id, content_id, offset, length)

    @server.tool()
    async def list_downloads(course_id: str) -> list[dict]:
        """List verified local download receipts without exposing filenames or paths."""
        return client.list_downloads(course_id)

    @server.tool()
    async def list_assessments(course_id: str) -> list[dict]:
        """List visible assessment deadlines; submission state is deliberately not inferred."""
        return await client.list_assessments(course_id)

    @server.tool()
    async def get_assessment(course_id: str, content_id: str) -> dict:
        """Read one activity's instructions, deadline, attempt limits and
        embedded attachments list; read-only, never starts an attempt."""
        return await client.get_assessment(course_id, content_id)

    @server.tool()
    async def list_course_activities(course_id: str) -> list[dict]:
        """Every activity of a course (dated or not, open or past due) with
        the same read-only detail as get_assessment; never starts an attempt."""
        return await client.list_course_activities(course_id)

    @server.tool()
    async def read_open_attempt(course_id: str, content_id: str) -> dict:
        """Questions and options of the attempt ALREADY in progress for an
        assessment. Read-only: never starts an attempt (open=false if none)."""
        return await client.read_open_attempt(course_id, content_id)

    @server.tool()
    async def list_answered_assessments(course_id: str) -> list[dict]:
        """Every already-answered assessment attempt of a course: questions,
        options, the given answer and the answer key when the instructor
        released it. Read-only; in-progress attempts are excluded."""
        return await client.list_answered_assessments(course_id)

    @server.tool()
    async def read_assessment_attachment(course_id: str, content_id: str, index: int) -> dict:
        """Base64 of one image embedded in an activity's instructions (same
        Blackboard host only, magic-byte proven image, 5 MiB cap)."""
        return await client.read_assessment_attachment(course_id, content_id, index)

    @server.tool()
    async def list_announcements(course_id: str) -> list[dict]:
        """List course announcements with full title/body text and publish date."""
        return await client.list_announcements(course_id)

    @server.tool()
    async def list_video_descriptions(course_id: str) -> list[dict]:
        """List accessibility descriptions ("#paratodosverem") already written
        next to embedded video/interactive content; never opens a video or
        scrapes a third-party embed."""
        return await client.list_video_descriptions(course_id)

    @server.tool()
    async def list_course_documents(course_id: str) -> list[dict]:
        """List the plain text of every `x-bb-document` page body — the
        professor's own lecture notes / unit intro / instructions written
        into the page (no attachment). Short/empty pages are skipped."""
        return await client.list_course_documents(course_id)

    @server.tool()
    async def list_video_transcripts(course_id: str) -> list[dict]:
        """List Kaltura caption transcripts for every lecture video embedded
        in the course's document pages; only fetches the caption track
        Kaltura already generates, never the video/audio itself."""
        return await client.list_video_transcripts(course_id)

    @server.tool()
    async def sync_available_courses(term: str = "") -> list[dict]:
        """Snapshot every available course locally; no material is opened or downloaded."""
        return await client.sync_available_courses(term or None)

    return server
