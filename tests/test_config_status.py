from friday.config import build_config_diagnostics
from friday.web_ui import _local_status


def _clear_provider_env(monkeypatch):
    for key in (
        "DEEPGRAM_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "LIVEKIT_URL",
        "OPENAI_API_KEY",
        "SARVAM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_config_validation_reports_missing_openai(monkeypatch, tmp_path):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    diagnostics = build_config_diagnostics()

    assert diagnostics.app_ready is False
    assert diagnostics.openai_configured is False
    assert any("OPENAI_API_KEY is missing" in issue for issue in diagnostics.setup_issues)
    assert diagnostics.browser_automation_ready in {True, False}


def test_optional_voice_keys_do_not_block_local_text(monkeypatch, tmp_path):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("TTS_PROVIDER", "sarvam")

    diagnostics = build_config_diagnostics()

    assert diagnostics.chat_ready is True
    assert diagnostics.app_ready is True
    assert diagnostics.setup_issues == []
    assert any("LiveKit voice" in warning for warning in diagnostics.warnings)


def test_status_payload_contains_phase1_fields(monkeypatch, tmp_path, mocker):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mocker.patch(
        "friday.web_ui.codex_relay_status",
        return_value={"ready": False, "issues": ["not configured"], "project_path": str(tmp_path)},
    )
    mocker.patch(
        "friday.web_ui.get_tool_module_status",
        return_value=[
            {"module": "friday.tools.files", "enabled": True, "error": ""},
            {"module": "friday.tools.optional", "enabled": False, "error": "missing dep"},
        ],
    )

    payload = _local_status()

    expected_keys = {
        "app_ready",
        "server_name",
        "mode",
        "host",
        "port",
        "workspace_path",
        "python_version",
        "os",
        "is_windows",
        "windows_version",
        "llm_provider",
        "llm_model",
        "openai_configured",
        "voice_configured",
        "browser_automation_ready",
        "desktop_control_ready",
        "pywinauto_available",
        "pyautogui_available",
        "playwright_available",
        "chrome_available",
        "edge_available",
        "powershell_available",
        "enabled_tool_modules",
        "disabled_tool_modules",
        "setup_issues",
        "warnings",
        "next_steps",
    }
    assert expected_keys.issubset(payload)
    assert payload["ready"] is True
    assert payload["issues"] == []
    assert payload["enabled_tool_modules"] == ["friday.tools.files"]
    assert payload["disabled_tool_modules"] == [
        {"module": "friday.tools.optional", "error": "missing dep"}
    ]
    if not payload["is_windows"]:
        assert payload["desktop_control_ready"] is False
        assert any("Windows only" in step for step in payload["next_steps"])
