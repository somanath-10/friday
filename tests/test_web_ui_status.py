from types import SimpleNamespace

import friday.config as friday_config
import friday.web_ui as web_ui


def _tool_status():
    return {
        "attempted": False,
        "discovered_modules": ["browser", "files"],
        "enabled_modules": ["browser", "files"],
        "disabled_modules": [],
        "registered_modules": ["browser", "files"],
        "failed_modules": {},
        "ready": True,
        "issues": [],
    }


def test_local_status_payload_contains_phase_one_fields(monkeypatch, mock_workspace):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MCP_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_SERVER_PORT", "8123")
    monkeypatch.setenv("MCP_SERVER_URL", "")
    monkeypatch.setattr(
        friday_config,
        "_module_available",
        lambda name: name in {"playwright", "pyautogui"},
    )
    monkeypatch.setattr(friday_config, "tool_registration_status", _tool_status)
    monkeypatch.setattr(
        web_ui,
        "codex_relay_status",
        lambda: {
            "ready": False,
            "issues": ["Codex extension missing"],
            "project_path": str(mock_workspace),
        },
    )

    status = web_ui._local_status()

    expected_keys = {
        "app_ready",
        "server_name",
        "mode",
        "host",
        "port",
        "workspace_path",
        "python_version",
        "os",
        "llm_provider",
        "llm_model",
        "openai_configured",
        "voice_configured",
        "browser_automation_ready",
        "desktop_control_ready",
        "enabled_tool_modules",
        "disabled_tool_modules",
        "tool_registration_ready",
        "tool_registration_issues",
        "setup_issues",
        "warnings",
        "next_steps",
        "diagnostics",
        "mcp_server_url",
        "codex_relay",
    }

    assert expected_keys.issubset(status.keys())
    assert status["app_ready"] is True
    assert status["ready"] is True
    assert status["mode"] == "local-browser"
    assert status["host"] == "0.0.0.0"
    assert status["port"] == 8123
    assert status["llm_provider"] == "openai"
    assert status["mcp_server_url"] == "http://127.0.0.1:8123/sse"
    assert status["codex_relay"]["project_path"] == str(mock_workspace)
    assert status["diagnostics"]["transport"]["effective_local_mcp_server_url"] == "http://127.0.0.1:8123/sse"


def test_mcp_server_url_prefers_current_request_for_local_browser(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://stale-host:9999/sse")
    request = SimpleNamespace(url=SimpleNamespace(scheme="http", hostname="0.0.0.0", port=8123))

    assert web_ui._mcp_server_url(request) == "http://127.0.0.1:8123/sse"
