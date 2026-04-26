import friday.local_chat as local_chat
from friday.local_chat import _direct_browser_open_shortcut, local_mode_issues


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
