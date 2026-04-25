from pathlib import Path
from types import SimpleNamespace

import friday.tools as tool_registry
from friday.tools import register_all_tools


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


def test_register_all_tools_skips_disabled_modules(mocker):
    fake_paths = [
        Path("/tmp/calendar_tool.py"),
        Path("/tmp/files.py"),
    ]
    registered_modules = []

    def fake_import(name: str):
        module_name = name.rsplit(".", 1)[-1]

        def register(_mcp):
            registered_modules.append(module_name)

        return SimpleNamespace(register=register)

    mocker.patch.object(tool_registry.Path, "glob", return_value=fake_paths)
    mocker.patch.object(tool_registry.importlib, "import_module", side_effect=fake_import)
    mocker.patch.object(
        tool_registry,
        "tool_module_enabled",
        side_effect=lambda module_name: module_name != "calendar_tool",
    )
    mocker.patch.object(tool_registry, "disabled_tool_modules", return_value={"calendar_tool"})

    register_all_tools(MockMCP())

    assert registered_modules == ["files"]
