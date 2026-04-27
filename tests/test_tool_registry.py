from pathlib import Path
from types import SimpleNamespace

from friday.tools import get_tool_module_status, register_all_tools


class MockMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def test_register_all_tools_loads_modules_in_sorted_order(mocker):
    fake_paths = [
        Path("/tmp/zeta.py"),
        Path("/tmp/__init__.py"),
        Path("/tmp/alpha.py"),
        Path("/tmp/.hidden.py"),
    ]
    registered_modules = []

    def fake_import(name: str):
        module_name = name.rsplit(".", 1)[-1]

        def register(_mcp):
            registered_modules.append(module_name)

        return SimpleNamespace(register=register)

    mocker.patch("friday.tools.Path.glob", return_value=fake_paths)
    mocker.patch("friday.tools.importlib.import_module", side_effect=fake_import)

    register_all_tools(MockMCP())

    assert registered_modules == ["alpha", "zeta"]


def test_register_all_tools_records_disabled_modules(mocker):
    fake_paths = [Path("/tmp/broken.py")]

    mocker.patch("friday.tools.Path.glob", return_value=fake_paths)
    mocker.patch("friday.tools.importlib.import_module", side_effect=ImportError("missing dep"))

    status = register_all_tools(MockMCP())

    assert status == get_tool_module_status()
    assert status == [
        {
            "module": "friday.tools.broken",
            "enabled": False,
            "error": "missing dep",
        }
    ]
