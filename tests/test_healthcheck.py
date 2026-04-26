import subprocess
from pathlib import Path

import friday.healthcheck as healthcheck


class DummyProcess:
    def __init__(self) -> None:
        self.terminate_called = False
        self.kill_called = False
        self.wait_called = False
        self.communicate_called = False
        self.running = True

    def poll(self):
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminate_called = True

    def wait(self, timeout: float) -> int:
        self.wait_called = True
        raise subprocess.TimeoutExpired("server.py", timeout)

    def kill(self) -> None:
        self.kill_called = True
        self.running = False

    def communicate(self, timeout: float):
        self.communicate_called = True
        return (b"stdout from child", b"stderr from child")


def test_stop_subprocess_kills_after_timeout():
    process = DummyProcess()

    stdout, stderr = healthcheck._stop_subprocess(process)

    assert process.terminate_called is True
    assert process.wait_called is True
    assert process.kill_called is True
    assert process.communicate_called is True
    assert stdout == "stdout from child"
    assert stderr == "stderr from child"


def test_server_startup_check_cleans_up_failed_process(mocker):
    process = DummyProcess()
    mocker.patch.object(healthcheck, "_free_port", return_value=8123)
    mocker.patch.object(healthcheck.subprocess, "Popen", return_value=process)
    mocker.patch.object(healthcheck, "_wait_for_url", side_effect=RuntimeError("boom"))

    result = healthcheck._server_startup_check(Path.cwd())

    assert result.name == "server.startup"
    assert result.status == healthcheck.FAIL
    assert "Startup smoke test failed: boom" in result.detail
    assert "stderr: stderr from child" in result.detail
    assert "stdout: stdout from child" in result.detail
    assert process.terminate_called is True


def test_build_env_readiness_reports_workspace_and_tool_registration(mocker):
    mocker.patch.object(
        healthcheck,
        "build_runtime_status",
        return_value={
            "app_ready": True,
            "llm_provider": "openai",
            "llm_model": "gpt-4o",
            "openai_configured": True,
            "workspace_path": "C:/tmp/workspace",
            "workspace_writable": True,
            "workspace_error": None,
            "setup_issues": [],
            "legacy_livekit_configured": False,
            "voice_providers": {"stt": "deepgram", "llm": "openai", "tts": "openai"},
            "voice_configured": False,
            "voice_missing_keys": ["stt:DEEPGRAM_API_KEY"],
            "browser_automation_ready": False,
            "desktop_control_ready": False,
            "diagnostics": {
                "transport": {
                    "configured_mcp_server_url": "",
                    "effective_local_mcp_server_url": "http://127.0.0.1:8000/sse",
                    "conflicting_override": False,
                },
                "tool_registration": {
                    "ready": True,
                    "registered_modules": ["browser", "files"],
                    "issues": [],
                },
            },
        },
    )
    mocker.patch.object(healthcheck, "_desktop_permission_results", return_value=[])
    mocker.patch.object(healthcheck, "_has_module", return_value=False)

    results = healthcheck._build_env_readiness()
    names = {result.name for result in results}

    assert "config.openai" in names
    assert "config.workspace" in names
    assert "config.tool_registration" in names


def test_desktop_permission_results_windows(mocker):
    mocker.patch.object(healthcheck.platform, "system", return_value="Windows")

    results = healthcheck._desktop_permission_results()

    assert len(results) == 1
    assert results[0].name == "config.desktop_permissions"
    assert results[0].status == healthcheck.PASS
