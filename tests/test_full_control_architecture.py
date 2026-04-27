import json
import sys

from friday.browser.dom_snapshot import format_indexed_elements, parse_html_snapshot
from friday.browser.downloads import check_download_permission, download_target_path
from friday.browser.forms import check_form_submit_permission
from friday.browser.profile_manager import load_profile_policy
from friday.browser.runtime import BrowserRuntime
from friday.code.git_ops import require_git_push_permission
from friday.code.repo_inspector import detect_project_type, detect_test_command
from friday.config import build_config_diagnostics
from friday.core.permissions import access_mode_summary, check_shell_permission
from friday.files.backup import create_backup
from friday.files.runtime import FileRuntime
from friday.files.safe_paths import preview_bulk_operation, resolve_safe_path
from friday.memory.action_trace import save_action_trace
from friday.memory.store import MemoryStore
from friday.observability.timeline import append_timeline_event, read_timeline_events
from friday.research.citations import Citation
from friday.research.report_writer import write_research_report
from friday.safety.audit_log import append_audit_record, read_audit_records
from friday.safety.emergency_stop import clear_emergency_stop, trigger_emergency_stop
from friday.safety.policy import evaluate_safety_policy
from friday.safety.secrets_filter import contains_secret, redact_text
from friday.shell.command_policy import validate_command
from friday.shell.runtime import ShellRuntime
from friday.voice.input import VoiceCommand, route_voice_command, transcript_path
from friday.voice.realtime import load_realtime_voice_config
from friday.voice.transcription import load_transcription_config
from friday.voice.tts import load_tts_config
from friday.voice.vad import has_speech
from friday.workflows.engine import WorkflowEngine
from friday.workflows.store import WorkflowStore


def test_secret_redaction_and_audit_log(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    secret = "sk-proj-" + "a" * 30

    assert contains_secret(secret)
    assert secret not in redact_text(f"token={secret}")

    append_audit_record(command=f"send {secret}", risk_level=3, decision="ask", tool="test", result=secret)
    record = read_audit_records(limit=1)[0]

    assert secret not in json.dumps(record)
    assert "[REDACTED_SECRET]" in json.dumps(record)


def test_emergency_stop_blocks_permission(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    trigger_emergency_stop("test")
    try:
        decision = check_shell_permission("pwd")
        assert decision.decision == "block"
        assert "Emergency stop" in decision.reason
    finally:
        clear_emergency_stop()


def test_access_mode_and_full_control_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FRIDAY_ACCESS_MODE", "full_control")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    summary = access_mode_summary()
    diagnostics = build_config_diagnostics()

    assert summary["mode"] == "full_control"
    assert diagnostics.access_mode == "full_control"
    assert any("full_control" in warning for warning in diagnostics.warnings)


def test_browser_policy_snapshot_and_sensitive_actions(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    policy = load_profile_policy(base=tmp_path)
    html = "<title>Demo</title><a href='/next'>Next</a><input name='password' type='password'>"

    snapshot = parse_html_snapshot(html, base_url="https://example.test")
    text = format_indexed_elements(snapshot)
    runtime = BrowserRuntime(policy)
    observed = runtime.observe_html(html, url="https://example.test/login")
    submit = check_form_submit_permission("Login", "https://example.test/login", ["password"])
    download = check_download_permission(download_target_path("installer.exe", downloads_dir=tmp_path))

    assert policy.use_isolated_profile is True
    assert "Next" in text
    assert observed.ok is True
    assert submit.decision == "ask"
    assert download.decision == "ask"


def test_file_runtime_safety_backup_and_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    runtime = FileRuntime()
    target = tmp_path / "note.txt"
    target.write_text("old", encoding="utf-8")

    traversal = resolve_safe_path("../outside.txt")
    backup = create_backup(target)
    delete_result = runtime.delete_path("note.txt")
    preview = preview_bulk_operation(["note.txt", "../outside.txt"], operation="delete")

    assert traversal.decision.decision == "block"
    assert backup.exists()
    assert delete_result.permission_decision == "ask"
    assert target.exists()
    assert preview["blocked"]


def test_shell_policy_runtime_and_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    readonly = validate_command("python --version", cwd=tmp_path)
    install = validate_command("pip install rich", cwd=tmp_path)
    dangerous = validate_command("rm -rf /", cwd=tmp_path)
    slow = ShellRuntime(timeout_seconds=1).execute_command(
        f"{sys.executable} -c \"import time; time.sleep(2)\"",
        cwd=tmp_path,
    )

    assert readonly.decision == "allow"
    assert install.decision == "ask"
    assert dangerous.decision == "block"
    assert slow.ok is False
    assert slow.returncode == -1


def test_code_project_detection_and_git_push_approval():
    assert detect_project_type(".") == "python"
    assert "pytest" in detect_test_command(".")
    push = require_git_push_permission(".")
    assert push.permission_decision == "ask"


def test_research_report_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    path = write_research_report("Demo Topic", "Summary with a citation.", [Citation("Example", "https://example.test")])

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "source_urls" in content
    assert "https://example.test" in content


def test_workflow_store_and_replay_permission(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    store = WorkflowStore(tmp_path / "workflows")
    engine = WorkflowEngine(store)
    record = engine.create_workflow(
        "delete a file",
        intent="files",
        risk_level=3,
        steps=[{"id": "delete", "risk_level": 3, "executor": "files", "action_type": "delete_path", "description": "delete file"}],
    )

    replay = engine.replay_workflow(record.workflow_id)

    assert store.load(record.workflow_id).goal == "delete a file"
    assert replay.ok is False
    assert "approval" in replay.message.lower()


def test_memory_redacts_and_disabled_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_MEMORY_DIR", str(tmp_path / "memory"))
    secret = "ghp_" + "a" * 30
    store = MemoryStore()
    save_action_trace("cmd", {"token": secret}, {"ok": True}, store=store)

    exported = json.dumps(store.export())
    disabled = MemoryStore(root=tmp_path / "disabled", enabled=False)

    assert secret not in exported
    assert disabled.save_preference("x", "y").ok is False


def test_voice_config_and_pipeline_permission(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("STT_PROVIDER", "openai")
    monkeypatch.setenv("TTS_PROVIDER", "openai")

    assert load_transcription_config().configured is False
    assert load_tts_config().configured is False
    assert load_realtime_voice_config().configured is True
    assert has_speech([0.1, 0.1, 0.1])
    assert str(transcript_path("session")).endswith("session.txt")

    result = route_voice_command(VoiceCommand("delete all files in Downloads"), dry_run=True)
    assert result["status"] == "paused"


def test_timeline_and_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    append_timeline_event("tool_started", "Testing timeline", command="pwd")
    decision = evaluate_safety_policy("send payload", {"outgoing_payload": "sk-proj-" + "b" * 30})

    assert read_timeline_events(limit=1)[0]["event_type"] == "tool_started"
    assert decision.decision == "block"
