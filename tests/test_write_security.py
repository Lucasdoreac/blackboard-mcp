"""Security boundaries, exercised through the MCP tool dispatcher."""
from unittest.mock import AsyncMock, Mock

import pytest

from blackboard_mcp.server import create_server


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", [
    ("submit_assignment", {"course_id": "_1_1", "content_id": "_2_1", "file_path": "file"}),
    ("send_course_message", {"course_id": "_1_1", "text": "hello", "recipient_ids": ["_2_1"]}),
])
async def test_bridge_default_blocks_writes_but_allows_preview(tool, args):
    client = Mock()
    method = AsyncMock(return_value={"preview": True})
    setattr(client, tool, method)
    server = create_server("test", client, allow_writes=False)
    await server.call_tool(tool, args)
    method.assert_awaited_once()
    method.reset_mock()
    with pytest.raises(Exception, match="escritas desabilitadas"):
        await server.call_tool(tool, {**args, "confirm": True})
    method.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", [
    ("submit_assignment", {"course_id": "_1_1", "content_id": "_2_1", "file_path": "file"}),
    ("send_course_message", {"course_id": "_1_1", "text": "hello", "recipient_ids": ["_2_1"]}),
])
async def test_explicit_opt_in_allows_boolean_true_but_not_coercions(tool, args):
    client = Mock()
    method = AsyncMock(return_value={"ok": True})
    setattr(client, tool, method)
    server = create_server("test", client, allow_writes=True)
    for bad in ("true", 1, "false"):
        with pytest.raises(Exception):
            await server.call_tool(tool, {**args, "confirm": bad})
    method.assert_not_awaited()
    await server.call_tool(tool, {**args, "confirm": True})
    method.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../evil", "_1_1/../../conversations", "_1_1?x=y", "_1_1%2fother", "https://evil.test"])
async def test_writer_rejects_route_injection_before_request(bad):
    from blackboard_mcp.submitting import MessageWriter, SubmissionError, SubmissionWriter
    writer = MessageWriter(object())
    writer._write = AsyncMock()
    with pytest.raises(SubmissionError):
        await writer.reply("_1_1", bad, "hello")
    writer._write.assert_not_awaited()
    submission = SubmissionWriter(object())
    submission._write = AsyncMock()
    with pytest.raises(SubmissionError):
        await submission.start_attempt("_1_1", bad, [])
    submission._write.assert_not_awaited()
