from unittest.mock import MagicMock
from friday.tools.diagnostics import (
    _check_macos_screen_recording,
    _check_macos_accessibility,
    register,
)


def test_screen_recording_granted(mocker):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mocker.patch("friday.tools.diagnostics.subprocess.run", return_value=mock_result)

    result = _check_macos_screen_recording()
    assert result["status"] == "Granted"


def test_screen_recording_denied(mocker):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mocker.patch("friday.tools.diagnostics.subprocess.run", return_value=mock_result)

    result = _check_macos_screen_recording()
    assert result["status"] == "Denied/Missing"
    assert "fix" in result
    assert "Privacy_ScreenCapture" in result["fix"]


def test_accessibility_granted(mocker):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Finder, Terminal, Code"
    mocker.patch("friday.tools.diagnostics.subprocess.run", return_value=mock_result)

    result = _check_macos_accessibility()
    assert result["status"] == "Granted"


def test_accessibility_denied(mocker):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Not allowed to send Apple events to System Events"
    mocker.patch("friday.tools.diagnostics.subprocess.run", return_value=mock_result)

    result = _check_macos_accessibility()
    assert result["status"] == "Denied/Missing"
    assert "fix" in result
    assert "Privacy_Accessibility" in result["fix"]


def test_run_permission_diagnostics_macos(mock_mcp, mocker):
    register(mock_mcp)
    run_perm_diag = mock_mcp.tools["run_permission_diagnostics"]

    mocker.patch("friday.tools.diagnostics.platform.system", return_value="Darwin")

    # Mock both checks as granted
    mock_sr = MagicMock(returncode=0)
    mock_acc = MagicMock(returncode=0, stdout="Finder, Code")
    mocker.patch(
        "friday.tools.diagnostics.subprocess.run",
        side_effect=[mock_sr, mock_acc]
    )

    result = run_perm_diag()
    assert "Screen Recording" in result
    assert "Accessibility" in result
    assert "Granted" in result


def test_run_permission_diagnostics_denied_shows_fix(mock_mcp, mocker):
    register(mock_mcp)
    run_perm_diag = mock_mcp.tools["run_permission_diagnostics"]

    mocker.patch("friday.tools.diagnostics.platform.system", return_value="Darwin")

    # Screen recording denied
    mock_sr = MagicMock(returncode=1)
    # Accessibility granted
    mock_acc = MagicMock(returncode=0, stdout="Finder")
    mocker.patch(
        "friday.tools.diagnostics.subprocess.run",
        side_effect=[mock_sr, mock_acc]
    )

    result = run_perm_diag()
    assert "Denied" in result
    assert "How to Fix" in result
    assert "Privacy_ScreenCapture" in result
