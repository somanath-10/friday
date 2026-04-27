from pathlib import Path

from friday.healthcheck import FAIL, _server_startup_check


class _PipeThatMustNotBeRead:
    def read(self):
        raise AssertionError("healthcheck should use communicate(), not blocking pipe reads")


class _FakeServerProcess:
    stdout = _PipeThatMustNotBeRead()
    stderr = _PipeThatMustNotBeRead()

    def __init__(self):
        self.terminated = False
        self.killed = False
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self.terminated = True
        self._returncode = -15

    def kill(self):
        self.killed = True
        self._returncode = -9

    def communicate(self, timeout=None):
        return b"startup stdout", b"startup stderr"


def test_server_startup_check_collects_output_without_blocking_read(mocker):
    process = _FakeServerProcess()
    mocker.patch("friday.healthcheck._free_port", return_value=8765)
    mocker.patch("friday.healthcheck.subprocess.Popen", return_value=process)
    mocker.patch("friday.healthcheck._wait_for_url", side_effect=RuntimeError("server never responded"))

    result = _server_startup_check(Path.cwd())

    assert result.status == FAIL
    assert process.terminated is True
    assert "server never responded" in result.detail
    assert "startup stderr" in result.detail
    assert "startup stdout" in result.detail
