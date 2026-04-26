import asyncio
import json

import pytest

from friday.core.permissions import PermissionEngine, load_permission_config
from friday.core.risk import classify_shell_command
from friday.safety.approval_gate import get_approval_gate
from friday.safety.audit_log import append_audit_record, audit_log_path
from friday.tools import browser as browser_tools
from friday.tools import files as file_tools
from friday.tools import git_tool
from friday.tools import utils as utils_tools


@pytest.fixture(autouse=True)
def reset_permission_state(monkeypatch):
    monkeypatch.delenv("FRIDAY_PERMISSIONS_PATH", raising=False)
    gate = get_approval_gate()
    gate._pending.clear()
    gate._approved_once.clear()
    gate._session_approvals.clear()
    yield
    gate._pending.clear()
    gate._approved_once.clear()
    gate._session_approvals.clear()


def test_load_permission_config_merges_yaml_and_workspace(monkeypatch, mock_workspace):
    permissions_path = mock_workspace / "permissions.yaml"
    protected_path = mock_workspace / "protected.txt"
    permissions_path.write_text(
        "\n".join(
            [
                "mode: trusted",
                "filesystem:",
                "  allowed_roots:",
                f"    - '{mock_workspace / 'allowed'}'",
                "  protected_paths:",
                f"    - '{protected_path}'",
                "shell:",
                "  timeout_seconds: 45",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRIDAY_PERMISSIONS_PATH", str(permissions_path))

    config = load_permission_config()

    assert config["mode"] == "trusted"
    assert str(mock_workspace.resolve()) in config["filesystem"]["allowed_roots"]
    assert str(protected_path.resolve()) in config["filesystem"]["protected_paths"]
    assert config["shell"]["timeout_seconds"] == 45


def test_classify_shell_command_blocks_dangerous_pattern():
    assessment = classify_shell_command("rm -rf /")

    assert assessment.blocked is True
    assert assessment.risk_level == 4
    assert assessment.category == "shell.dangerous"


def test_install_package_requires_approval():
    decision = PermissionEngine().evaluate_tool_call(
        "install_package",
        {"package_name": "pytest"},
    )

    assert decision.decision == "ask"
    assert decision.category == "shell.install"
    assert decision.risk_level == 2


def test_protected_path_is_blocked(monkeypatch, mock_workspace):
    protected_path = mock_workspace / "secret.txt"
    permissions_path = mock_workspace / "permissions.yaml"
    permissions_path.write_text(
        "\n".join(
            [
                "filesystem:",
                "  allowed_roots:",
                f"    - '{mock_workspace}'",
                "  protected_paths:",
                f"    - '{protected_path}'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRIDAY_PERMISSIONS_PATH", str(permissions_path))

    decision = PermissionEngine().evaluate_tool_call(
        "write_file",
        {"file_path": str(protected_path)},
    )

    assert decision.decision == "block"
    assert "protected by policy" in decision.reason


def test_run_shell_command_blocks_dangerous_command(mock_mcp, mock_workspace):
    utils_tools.register(mock_mcp)

    result = mock_mcp.tools["run_shell_command"]("rm -rf /")

    assert "[Permission Blocked]" in result
    assert "Risk: 4" in result
    assert not (mock_workspace / "logs" / "audit.jsonl").read_text(encoding="utf-8").strip() == ""


def test_write_file_requires_approval_on_overwrite(mock_mcp, mock_workspace):
    target = mock_workspace / "demo.txt"
    target.write_text("original", encoding="utf-8")
    utils_tools.register(mock_mcp)

    result = mock_mcp.tools["write_file"]("demo.txt", "updated")

    assert "[Approval Required]" in result
    assert target.read_text(encoding="utf-8") == "original"


def test_delete_path_requires_approval(mock_mcp, mock_workspace):
    target = mock_workspace / "delete-me.txt"
    target.write_text("remove", encoding="utf-8")
    file_tools.register(mock_mcp)

    result = mock_mcp.tools["delete_path"]("delete-me.txt")

    assert "[Approval Required]" in result
    assert target.exists()


def test_git_push_requires_approval_without_running_git(mock_mcp, mocker):
    git_tools = mock_mcp
    git_tool.register(git_tools)
    run_git = mocker.patch.object(git_tool, "_run_git")

    result = git_tools.tools["git_push"](repo_path="", remote="origin", branch="main")

    assert "[Approval Required]" in result
    run_git.assert_not_called()


def test_session_approval_allows_git_push():
    gate = get_approval_gate()
    gate.grant_session_approval("shell.git_push")

    decision = PermissionEngine().evaluate_tool_call(
        "git_push",
        {"remote": "origin", "branch": "main"},
    )

    assert decision.decision == "allow"
    assert "Session approval" in decision.reason


def test_browser_type_index_press_enter_requires_approval(mock_mcp, monkeypatch):
    browser_tools.register(mock_mcp)

    class FakePage:
        url = "https://example.com/login"

    async def fake_get_page():
        return FakePage()

    async def fake_peek_typable_index(page, index):
        return {"ok": True, "label": "Password", "tag": "input"}

    monkeypatch.setattr(browser_tools, "_browser_backend", "playwright")
    monkeypatch.setattr(browser_tools, "_get_page", fake_get_page)
    monkeypatch.setattr(browser_tools, "_peek_typable_index", fake_peek_typable_index)
    monkeypatch.setattr(
        browser_tools,
        "_type_interactive_index",
        mock_type := mocker_stub(),
    )

    result = asyncio.run(mock_mcp.tools["browser_type_index"](1, "secret", True))

    assert "[Approval Required]" in result
    assert mock_type.called is False


def test_browser_press_key_enter_requires_approval(mock_mcp, monkeypatch):
    browser_tools.register(mock_mcp)

    class FakeKeyboard:
        def __init__(self) -> None:
            self.called = False

        async def press(self, key: str) -> None:
            self.called = True

    class FakePage:
        def __init__(self) -> None:
            self.url = "https://example.com/signin"
            self.keyboard = FakeKeyboard()

    page = FakePage()

    async def fake_get_page():
        return page

    monkeypatch.setattr(browser_tools, "_browser_backend", "playwright")
    monkeypatch.setattr(browser_tools, "_get_page", fake_get_page)

    result = asyncio.run(mock_mcp.tools["browser_press_key"]("Enter"))

    assert "[Approval Required]" in result
    assert page.keyboard.called is False


def test_audit_log_write_creates_jsonl(mock_workspace):
    output_path = append_audit_record(
        tool="run_shell_command",
        action="shell.command",
        decision="allow",
        risk_level=0,
        result="succeeded",
        command="git status",
        metadata={"exit_code": 0},
    )

    assert output_path == audit_log_path()
    payload = json.loads(output_path.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["tool"] == "run_shell_command"
    assert payload["result"] == "succeeded"
    assert payload["metadata"]["exit_code"] == 0


class mocker_stub:
    def __init__(self) -> None:
        self.called = False

    async def __call__(self, *args, **kwargs):
        self.called = True
        return {"ok": True, "label": "Password", "tag": "input"}
