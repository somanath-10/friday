import importlib.util
import threading
from pathlib import Path


_SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
_SERVER_SPEC = importlib.util.spec_from_file_location("friday_local_server", _SERVER_PATH)
assert _SERVER_SPEC is not None and _SERVER_SPEC.loader is not None
server = importlib.util.module_from_spec(_SERVER_SPEC)
_SERVER_SPEC.loader.exec_module(server)


def test_main_runs_sse_server(mocker):
    run = mocker.patch.object(server.mcp, "run")

    server.main()

    run.assert_called_once_with(transport="sse", mount_path=server.SERVER_MOUNT_PATH)


def test_main_suppresses_keyboard_interrupt(mocker):
    run = mocker.patch.object(server.mcp, "run", side_effect=KeyboardInterrupt())
    raised: list[BaseException] = []

    def invoke() -> None:
        try:
            server.main()
        except BaseException as exc:  # pragma: no cover - defensive capture
            raised.append(exc)

    thread = threading.Thread(target=invoke)
    thread.start()
    thread.join(timeout=5)

    assert thread.is_alive() is False
    assert raised == []
    run.assert_called_once_with(transport="sse", mount_path=server.SERVER_MOUNT_PATH)
