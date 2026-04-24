import pytest
from friday.tools.context_manager import ContextManager


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """Isolated ContextManager using a temp memory directory."""
    monkeypatch.setenv("FRIDAY_MEMORY_DIR", str(tmp_path))
    # Re-instantiate so it uses the monkeypatched env
    from friday import path_utils
    monkeypatch.setattr(path_utils, "memory_dir", lambda: tmp_path)
    manager = ContextManager()
    return manager


def _make_turn(user="hello", reply="hi"):
    return {
        "user_message": user,
        "assistant_reply": reply,
        "tool_events": [],
        "timestamp": "2026-04-24T10:00:00",
    }


def test_initial_stats_empty(ctx):
    stats = ctx.get_context_stats()
    assert stats["turn_count"] == 0
    assert stats["has_summary"] is False
    assert stats["needs_trim"] is False


def test_trim_empty_history(ctx):
    removed, remaining = ctx.trim_to_recent(keep_last=5)
    assert removed == 0
    assert remaining == 0


def test_trim_keeps_last_n(ctx):
    turns = [_make_turn(user=f"msg {i}") for i in range(25)]
    ctx._write_history(turns)

    removed, remaining = ctx.trim_to_recent(keep_last=10)
    assert removed == 15
    assert remaining == 10

    # Verify the correct turns were kept (the last 10)
    surviving = ctx._read_history()
    assert surviving[0]["user_message"] == "msg 15"
    assert surviving[-1]["user_message"] == "msg 24"


def test_stats_needs_trim(ctx):
    turns = [_make_turn() for _ in range(25)]
    ctx._write_history(turns)

    stats = ctx.get_context_stats()
    assert stats["turn_count"] == 25
    assert stats["needs_trim"] is True


def test_save_and_read_summary(ctx):
    ctx._write_summary("Completed phase 4 work.")
    assert ctx._read_summary() == "Completed phase 4 work."


def test_build_inline_summary_includes_turns(ctx):
    turns = [_make_turn(user="What is 2+2?", reply="It is 4.")]
    ctx._write_history(turns)

    summary = ctx.build_inline_summary()
    assert "What is 2+2?" in summary
    assert "It is 4." in summary


def test_build_inline_summary_includes_prior_note(ctx):
    ctx._write_summary("Prior session note: deployed Friday.")
    turns = [_make_turn()]
    ctx._write_history(turns)

    summary = ctx.build_inline_summary()
    assert "Prior session note: deployed Friday." in summary


def test_build_inline_summary_includes_prior_note_without_turns(ctx):
    ctx._write_summary("Prior session note: verified workflows.")

    summary = ctx.build_inline_summary()
    assert "Prior session note: verified workflows." in summary
    assert "No conversation history" not in summary


def test_clear_all_removes_history_and_summary(ctx):
    turns = [_make_turn() for _ in range(5)]
    ctx._write_history(turns)
    ctx._write_summary("Some note")

    count = ctx.clear_all()
    assert count == 5
    assert ctx._read_history() == []
    assert ctx._read_summary() == ""


def test_clear_all_on_empty_is_safe(ctx):
    count = ctx.clear_all()
    assert count == 0
