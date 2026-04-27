import json

from friday.core.permissions import load_permissions_config, check_shell_permission, check_tool_permission
from friday.core.risk import RiskLevel, classify_file_operation, classify_shell_command
from friday.safety.approval_gate import create_approval_request
from friday.safety.audit_log import append_audit_record, read_audit_records
from friday.tools import files as file_tools
from friday.tools import git_tool, shell as shell_tools


def test_risk_classifies_readonly_and_dangerous_shell():
    assert classify_shell_command("git status").level == RiskLevel.READ_ONLY
    assert classify_shell_command("rm -rf /").level == RiskLevel.DANGEROUS_RESTRICTED
    assert classify_shell_command("pip install requests").level == RiskLevel.SENSITIVE_ACTION
    assert classify_shell_command("python fix_script.py").level == RiskLevel.REVERSIBLE_CHANGE


def test_file_risk_classification():
    assert classify_file_operation("read").level == RiskLevel.READ_ONLY
    assert classify_file_operation("create").level == RiskLevel.SAFE_WRITE
    assert classify_file_operation("delete").level == RiskLevel.SENSITIVE_ACTION


def test_append_and_create_folder_are_safe_file_writes():
    append_decision = check_tool_permission("append_to_file", {"file_path": "workspace/demo.txt"})
    folder_decision = check_tool_permission("create_folder", {"path": "workspace/reports"})

    assert append_decision.decision == "allow"
    assert append_decision.risk_level == RiskLevel.SAFE_WRITE
    assert folder_decision.decision == "allow"
    assert folder_decision.risk_level == RiskLevel.SAFE_WRITE


def test_permissions_config_loading(tmp_path):
    config_path = tmp_path / "permissions.yaml"
    config_path.write_text(
        """
mode: local_permission_based
shell:
  enabled: false
filesystem:
  allowed_roots:
    - "./workspace"
""",
        encoding="utf-8",
    )

    config = load_permissions_config(config_path)

    assert config["mode"] == "local_permission_based"
    assert config["shell"]["enabled"] is False
    assert config["filesystem"]["allowed_roots"] == ["./workspace"]


def test_dangerous_command_blocked():
    decision = check_shell_permission("rm -rf /")

    assert decision.decision == "block"
    assert decision.risk_level == RiskLevel.DANGEROUS_RESTRICTED


def test_sensitive_command_requires_approval():
    decision = check_shell_permission("git push origin main")

    assert decision.decision == "ask"
    assert decision.risk_level == RiskLevel.SENSITIVE_ACTION


def test_approval_gate_payload_contains_exact_command():
    decision = check_shell_permission("pip install rich")
    request = create_approval_request(decision, tool="run_shell_command", command="pip install rich")

    payload = request.to_dict()
    assert payload["command"] == "pip install rich"
    assert payload["risk_level"] == int(RiskLevel.SENSITIVE_ACTION)
    assert payload["approval_id"].startswith("apr_")


def test_audit_log_write_and_read(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))

    append_audit_record(
        command="git push origin main",
        risk_level=3,
        decision="ask",
        tool="git_push",
        result="Approval required",
    )

    records = read_audit_records(limit=1)
    assert records[-1]["command"] == "git push origin main"
    assert records[-1]["permission_decision"] == "ask"


def test_shell_tool_blocks_dangerous_command(mock_mcp, monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    shell_tools.register(mock_mcp)

    result = mock_mcp.tools["execute_shell_command"]("rm -rf /")

    assert result.startswith("Blocked by FRIDAY safety policy")


def test_run_shell_command_requires_approval_for_git_push(mock_mcp, monkeypatch, tmp_path):
    from friday.tools import utils

    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    utils.register(mock_mcp)

    result = mock_mcp.tools["run_shell_command"]("git push origin main")

    assert "Approval required" in result
    assert "git push origin main" in result


def test_file_delete_requires_approval(mock_mcp, monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    file_tools.register(mock_mcp)
    target = tmp_path / "delete-me.txt"
    target.write_text("temporary", encoding="utf-8")

    result = mock_mcp.tools["delete_path"]("delete-me.txt")

    assert "Approval required" in result
    assert target.exists()


def test_git_push_tool_requires_approval(mock_mcp, monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    git_tool.register(mock_mcp)

    result = mock_mcp.tools["git_push"](repo_path=str(tmp_path))

    assert "Approval required" in result


def test_tool_permission_blocks_protected_path():
    decision = check_tool_permission("delete_path", {"path": "~/.ssh/id_rsa"}, subject="~/.ssh/id_rsa")

    assert decision.decision == "block"
