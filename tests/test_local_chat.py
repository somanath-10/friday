import asyncio

import friday.local_chat as local_chat
from friday.local_chat import LocalChatResult, _direct_browser_open_shortcut, local_mode_issues


def test_direct_browser_open_shortcut_builds_youtube_search():
    shortcut = _direct_browser_open_shortcut("open Samay Raina is alive video")

    assert shortcut is not None
    assert shortcut.url == "https://www.youtube.com/results?search_query=samay+raina+is+alive"
    assert shortcut.reply == "Opened YouTube results for 'samay raina is alive' in your browser."


def test_direct_browser_open_shortcut_skips_local_video_folder_requests():
    shortcut = _direct_browser_open_shortcut("open Desktop video folder")

    assert shortcut is None


def test_local_mode_issues_only_require_openai_for_browser_mode(monkeypatch, mock_workspace):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(local_chat, "local_browser_setup_issues", lambda: [])

    assert local_mode_issues() == []


def test_run_local_chat_can_approve_latest_pending_action(monkeypatch):
    pending = [
        {
            "approval_id": "apr_demo",
            "request": {
                "action_summary": "delete_path: workspace/report.md",
                "tool": "delete_path",
            },
        }
    ]

    async def _noop(*args, **kwargs):
        return None

    async def _resume(approval_id: str, mcp_url: str) -> LocalChatResult:
        assert approval_id == "apr_demo"
        assert mcp_url == "http://local.test/sse"
        return LocalChatResult(reply="Deleted workspace/report.md", tool_events=[{"name": "delete_path"}])

    monkeypatch.setattr(local_chat, "list_pending_approvals", lambda: pending)
    monkeypatch.setattr(
        local_chat,
        "resolve_pending_approval",
        lambda approval_id, decision, approval_mode="one_time": {
            "approval_id": approval_id,
            "request": pending[0]["request"],
            "status": decision,
            "approval_mode": approval_mode,
        },
    )
    monkeypatch.setattr(local_chat, "resume_approved_local_action", _resume)
    monkeypatch.setattr(local_chat, "record_conversation_turn", _noop)
    monkeypatch.setattr(local_chat, "store_action_trace", _noop)

    result = asyncio.run(
        local_chat.run_local_chat(
            [{"role": "user", "content": "approve"}],
            "http://local.test/sse",
        )
    )

    assert result.reply == "Deleted workspace/report.md"
    assert result.tool_events[0]["name"] == "delete_path"


def test_run_local_chat_can_deny_pending_action(monkeypatch):
    pending = [
        {
            "approval_id": "apr_demo",
            "request": {
                "action_summary": "git_push: origin main",
                "tool": "git_push",
            },
        }
    ]

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(local_chat, "list_pending_approvals", lambda: pending)
    monkeypatch.setattr(
        local_chat,
        "resolve_pending_approval",
        lambda approval_id, decision, approval_mode="one_time": {
            "approval_id": approval_id,
            "request": pending[0]["request"],
            "status": decision,
            "approval_mode": approval_mode,
        },
    )
    monkeypatch.setattr(local_chat, "record_conversation_turn", _noop)
    monkeypatch.setattr(local_chat, "store_action_trace", _noop)

    result = asyncio.run(
        local_chat.run_local_chat(
            [{"role": "user", "content": "deny"}],
            "http://local.test/sse",
        )
    )

    assert "did not run" in result.reply.lower()
    assert "git_push" in result.reply
