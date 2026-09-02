import pytest

from blackboard_mcp.client import BlackboardClient
from blackboard_mcp.config import Settings


@pytest.mark.asyncio
async def test_sync_available_courses_skips_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BlackboardClient(Settings.from_profile("sober"))

    async def courses(_term: str | None = None) -> list[dict[str, str]]:
        return [
            {"id": "_open_1", "availability": "Aberto"},
            {"id": "_closed_1", "availability": "Indisponível"},
        ]

    seen: list[str] = []
    async def sync(course_id: str) -> dict[str, str]:
        seen.append(course_id)
        return {"course_id": course_id}

    monkeypatch.setattr(client, "list_courses", courses)
    monkeypatch.setattr(client, "sync_course", sync)
    out = await client.sync_available_courses()
    assert seen == ["_open_1"]
    assert out[0]["sync"] == {"course_id": "_open_1"}
