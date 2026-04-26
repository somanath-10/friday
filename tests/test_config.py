import friday.config as friday_config


def _tool_status(**overrides):
    status = {
        "attempted": False,
        "discovered_modules": ["browser", "files"],
        "enabled_modules": ["browser", "files"],
        "disabled_modules": [],
        "registered_modules": ["browser", "files"],
        "failed_modules": {},
        "ready": True,
        "issues": [],
    }
    status.update(overrides)
    return status


def test_build_runtime_status_allows_local_browser_when_openai_is_configured(monkeypatch, mock_workspace):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    monkeypatch.setattr(friday_config, "_module_available", lambda name: name == "pyautogui")
    monkeypatch.setattr(friday_config, "tool_registration_status", lambda: _tool_status())

    status = friday_config.build_runtime_status()

    assert status["app_ready"] is True
    assert status["llm_provider"] == "openai"
    assert status["openai_configured"] is True
    assert status["voice_configured"] is False
    assert any("LLM_PROVIDER=gemini" in warning for warning in status["warnings"])


def test_build_runtime_status_reports_missing_openai_key(monkeypatch, mock_workspace):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(friday_config, "_module_available", lambda _name: True)
    monkeypatch.setattr(friday_config, "tool_registration_status", lambda: _tool_status())

    status = friday_config.build_runtime_status()

    assert status["app_ready"] is False
    assert "OPENAI_API_KEY is required for local browser chat" in status["setup_issues"][0]


def test_build_runtime_status_falls_back_from_invalid_port(monkeypatch, mock_workspace):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MCP_SERVER_PORT", "not-a-port")
    monkeypatch.setattr(friday_config, "_module_available", lambda _name: True)
    monkeypatch.setattr(friday_config, "tool_registration_status", lambda: _tool_status())

    status = friday_config.build_runtime_status()

    assert status["port"] == 8000
    assert any("MCP_SERVER_PORT='not-a-port'" in warning for warning in status["warnings"])


def test_build_runtime_status_warns_about_conflicting_mcp_server_url(monkeypatch, mock_workspace):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MCP_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_SERVER_PORT", "8000")
    monkeypatch.setenv("MCP_SERVER_URL", "http://192.168.1.5:9000/sse")
    monkeypatch.setattr(friday_config, "_module_available", lambda _name: True)
    monkeypatch.setattr(friday_config, "tool_registration_status", lambda: _tool_status())

    status = friday_config.build_runtime_status()

    assert status["diagnostics"]["transport"]["conflicting_override"] is True
    assert any("MCP_SERVER_URL does not match the local host/port settings" in warning for warning in status["warnings"])


def test_build_runtime_status_reports_missing_tool_registration(monkeypatch, mock_workspace):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(friday_config, "_module_available", lambda _name: True)
    monkeypatch.setattr(
        friday_config,
        "tool_registration_status",
        lambda: _tool_status(
            registered_modules=[],
            ready=False,
            issues=["browser: RuntimeError: import failed"],
        ),
    )

    status = friday_config.build_runtime_status()

    assert status["app_ready"] is False
    assert any("No enabled tool modules were successfully registered" in issue for issue in status["setup_issues"])
    assert status["tool_registration_ready"] is False
