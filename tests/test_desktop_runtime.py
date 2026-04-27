from friday.core.executor import run_command_pipeline
from friday.core.models import PlanStep
from friday.core.risk import RiskLevel
from friday.desktop.runtime import DesktopRuntime
from friday.desktop.screen import take_screenshot


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.windows = []

    def open_application(self, app_name: str):
        self.windows.append({"app": app_name, "title": f"{app_name} main"})
        return {"ok": True, "message": f"Opened {app_name}."}

    def focus_application(self, app_name: str):
        return {"ok": True, "message": f"Focused {app_name}."}

    def close_application(self, app_name: str):
        return {"ok": True, "message": f"Closed {app_name}."}

    def list_open_windows(self):
        return list(self.windows)

    def get_active_window(self):
        return self.windows[-1] if self.windows else {"app": "", "title": ""}

    def list_installed_apps(self):
        return [{"name": "Notepad", "path": "/Applications/Notepad.app"}]


def _desktop_step(action_type: str, parameters: dict) -> PlanStep:
    return PlanStep(
        id="step_1",
        description="desktop test",
        executor="desktop",
        action_type=action_type,
        parameters=parameters,
        expected_result="done",
        risk_level=RiskLevel.REVERSIBLE_CHANGE,
        needs_approval=False,
        verification_method="window_active",
    )


def test_desktop_runtime_mock_app_open_and_verify(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    runtime = DesktopRuntime(backend=FakeBackend())

    result = runtime.open_application("Notepad", dry_run=False)

    assert result.ok is True
    assert runtime.verify_app_opened("Notepad") is True
    assert result.verification["app_opened"] is True
    assert result.verification["after_active_window"]["app"] == "Notepad"


def test_desktop_runtime_mock_window_active():
    runtime = DesktopRuntime(backend=FakeBackend())
    runtime.backend.windows.append({"app": "Notes", "title": "Notes main"})

    active = runtime.get_active_window()

    assert active["app"] == "Notes"


def test_screenshot_safe_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("friday.desktop.screen.platform.system", lambda: "Windows")

    def fail_pyautogui():
        raise RuntimeError("no display")

    class _BrokenImageGrab:
        @staticmethod
        def grab():
            raise RuntimeError("no display")

    monkeypatch.setattr("friday.desktop.screen._load_pyautogui", fail_pyautogui)
    monkeypatch.setattr(
        "friday.desktop.screen._module_available",
        lambda name: False if name == "PIL.ImageGrab" else False,
    )

    result = take_screenshot("safe_failure.png")

    assert result.ok is False
    assert "no display" in result.error


def test_non_windows_desktop_runtime_fails_gracefully(monkeypatch):
    monkeypatch.setattr("friday.desktop.runtime.platform.system", lambda: "Darwin")
    from friday.desktop.apps import UnsupportedDesktopBackend

    runtime = DesktopRuntime(backend=UnsupportedDesktopBackend("Darwin"))

    result = runtime.open_application("Notepad", dry_run=False)

    assert result.ok is False
    assert "Windows only" in result.message


def test_desktop_permission_check_for_close_requires_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    runtime = DesktopRuntime(backend=FakeBackend())

    result = runtime.close_application("Notes", dry_run=False)

    assert result.ok is False
    assert result.permission_decision == "ask"
    assert "Approval required" in result.message


def test_desktop_executor_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    runtime = DesktopRuntime(backend=FakeBackend())
    step = _desktop_step("open_app", {"app_name": "Notepad"})

    result = runtime.execute("open notepad", step, dry_run=True)

    assert result.ok is True
    assert result.dry_run is True
    assert "would open Notepad" in result.message


def test_core_pipeline_desktop_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))

    result = run_command_pipeline("open notepad and type hello", dry_run=True)

    assert result.plan.intent.intent.value == "desktop"
    assert all(step_result.status == "dry_run" for step_result in result.step_results)
