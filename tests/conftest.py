import pytest
import os
import shutil
import tempfile
import uuid
from pathlib import Path


_default_temp_root = Path.cwd() / "workspace" / ".pytest_runtime" / f"run_{os.getpid()}"
_TEST_TEMP_ROOT = Path(os.environ.get("FRIDAY_TEST_TMPDIR", _default_temp_root)).resolve()
try:
    _TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    _TEST_TEMP_ROOT = (Path.cwd() / "workspace" / ".pytest_runtime_fallback" / f"run_{os.getpid()}").resolve()
    _TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
for _name in ("TMPDIR", "TEMP", "TMP"):
    os.environ[_name] = str(_TEST_TEMP_ROOT)
tempfile.tempdir = str(_TEST_TEMP_ROOT)


@pytest.fixture
def isolated_temp_dir():
    temp_path = (_TEST_TEMP_ROOT / f"tmp_{uuid.uuid4().hex[:12]}").resolve()
    temp_path.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_path
    finally:
        shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_workspace(isolated_temp_dir):
    """Fixture to provide a temporary workspace directory."""
    original_workspace = os.environ.get("FRIDAY_WORKSPACE_DIR")
    os.environ["FRIDAY_WORKSPACE_DIR"] = str(isolated_temp_dir)

    yield isolated_temp_dir

    if original_workspace:
        os.environ["FRIDAY_WORKSPACE_DIR"] = original_workspace
    else:
        del os.environ["FRIDAY_WORKSPACE_DIR"]

@pytest.fixture
def mock_mcp():
    """Mock an MCP server instance used in register(mcp) calls."""
    class MockMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func
            return decorator

    return MockMCP()
