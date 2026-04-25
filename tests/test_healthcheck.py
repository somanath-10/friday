import subprocess

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


def test_server_startup_check_cleans_up_failed_process(mocker, tmp_path):
    process = DummyProcess()
    mocker.patch.object(healthcheck, "_free_port", return_value=8123)
    mocker.patch.object(healthcheck.subprocess, "Popen", return_value=process)
    mocker.patch.object(healthcheck, "_wait_for_url", side_effect=RuntimeError("boom"))

    result = healthcheck._server_startup_check(tmp_path)

    assert result.name == "server.startup"
    assert result.status == healthcheck.FAIL
    assert "Startup smoke test failed: boom" in result.detail
    assert "stderr: stderr from child" in result.detail
    assert "stdout: stdout from child" in result.detail
    assert process.terminate_called is True
