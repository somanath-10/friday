import pytest
import os

@pytest.fixture
def mock_workspace(tmp_path):
    """Fixture to provide a temporary workspace directory."""
    original_workspace = os.environ.get("FRIDAY_WORKSPACE_DIR")
    os.environ["FRIDAY_WORKSPACE_DIR"] = str(tmp_path)
    
    yield tmp_path
    
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
