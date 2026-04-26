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
    fake_paths = [Path("/tmp/alpha.py"), Path("/tmp/zeta.py")]
    registered_modules = []

    def fake_import(name: str):
        module_name = name.rsplit(".", 1)[-1]

        def register(_mcp):
            registered_modules.append(module_name)

        return SimpleNamespace(register=register)

    mocker.patch.object(tool_registry, "_tool_module_paths", return_value=fake_paths)
    mocker.patch("friday.tools.importlib.import_module", side_effect=fake_import)

    register_all_tools(MockMCP())

    assert registered_modules == ["alpha", "zeta"]


def test_register_all_tools_skips_disabled_modules(mocker):
    fake_paths = [Path("/tmp/calendar_tool.py"), Path("/tmp/files.py")]
    registered_modules = []

    def fake_import(name: str):
        module_name = name.rsplit(".", 1)[-1]

        def register(_mcp):
            registered_modules.append(module_name)

        return SimpleNamespace(register=register)

    mocker.patch.object(tool_registry, "_tool_module_paths", return_value=fake_paths)
    mocker.patch.object(tool_registry.importlib, "import_module", side_effect=fake_import)
    mocker.patch.object(
        tool_registry,
        "tool_module_enabled",
        side_effect=lambda module_name: module_name != "calendar_tool",
    )
    mocker.patch.object(tool_registry, "disabled_tool_modules", return_value={"calendar_tool"})

    register_all_tools(MockMCP())

    assert registered_modules == ["files"]


def test_preview_tool_registration_report_tracks_failures(mocker):
    fake_paths = [
        Path("/tmp/alpha.py"),
        Path("/tmp/broken.py"),
        Path("/tmp/gamma.py"),
        Path("/tmp/no_register.py"),
    ]

    def fake_import(name: str):
        module_name = name.rsplit(".", 1)[-1]
        if module_name == "broken":
            raise RuntimeError("missing dependency")
        if module_name == "no_register":
            return SimpleNamespace()
        return SimpleNamespace(register=lambda _mcp: None)

    mocker.patch.object(tool_registry, "_tool_module_paths", return_value=fake_paths)
    mocker.patch.object(
        tool_registry,
        "tool_module_enabled",
        side_effect=lambda module_name: module_name != "gamma",
    )
    mocker.patch.object(tool_registry, "disabled_tool_modules", return_value={"gamma"})
    mocker.patch.object(tool_registry.importlib, "import_module", side_effect=fake_import)

    report = tool_registry.preview_tool_registration_report()

    assert report["enabled_modules"] == ["alpha", "broken", "no_register"]
    assert report["disabled_modules"] == ["gamma"]
    assert report["registered_modules"] == ["alpha"]
    assert report["failed_modules"]["broken"] == "RuntimeError: missing dependency"
    assert report["failed_modules"]["no_register"] == "Module does not define register(mcp)."
    assert report["ready"] is False
