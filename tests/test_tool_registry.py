from pathlib import Path
from types import SimpleNamespace

from friday.tools import (
    build_tool_capability_manifest,
    get_tool_module_status,
    register_all_tools,
)


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

        return SimpleNamespace(
            register=register,
            TOOL_METADATA={
                "capability": "test",
                "capability_name": "Test Tools",
                "risk": "low",
                "summary": f"{module_name} summary",
                "requires_approval": False,
            },
        )

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
            "capability": "extension",
            "capability_name": "Local Extension",
            "risk": "medium",
            "summary": "Local FRIDAY tool module.",
            "requires_approval": False,
        }
    ]


def test_register_all_tools_records_metadata_for_enabled_modules(mocker):
    fake_paths = [Path("/tmp/custom.py")]

    def register(_mcp):
        return None

    module = SimpleNamespace(
        register=register,
        TOOL_METADATA={
            "capability": "desktop",
            "capability_name": "Desktop Control",
            "risk": "high",
            "summary": "Controls visible apps.",
            "requires_approval": True,
        },
    )
    mocker.patch("friday.tools.Path.glob", return_value=fake_paths)
    mocker.patch("friday.tools.importlib.import_module", return_value=module)

    status = register_all_tools(MockMCP())

    assert status[0]["capability"] == "desktop"
    assert status[0]["risk"] == "high"
    assert status[0]["requires_approval"] is True
    manifest = build_tool_capability_manifest(status)
    assert manifest["module_count"] == 1
    assert manifest["capabilities"][0]["id"] == "desktop"
    assert manifest["capabilities"][0]["enabled_count"] == 1
