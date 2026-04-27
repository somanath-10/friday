import friday.voice.input as voice_input
from friday.memory.store import MemoryStore
from friday.voice.input import VoiceCommand


def test_voice_transcript_memory_extracts_summary_and_action_items(tmp_path):
    store = MemoryStore(root=tmp_path / "memory")
    command = VoiceCommand(
        "We discussed the release timeline. I will send the updated notes tomorrow. We need to follow up with Sarah next week.",
        source="browser_upload",
    )

    saved = voice_input.save_voice_transcript(command, store=store)
    results = voice_input.search_voice_memory("Sarah", store=store)

    assert saved["saved"] is True
    assert "release timeline" in saved["summary"].lower()
    assert any("follow up with sarah" in item.lower() for item in saved["action_items"])
    assert results


def test_route_voice_command_saves_transcript_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        voice_input,
        "run_command_pipeline",
        lambda transcript, dry_run=True: type("Pipeline", (), {"to_dict": lambda self: {"status": "paused", "command": transcript}})(),
    )

    result = voice_input.route_voice_command(VoiceCommand("Remind me to send the invoice"), dry_run=True)

    assert result["status"] == "paused"
    assert result["transcript_memory"]["saved"] is True
    assert any("send the invoice" in item.lower() for item in result["transcript_memory"]["action_items"])
