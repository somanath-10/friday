"""
Deterministic structured planner for FRIDAY.

The planner intentionally handles safe, repeatable workflows itself and leaves
open-ended reasoning or repair tasks to the legacy LLM tool loop. That keeps
local control permission-aware without pretending every natural-language
request can be solved by a fixed template.
"""

from __future__ import annotations

import re
import os

from friday.core.models import ExecutionPlan, Intent, IntentResult, IntentRoute, Plan, PlanStep
from friday.core.permissions import check_shell_permission, check_tool_permission
from friday.core.risk import (
    RiskLevel,
    classify_browser_action,
    classify_desktop_action,
    classify_file_operation,
)
from friday.core.router import route_intent


SPECIAL_PATH_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("downloads", "download folder", "download directory"), "Downloads"),
    (("documents", "document folder", "document directory"), "Documents"),
    (("desktop",), "Desktop"),
    (("pictures", "picture folder", "photos"), "Pictures"),
    (("videos", "video folder"), "Videos"),
    (("music", "songs"), "Music"),
    (("home", "user folder"), "home"),
    (("reports folder", "report folder", "reports directory"), "workspace/reports"),
    (("workspace", "work space"), "workspace"),
)

APP_ALIASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("notepad",), "Notepad"),
    (("chrome", "google chrome"), "Chrome"),
    (("edge", "microsoft edge"), "Edge"),
    (("vscode", "vs code", "visual studio code"), "Visual Studio Code"),
    (("calculator", "calc"), "Calculator"),
    (("file explorer", "explorer"), "File Explorer"),
    (("terminal",), "Windows Terminal"),
    (("command prompt", "cmd"), "Command Prompt"),
    (("powershell",), "Windows PowerShell"),
)


def _step(
    index: int,
    *,
    description: str,
    executor: str,
    action_type: str,
    parameters: dict,
    expected_result: str,
    risk_level: RiskLevel,
    needs_approval: bool,
    verification_method: str,
    fallback_strategy: str = "",
    tool_name: str = "",
    verification_target: str = "",
) -> PlanStep:
    return PlanStep(
        id=f"step_{index}",
        description=description,
        executor=executor,
        action_type=action_type,
        parameters=parameters,
        expected_result=expected_result,
        risk_level=risk_level,
        needs_approval=needs_approval,
        verification_method=verification_method,
        tool_name=tool_name,
        verification_target=verification_target,
        fallback_strategy=fallback_strategy,
    )


def _extract_quoted_text(message: str) -> str:
    match = re.search(r"['\"]([^'\"]+)['\"]", message)
    return match.group(1) if match else ""


def _special_path_from_text(message: str) -> str:
    lowered = message.lower()
    for markers, path in SPECIAL_PATH_HINTS:
        if any(marker in lowered for marker in markers):
            return path
    return ""


def _extract_path_hint(message: str) -> str:
    quoted = _extract_quoted_text(message)
    if quoted and any(sep in quoted for sep in ("/", "\\", ".")):
        return quoted

    special = _special_path_from_text(message)
    if special:
        return special

    match = re.search(r"\b(?:delete|remove|list|read|open|move|rename|copy)\s+([^\s]+)", message, flags=re.IGNORECASE)
    if not match:
        return ""
    candidate = match.group(1).strip(".,;:()[]{}")
    blocked_words = {"all", "files", "folders", "everything", "the", "my"}
    return "" if candidate.lower() in blocked_words else candidate


def _extract_move_paths(message: str) -> tuple[str, str]:
    lowered = message.lower()
    source = _special_path_from_text(message) or _extract_path_hint(message)
    destination = ""
    to_match = re.search(r"\bto\s+([^,.]+)", lowered)
    if to_match:
        destination = to_match.group(1).strip().strip("'").strip('"')
        for markers, path in SPECIAL_PATH_HINTS:
            if any(marker in destination for marker in markers):
                destination = path
                break
    return source, destination


def _is_folder_open_request(message: str) -> bool:
    lowered = message.lower()
    if not any(marker in lowered for marker in ("open", "show", "reveal")):
        return False
    if "file explorer" in lowered or " in explorer" in lowered or " folder" in lowered:
        return True
    return any(marker in lowered for marker in ("desktop", "downloads", "documents", "pictures", "videos", "music", "workspace")) and "type " not in lowered


def _extract_app_name(message: str) -> str:
    lowered = message.lower()
    for markers, app_name in APP_ALIASES:
        if any(marker in lowered for marker in markers):
            return app_name
    quoted = _extract_quoted_text(message)
    if quoted:
        return quoted
    match = re.search(r"\bopen\s+([a-zA-Z0-9_. -]+?)(?:\s+and\s+|\s+then\s+|$)", message, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip(" .,;:")
        if candidate:
            return candidate
    return "requested application"


def _extract_type_text(message: str) -> str:
    quoted = _extract_quoted_text(message)
    if quoted:
        return quoted
    match = re.search(r"\btype\s+(.+)$", message, flags=re.IGNORECASE)
    if not match:
        return "hello"
    text = match.group(1).strip()
    text = re.sub(
        r"\s+(?:in|into|inside)\s+(?:notepad|chrome|edge|the app|application).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip(" .,;:") or "hello"


def _extract_browser_name(message: str) -> str:
    lowered = message.lower()
    if "edge" in lowered:
        return "Edge"
    if "chrome" in lowered:
        return "Chrome"
    return "Browser"


def _wants_first_browser_result(message: str) -> bool:
    lowered = message.lower()
    first_target = any(
        phrase in lowered
        for phrase in (
            "first video",
            "first result",
            "first one",
            "1st video",
            "1st result",
        )
    )
    click_target = any(word in lowered for word in ("open", "click", "play", "select"))
    only_video = ("only click" in lowered or "u only click" in lowered or "you only click" in lowered) and "video" in lowered
    return (first_target and click_target) or only_video


def _extract_site_search_query(message: str, site: str) -> str:
    text = " ".join(message.strip().split())
    site_pattern = re.escape(site)
    patterns = (
        rf"\b{site_pattern}\s+search\s+(.+?)(?:\s+and\s+(?:open|click|play)\b|$)",
        rf"\bsearch\s+{site_pattern}\s+for\s+(.+?)(?:\s+and\s+(?:open|click|play)\b|$)",
        rf"\bsearch(?: for)?\s+(.+?)\s+(?:on|in|from)\s+{site_pattern}\b",
        r"\bsearch(?: for)?\s+(.+?)(?:\s+and\s+(?:open|click|play)\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            query = match.group(1).strip(" .,:;")
            query = re.sub(rf"\b{site_pattern}\b", " ", query, flags=re.IGNORECASE)
            query = re.sub(r"\b(?:video|videos|result|results)\b$", "", query, flags=re.IGNORECASE).strip(" .,:;")
            return re.sub(r"\s+", " ", query)
    return ""


def _is_youtube_search_and_open_first(message: str) -> bool:
    lowered = message.lower()
    return "youtube" in lowered and "search" in lowered and _wants_first_browser_result(message)


def _is_browser_click_first_request(message: str) -> bool:
    lowered = message.lower()
    if not _wants_first_browser_result(message):
        return False
    return any(
        marker in lowered
        for marker in (
            "current",
            "this page",
            "the page",
            "search results page",
            "in it",
            "on it",
            "from it",
            "first result",
            "first video",
            "first one",
        )
    )


def _is_react_project_request(message: str) -> bool:
    lowered = message.lower()
    return "react" in lowered and "project" in lowered and any(
        marker in lowered for marker in ("initialize", "initialise", "create", "make", "setup", "set up")
    )


def _is_calculator_page_request(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in ("calculator webpage", "calculator web page", "calculator page")) and any(
        marker in lowered for marker in ("make", "create", "add", "build")
    )


def _extract_project_name(message: str) -> str:
    quoted = _extract_quoted_text(message)
    if quoted and "/" not in quoted and "\\" not in quoted:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "-", quoted).strip("-")
    patterns = (
        r"\b(?:named|called|name(?:d)?\s+is|in\s+the\s+name)\s+([a-zA-Z0-9_.-]+)",
        r"\bproject\s+([a-zA-Z0-9_.-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" .,:;")
            if candidate.lower() not in {"in", "at", "on", "with"}:
                return candidate
    return ""


def _extract_project_location(message: str) -> str:
    lowered = message.lower()
    for markers, path in SPECIAL_PATH_HINTS:
        if any(marker in lowered for marker in markers):
            return path
    match = re.search(r"\bin\s+([a-zA-Z]:[\\/][^,]+|[~/]?[a-zA-Z0-9_.\\/ -]+?)\s+(?:named|called|in the name|with|and|$)", message, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(" .,:;")
    return ""


def _extract_project_path(message: str) -> str:
    match = re.search(r"\b(?:project\s+)?at\s+(.+)$", message, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(" .,:;\"'")
    match = re.search(r"\bin\s+the\s+project\s+(.+)$", message, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(" .,:;\"'")
    return ""


def _shell_cd_command(directory: str, command: str) -> str:
    if os.name == "nt":
        return f'cd /d "{directory}" && {command}'
    return f'cd "{directory}" && {command}'


def _react_app_jsx() -> str:
    return """import { useMemo, useState } from "react";
import "./App.css";

const buttons = [
  "7", "8", "9", "/",
  "4", "5", "6", "*",
  "1", "2", "3", "-",
  "0", ".", "=", "+",
];

function App() {
  const [display, setDisplay] = useState("0");
  const [expression, setExpression] = useState("");

  const preview = useMemo(() => expression || display, [display, expression]);

  function appendValue(value) {
    if (value === "=") {
      try {
        const normalized = expression || display;
        if (!/^[0-9+\\-*/. ()]+$/.test(normalized)) {
          throw new Error("Invalid expression");
        }
        const result = Function(`"use strict"; return (${normalized})`)();
        setDisplay(String(Number.isFinite(result) ? result : "Error"));
        setExpression("");
      } catch {
        setDisplay("Error");
        setExpression("");
      }
      return;
    }

    setExpression((current) => {
      const next = current === "" && display !== "0" ? display + value : current + value;
      setDisplay(next);
      return next;
    });
  }

  function clearAll() {
    setDisplay("0");
    setExpression("");
  }

  function backspace() {
    setExpression((current) => {
      const next = current.slice(0, -1);
      setDisplay(next || "0");
      return next;
    });
  }

  return (
    <main className="calculator-shell">
      <section className="calculator" aria-label="Calculator">
        <div className="display">
          <span className="expression">{preview}</span>
          <strong>{display}</strong>
        </div>
        <div className="utility-row">
          <button type="button" onClick={clearAll}>AC</button>
          <button type="button" onClick={backspace}>DEL</button>
        </div>
        <div className="keypad">
          {buttons.map((button) => (
            <button
              type="button"
              key={button}
              className={/[+\\-*/=]/.test(button) ? "operator" : ""}
              onClick={() => appendValue(button)}
            >
              {button}
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

export default App;
"""


def _react_app_css() -> str:
    return """#root {
  min-height: 100vh;
}

.calculator-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #101820, #23395d 48%, #0f766e);
  color: #f8fafc;
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.calculator {
  width: min(92vw, 360px);
  padding: 24px;
  border-radius: 8px;
  background: #111827;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.35);
}

.display {
  min-height: 112px;
  display: grid;
  align-content: end;
  gap: 8px;
  padding: 18px;
  border-radius: 6px;
  background: #020617;
  text-align: right;
  overflow-wrap: anywhere;
}

.expression {
  min-height: 20px;
  color: #94a3b8;
  font-size: 0.95rem;
}

.display strong {
  font-size: 2.4rem;
  line-height: 1.1;
}

.utility-row,
.keypad {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.utility-row {
  grid-template-columns: 1fr 1fr;
}

.keypad {
  grid-template-columns: repeat(4, 1fr);
}

button {
  min-height: 54px;
  border: 0;
  border-radius: 6px;
  background: #334155;
  color: #f8fafc;
  font-size: 1.1rem;
  font-weight: 700;
  cursor: pointer;
}

button:hover {
  background: #475569;
}

button.operator,
.utility-row button {
  background: #14b8a6;
  color: #042f2e;
}
"""


def _react_project_plan(message: str) -> list[PlanStep]:
    project_name = _extract_project_name(message)
    location = _extract_project_location(message)
    if not project_name or not location:
        return []

    from friday.path_utils import resolve_user_path

    normalized_location = location.rstrip("/\\")
    project_relative = f"{normalized_location}/{project_name}"
    project_path = resolve_user_path(project_relative)
    location_path = resolve_user_path(location)
    if project_path.exists():
        assessment = classify_file_operation("overwrite", str(project_path), overwrite=True)
        return [
            _step(
                1,
                description=f"Ask before reusing or overwriting the existing React project folder at {project_relative}.",
                executor="files",
                action_type="confirm_existing_project",
                parameters={"path": project_relative, "project_name": project_name, "location": location},
                expected_result="The user chooses whether to reuse, overwrite, or pick a different project name.",
                risk_level=assessment.level,
                needs_approval=True,
                verification_method="user_decision_required",
                tool_name="run_shell_command",
                verification_target=str(project_path),
            )
        ]

    create_command = _shell_cd_command(str(location_path), f"npm create vite@latest {project_name} -- --template react")
    install_command = _shell_cd_command(str(project_path), "npm install")
    build_command = _shell_cd_command(str(project_path), "npm run build")
    verify_script = (
        "const fs=require('fs');"
        "for (const f of ['package.json','src/App.jsx']) { if (!fs.existsSync(f)) throw new Error(f+' missing'); }"
        "const app=fs.readFileSync('src/App.jsx','utf8');"
        "if (!/calculator|useState|keypad/i.test(app)) throw new Error('calculator UI missing');"
        "console.log('React calculator project verified');"
    )
    verify_command = _shell_cd_command(str(project_path), f'node -e "{verify_script}"')

    create_decision = check_shell_permission(create_command)
    install_decision = check_shell_permission(install_command)
    build_decision = check_shell_permission(build_command)
    verify_decision = check_shell_permission(verify_command)
    file_assessment = classify_file_operation("write_new")

    return [
        _step(
            1,
            description=f"Check that the target React project path is available: {project_relative}.",
            executor="files",
            action_type="check_project_path",
            parameters={"path": project_relative, "limit": 20},
            expected_result="The target folder does not already exist.",
            risk_level=RiskLevel.READ_ONLY,
            needs_approval=False,
            verification_method="path_available",
            tool_name="list_directory_tree",
            verification_target=str(project_path),
        ),
        _step(
            2,
            description="Create the Vite React project in the requested Documents folder.",
            executor="code",
            action_type="shell_command",
            parameters={"command": create_command},
            expected_result="Vite creates a new React project folder.",
            risk_level=create_decision.risk_level,
            needs_approval=create_decision.needs_approval,
            verification_method="command_output_ok",
            tool_name="run_shell_command",
        ),
        _step(
            3,
            description="Install React project dependencies.",
            executor="code",
            action_type="shell_command",
            parameters={"command": install_command},
            expected_result="npm installs dependencies for the generated React project.",
            risk_level=install_decision.risk_level,
            needs_approval=install_decision.needs_approval,
            verification_method="command_output_ok",
            tool_name="run_shell_command",
        ),
        _step(
            4,
            description="Replace the generated App component with a calculator UI.",
            executor="files",
            action_type="write_file",
            parameters={"path": f"{project_relative}/src/App.jsx", "content": _react_app_jsx()},
            expected_result="src/App.jsx contains the calculator React component.",
            risk_level=file_assessment.level,
            needs_approval=False,
            verification_method="file_exists",
            tool_name="write_file",
            verification_target=str(project_path / "src" / "App.jsx"),
        ),
        _step(
            5,
            description="Replace the generated app styles with calculator styling.",
            executor="files",
            action_type="write_file",
            parameters={"path": f"{project_relative}/src/App.css", "content": _react_app_css()},
            expected_result="src/App.css contains calculator styling.",
            risk_level=file_assessment.level,
            needs_approval=False,
            verification_method="file_exists",
            tool_name="write_file",
            verification_target=str(project_path / "src" / "App.css"),
        ),
        _step(
            6,
            description="Run the production build to verify the React calculator compiles.",
            executor="code",
            action_type="shell_command",
            parameters={"command": build_command},
            expected_result="npm run build exits successfully.",
            risk_level=build_decision.risk_level,
            needs_approval=build_decision.needs_approval,
            verification_method="command_output_ok",
            tool_name="run_shell_command",
        ),
        _step(
            7,
            description="Verify package.json, src/App.jsx, calculator UI code, and build evidence.",
            executor="code",
            action_type="verify_react_project",
            parameters={"command": verify_command, "project_path": project_relative},
            expected_result="Project files exist and the calculator UI code is present.",
            risk_level=verify_decision.risk_level,
            needs_approval=verify_decision.needs_approval,
            verification_method="react_project_verified",
            tool_name="run_shell_command",
            verification_target=str(project_path),
        ),
    ]


def _calculator_page_plan(message: str) -> list[PlanStep]:
    project_path = _extract_project_path(message)
    if not project_path:
        return []

    from friday.path_utils import resolve_user_path

    resolved_project = resolve_user_path(project_path)
    build_command = _shell_cd_command(str(resolved_project), "npm run build")
    verify_script = (
        "const fs=require('fs');"
        "for (const f of ['package.json','src/App.jsx']) { if (!fs.existsSync(f)) throw new Error(f+' missing'); }"
        "const app=fs.readFileSync('src/App.jsx','utf8');"
        "if (!/calculator|useState|keypad/i.test(app)) throw new Error('calculator UI missing');"
        "console.log('Calculator page verified');"
    )
    verify_command = _shell_cd_command(str(resolved_project), f'node -e "{verify_script}"')
    build_decision = check_shell_permission(build_command)
    verify_decision = check_shell_permission(verify_command)
    write_assessment = classify_file_operation("edit")
    project_root_text = project_path.rstrip("/\\")

    return [
        _step(
            1,
            description="Inspect the target project folder before changing app files.",
            executor="files",
            action_type="list_tree",
            parameters={"path": project_path, "limit": 80},
            expected_result="Project files are visible before edits are planned.",
            risk_level=RiskLevel.READ_ONLY,
            needs_approval=False,
            verification_method="output_nonempty",
            tool_name="list_directory_tree",
            verification_target=str(resolved_project),
        ),
        _step(
            2,
            description="Write the calculator React component into src/App.jsx.",
            executor="files",
            action_type="write_file",
            parameters={"path": f"{project_root_text}/src/App.jsx", "content": _react_app_jsx()},
            expected_result="src/App.jsx contains calculator UI code.",
            risk_level=write_assessment.level,
            needs_approval=write_assessment.level >= RiskLevel.SENSITIVE_ACTION,
            verification_method="file_exists",
            tool_name="write_file",
            verification_target=str(resolved_project / "src" / "App.jsx"),
        ),
        _step(
            3,
            description="Write calculator styles into src/App.css.",
            executor="files",
            action_type="write_file",
            parameters={"path": f"{project_root_text}/src/App.css", "content": _react_app_css()},
            expected_result="src/App.css contains calculator styling.",
            risk_level=write_assessment.level,
            needs_approval=write_assessment.level >= RiskLevel.SENSITIVE_ACTION,
            verification_method="file_exists",
            tool_name="write_file",
            verification_target=str(resolved_project / "src" / "App.css"),
        ),
        _step(
            4,
            description="Run the project build after editing calculator files.",
            executor="code",
            action_type="shell_command",
            parameters={"command": build_command},
            expected_result="The build exits successfully.",
            risk_level=build_decision.risk_level,
            needs_approval=build_decision.needs_approval,
            verification_method="command_output_ok",
            tool_name="run_shell_command",
        ),
        _step(
            5,
            description="Verify the calculator page files and UI markers exist.",
            executor="code",
            action_type="verify_react_project",
            parameters={"command": verify_command, "project_path": project_path},
            expected_result="Calculator page code is present and verifiable.",
            risk_level=verify_decision.risk_level,
            needs_approval=verify_decision.needs_approval,
            verification_method="react_project_verified",
            tool_name="run_shell_command",
            verification_target=str(resolved_project),
        ),
    ]


def _file_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    if _is_folder_open_request(message) and any(word in lowered for word in ("open", "show", "reveal")):
        assessment = classify_file_operation("read")
        return [
            _step(
                1,
                description="Open the requested folder in Windows File Explorer after safe path resolution.",
                executor="files",
                action_type="open_path",
                parameters={"path": _extract_path_hint(message) or _special_path_from_text(message) or "workspace"},
                expected_result="The folder opens in File Explorer.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="file_exists",
            )
        ]

    if any(word in lowered for word in ("list", "show files", "tree")) and "delete" not in lowered:
        assessment = classify_file_operation("list")
        return [
            _step(
                1,
                description="List the requested directory through the filesystem runtime.",
                executor="files",
                action_type="list_tree",
                parameters={"path": _extract_path_hint(message) or "Downloads", "limit": 200},
                expected_result="Directory entries are returned without modifying files.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="output_nonempty",
            )
        ]

    if "delete" in lowered or "remove" in lowered:
        target = _extract_path_hint(message)
        preview = _step(
            1,
            description="Preview the destructive file request before any deletion is possible.",
            executor="files",
            action_type="list_tree",
            parameters={"path": target or "Downloads", "limit": 500},
            expected_result="User can see the affected files before approval.",
            risk_level=RiskLevel.READ_ONLY,
            needs_approval=False,
            verification_method="output_nonempty",
        )
        assessment = classify_file_operation("delete")
        delete = _step(
            2,
            description="Request approval before deleting the selected path or files.",
            executor="files",
            action_type="delete_path",
            parameters={"path": target, "requires_preview": True},
            expected_result="Deletion is blocked until the user approves it.",
            risk_level=assessment.level,
            needs_approval=True,
            verification_method="path_absent",
        )
        return [preview, delete]

    if any(word in lowered for word in ("move", "rename", "copy")):
        source, destination = _extract_move_paths(message)
        operation = "copy" if "copy" in lowered else "move"
        assessment = classify_file_operation(operation)
        return [
            _step(
                1,
                description=f"{operation.title()} the requested file or folder after path safety checks.",
                executor="files",
                action_type="copy_path" if operation == "copy" else "move_path",
                parameters={"source_path": source, "destination_path": destination, "overwrite": False},
                expected_result="Path exists at the destination and original state is preserved or moved safely.",
                risk_level=assessment.level,
                needs_approval=assessment.level >= RiskLevel.SENSITIVE_ACTION,
                verification_method="file_exists",
            )
        ]

    assessment = classify_file_operation("write_new")
    path_text = re.sub(r"['\"][^'\"]+['\"]", "", lowered)
    wants_report_path = any(
        phrase in path_text
        for phrase in ("report file", "reports folder", "report folder", "make report", "save report")
    )
    default_path = "workspace/reports/report.md" if wants_report_path else "workspace/generated_by_friday.txt"
    return [
        _step(
            1,
            description="Create or save the requested file in the workspace.",
            executor="files",
            action_type="write_file",
            parameters={"path": default_path, "content": _extract_quoted_text(message) or message},
            expected_result="File exists at the target path.",
            risk_level=assessment.level,
            needs_approval=False,
            verification_method="file_exists",
        )
    ]


def _shell_or_code_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    if _is_react_project_request(message):
        return _react_project_plan(message)
    if _is_calculator_page_request(message):
        return _calculator_page_plan(message)
    project_path = _extract_project_path(message)
    if project_path and "build" in lowered:
        from friday.path_utils import resolve_user_path

        command = _shell_cd_command(str(resolve_user_path(project_path)), "npm run build")
        decision = check_shell_permission(command)
        return [
            _step(
                1,
                description="Run the project build in the referenced project folder.",
                executor="code",
                action_type="shell_command",
                parameters={"command": command},
                expected_result="The build command exits successfully.",
                risk_level=decision.risk_level,
                needs_approval=decision.needs_approval,
                verification_method="command_output_ok",
            )
        ]
    if project_path and "run" in lowered:
        from friday.path_utils import resolve_user_path

        command = _shell_cd_command(str(resolve_user_path(project_path)), "npm run dev")
        decision = check_shell_permission(command)
        return [
            _step(
                1,
                description="Start the project development command in the referenced project folder.",
                executor="code",
                action_type="shell_command",
                parameters={"command": command},
                expected_result="The project run command starts or reports captured output.",
                risk_level=decision.risk_level,
                needs_approval=decision.needs_approval,
                verification_method="command_output_ok",
            )
        ]
    if lowered.startswith("open ") and any(term in lowered for term in ("powershell", "cmd", "command prompt", "terminal")) and not any(term in lowered for term in ("initialize", "initialise", "create", "setup", "set up")):
        return _desktop_plan(message)
    if "push" in lowered:
        command = "git push"
    elif "commit" in lowered:
        command = "git commit -m 'FRIDAY changes'"
    elif "test" in lowered or "pytest" in lowered:
        command = "pytest tests -q"
    else:
        command = message
    decision = check_shell_permission(command)
    return [
        _step(
            1,
            description="Run the requested local command with permission checks.",
            executor="code" if intent.intent == Intent.CODE else "shell",
            action_type="shell_command",
            parameters={"command": command},
            expected_result="Command exits successfully or returns a captured error.",
            risk_level=decision.risk_level,
            needs_approval=decision.needs_approval,
            verification_method="exit_code",
        )
    ]


def _desktop_plan(message: str) -> list[PlanStep]:
    lowered = message.lower()
    if "screenshot" in lowered or "screen" in lowered and "error" in lowered:
        assessment = classify_desktop_action("inspect_screen")
        return [
            _step(
                1,
                description="Capture and inspect the screen before giving a local error-analysis response.",
                executor="desktop",
                action_type="inspect_screen",
                parameters={"question": message},
                expected_result="A screenshot artifact is saved and any available analysis is returned.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="output_nonempty",
                fallback_strategy="Use screenshot/OCR fallback if direct screen inspection is unavailable.",
            )
        ]

    if lowered.startswith("focus "):
        assessment = classify_desktop_action("focus_window")
        app_name = _extract_app_name(message.replace("focus", "open", 1))
        return [
            _step(
                1,
                description=f"Focus {app_name} by app/window name.",
                executor="desktop",
                action_type="focus_window",
                parameters={"app_name": app_name},
                expected_result="Requested window is active.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="window_active",
                fallback_strategy="List windows and ask the user if no matching window is found.",
            )
        ]

    if lowered.startswith("close "):
        assessment = classify_desktop_action("close_app")
        app_name = _extract_app_name(message.replace("close", "open", 1))
        return [
            _step(
                1,
                description=f"Request permission before closing {app_name}.",
                executor="desktop",
                action_type="close_app",
                parameters={"app_name": app_name},
                expected_result="Requested window is closed after approval if needed.",
                risk_level=assessment.level,
                needs_approval=assessment.level >= RiskLevel.SENSITIVE_ACTION,
                verification_method="window_absent",
                fallback_strategy="Ask the user to take over if unsaved changes or a modal blocks close.",
            )
        ]

    assessment = classify_desktop_action("open_app")
    app_name = _extract_app_name(message)
    steps = [
        _step(
            1,
            description=f"Open {app_name}.",
            executor="desktop",
            action_type="open_app",
            parameters={"app_name": app_name},
            expected_result="Application window is active or visible.",
            risk_level=assessment.level,
            needs_approval=False,
            verification_method="window_active",
            fallback_strategy="Resolve Windows app alias, then use PowerShell launch fallback.",
        )
    ]
    if "type" in message.lower() or "press" in message.lower():
        type_assessment = classify_desktop_action("type_text")
        steps.append(
            _step(
                2,
                description="Observe the active window and perform the requested desktop action using UI Automation targets.",
                executor="desktop",
                action_type="dynamic_desktop_task",
                parameters={"goal": message, "text": _extract_type_text(message)},
                expected_result="Requested desktop interaction is completed through observed controls.",
                risk_level=type_assessment.level,
                needs_approval=False,
                verification_method="dynamic_goal_progress",
                fallback_strategy="Use hotkeys, screenshot/OCR, or user takeover if UI Automation cannot identify the control.",
            )
        )
    return steps


def _screenshot_plan(message: str) -> list[PlanStep]:
    lowered = message.lower()
    wants_analysis = any(marker in lowered for marker in ("analyze", "analyse", "what is", "read", "debug", "error", "popup"))
    assessment = classify_desktop_action("inspect_screen" if wants_analysis else "screenshot")
    return [
        _step(
            1,
            description="Capture the current screen to a workspace screenshot artifact.",
            executor="desktop",
            action_type="inspect_screen" if wants_analysis else "screenshot",
            parameters={"question": message, "filename": ""},
            expected_result="A screenshot artifact is saved and any available OCR/vision analysis is returned.",
            risk_level=assessment.level,
            needs_approval=False,
            verification_method="artifact_or_output",
            tool_name="inspect_desktop_screen" if wants_analysis else "take_screenshot",
            fallback_strategy="Use OCR/vision when available; otherwise return the screenshot artifact path and setup message.",
        )
    ]


def _screen_recording_plan(message: str) -> list[PlanStep]:
    lowered = message.lower()
    if any(marker in lowered for marker in ("stop screen recording", "save the recording", "stop recording")):
        assessment = classify_desktop_action("stop_screen_recording")
        return [
            _step(
                1,
                description="Stop the active explicit screen recording session.",
                executor="screen_recording",
                action_type="stop_screen_recording",
                parameters={},
                expected_result="The active recording is stopped and the local artifact path is reported.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="screen_recording_stopped",
                tool_name="stop_screen_recording",
            )
        ]

    if any(marker in lowered for marker in ("analyze the recording", "analyse the recording")):
        assessment = classify_desktop_action("stop_screen_recording")
        return [
            _step(
                1,
                description="Inspect the saved screen recording artifact metadata for local analysis.",
                executor="screen_recording",
                action_type="analyze_screen_recording",
                parameters={},
                expected_result="Recording metadata or a clear setup message is returned.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="output_nonempty",
                tool_name="analyze_screen_recording",
            )
        ]

    assessment = classify_desktop_action("start_screen_recording")
    return [
        _step(
            1,
            description="Request explicit approval before starting local screen recording.",
            executor="screen_recording",
            action_type="start_screen_recording",
            parameters={"max_duration_seconds": 60},
            expected_result="Screen recording starts only after explicit approval and records locally.",
            risk_level=assessment.level,
            needs_approval=True,
            verification_method="screen_recording_started",
            tool_name="start_screen_recording",
            fallback_strategy="If recording dependencies are missing, report setup instructions without recording.",
        )
    ]


def _browser_or_research_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    executor = "research" if intent.intent == Intent.RESEARCH else "browser"
    steps: list[PlanStep] = []

    current_page_request = any(marker in lowered for marker in ("current", "this page", "the page", "in it", "on it", "from it"))
    if _is_youtube_search_and_open_first(message) and not current_page_request:
        query = _extract_site_search_query(message, "youtube")
        open_assessment = classify_browser_action("navigate")
        click_assessment = classify_browser_action("click")
        return [
            _step(
                1,
                description="Open YouTube in the browser.",
                executor="browser",
                action_type="open_url",
                parameters={"url": "https://www.youtube.com"},
                expected_result="YouTube opens in the visible browser.",
                risk_level=open_assessment.level,
                needs_approval=False,
                verification_method="browser_result_opened",
                tool_name="open_url",
                verification_target="https://www.youtube.com",
            ),
            _step(
                2,
                description=f"Search YouTube for {query}.",
                executor="browser",
                action_type="dynamic_search",
                parameters={"goal": f"search for {query} on YouTube", "max_steps": 4},
                expected_result="YouTube search results are displayed for the query.",
                risk_level=open_assessment.level,
                needs_approval=False,
                verification_method="dynamic_goal_progress",
                tool_name="browser_dynamic_loop",
                verification_target=query,
            ),
            _step(
                3,
                description="Click the first visible video result using browser observation.",
                executor="browser",
                action_type="click_first_result",
                parameters={"goal": f"On the current YouTube search results page for '{query}', click the first video result.", "max_steps": 4},
                expected_result="The first YouTube video result is clicked.",
                risk_level=click_assessment.level,
                needs_approval=False,
                verification_method="browser_result_opened",
                tool_name="browser_dynamic_loop",
                verification_target="first video",
            ),
            _step(
                4,
                description="Verify that a YouTube video page or player is open.",
                executor="browser",
                action_type="verify_video_opened",
                parameters={"limit": 30},
                expected_result="The browser URL, title, or page state shows the selected video is open.",
                risk_level=open_assessment.level,
                needs_approval=False,
                verification_method="browser_video_opened",
                tool_name="browser_get_state",
                verification_target="youtube video",
            ),
        ]

    if _is_browser_click_first_request(message):
        click_assessment = classify_browser_action("click")
        target = "video" if "video" in lowered or "youtube" in lowered else "result"
        return [
            _step(
                1,
                description="Observe the current browser page before choosing a clickable result.",
                executor="browser",
                action_type="browser_get_state",
                parameters={"limit": 30},
                expected_result="Visible browser links, buttons, and cards are available for selection.",
                risk_level=RiskLevel.READ_ONLY,
                needs_approval=False,
                verification_method="output_nonempty",
                tool_name="browser_get_state",
            ),
            _step(
                2,
                description=f"Click the first visible {target} result using the browser element map.",
                executor="browser",
                action_type="click_first_result",
                parameters={"goal": message, "max_steps": 4},
                expected_result=f"The first relevant {target} result is opened.",
                risk_level=click_assessment.level,
                needs_approval=False,
                verification_method="browser_result_opened",
                tool_name="browser_dynamic_loop",
                verification_target=f"first {target}",
            ),
            _step(
                3,
                description="Verify that the browser moved to the selected result page.",
                executor="browser",
                action_type="verify_video_opened" if target == "video" else "verify_result_opened",
                parameters={"limit": 30},
                expected_result="The browser URL, title, or visible page state changed after the click.",
                risk_level=RiskLevel.READ_ONLY,
                needs_approval=False,
                verification_method="browser_video_opened" if target == "video" else "browser_result_opened",
                tool_name="browser_get_state",
                verification_target=f"opened {target}",
            ),
        ]

    mentions_browser_app = any(name in lowered for name in ("chrome", "edge"))
    browser_task_markers = ("search", "go to", "visit", "website", "url", "login", "bank", "http://", "https://", "latest", "news", "page")
    if mentions_browser_app:
        launch_assessment = classify_desktop_action("open_app")
        steps.append(
            _step(
                1,
                description="Open the requested browser application before the web task.",
                executor="desktop",
                action_type="open_app",
                parameters={"app_name": _extract_browser_name(message)},
                expected_result="The requested browser window is open and available.",
                risk_level=launch_assessment.level,
                needs_approval=False,
                verification_method="window_active",
            )
        )
    if mentions_browser_app and not any(marker in lowered for marker in browser_task_markers):
        return steps
    sensitive_goal = any(word in lowered for word in ("login", "password", "submit", "send", "purchase", "payment", "checkout", "bank"))
    assessment = classify_browser_action("submit" if sensitive_goal else "read")
    steps.append(
        _step(
            len(steps) + 1,
            description="Run a generic browser observe-act-verify loop using DOM/accessibility targets.",
            executor=executor if executor == "research" else "browser",
            action_type="dynamic_browser_task",
            parameters={"goal": message, "browser": _extract_browser_name(message)},
            expected_result="The browser task progresses through observed page elements, not hardcoded site selectors.",
            risk_level=assessment.level,
            needs_approval=sensitive_goal,
            verification_method="dynamic_goal_progress",
            fallback_strategy="Use accessibility snapshot, then screenshot fallback; ask user on login, captcha, payment, or permission prompts.",
        )
    )
    if any(word in lowered for word in ("save", "report", "summary")):
        file_assessment = classify_file_operation("write_new")
        steps.append(
            _step(
                len(steps) + 1,
                description="Save a local report placeholder after research output is produced.",
                executor="files",
                action_type="write_file",
                parameters={
                    "path": "workspace/reports/research_report.md",
                    "content": (
                        "# Research Report\n\n"
                        f"Topic: {message}\n\n"
                        "Run the full local chat workflow to populate this report with cited sources."
                    ),
                },
                expected_result="Report file exists in the workspace reports folder.",
                risk_level=file_assessment.level,
                needs_approval=False,
                verification_method="file_exists",
            )
        )
    return steps


def create_plan(user_message: str, intent_result: IntentResult | None = None) -> Plan:
    intent = intent_result or route_intent(user_message)
    if intent.intent == Intent.FILES:
        steps = _file_plan(user_message, intent)
    elif intent.intent in {Intent.SHELL, Intent.CODE}:
        steps = _shell_or_code_plan(user_message, intent)
    elif intent.intent == Intent.DESKTOP:
        steps = _desktop_plan(user_message)
    elif intent.intent == Intent.SCREENSHOT:
        steps = _screenshot_plan(user_message)
    elif intent.intent == Intent.SCREEN_RECORDING:
        steps = _screen_recording_plan(user_message)
    elif intent.intent in {Intent.BROWSER, Intent.RESEARCH}:
        steps = _browser_or_research_plan(user_message, intent)
    elif intent.intent == Intent.MIXED:
        steps = _browser_or_research_plan(user_message, intent) + _file_plan(user_message, intent)
    else:
        assessment = check_tool_permission("get_host_control_status", {}).risk_level
        steps = [
            _step(
                1,
                description="Inspect current system status before choosing a tool.",
                executor="system",
                action_type="status",
                parameters={},
                expected_result="System status is available.",
                risk_level=assessment,
                needs_approval=False,
                verification_method="output_nonempty",
            )
        ]

    return Plan(goal=user_message, intent=intent, steps=steps)


def _should_use_legacy_for_complex_task(lowered: str, route: IntentRoute) -> bool:
    if route.should_use_legacy_fallback or route.intent == "mixed":
        return True
    if route.intent == "code" and any(word in lowered for word in ("fix", "patch", "repair")):
        return True
    dynamic_report = any(word in lowered for word in ("latest", "news", "research", "search")) and any(
        word in lowered for word in ("save", "report", "summary", "summarize")
    )
    return dynamic_report


def build_execution_plan(user_message: str, route: IntentRoute) -> ExecutionPlan:
    """Compatibility planning surface for the structured command tests and local chat bridge."""
    lowered = user_message.strip().lower()
    if lowered.startswith("needs_clarification:"):
        return ExecutionPlan(
            goal=user_message,
            intent=route.intent,
            confidence=route.confidence,
            required_capabilities=list(route.required_capabilities),
            suggested_executor=route.suggested_executor,
            steps=[],
            supported=True,
            notes=[user_message],
        )
    if _should_use_legacy_for_complex_task(lowered, route):
        return ExecutionPlan(
            goal=user_message,
            intent=route.intent,
            confidence=route.confidence,
            required_capabilities=list(route.required_capabilities),
            suggested_executor=route.suggested_executor,
            steps=[],
            supported=False,
            notes=[
                "This request needs dynamic reasoning, credentials, source synthesis, or code repair; "
                "falling back to the legacy local chat loop for now."
            ],
        )

    intent_result = IntentResult(
        intent=Intent(route.intent),
        confidence=route.confidence,
        required_capabilities=list(route.required_capabilities),
        likely_risk=RiskLevel(route.likely_risk),
        suggested_executor=route.suggested_executor,
    )
    plan = create_plan(user_message, intent_result)
    notes: list[str] = []
    if _is_react_project_request(user_message) and not plan.steps:
        notes.append("needs_clarification: React project name and location are required before initialization.")
    if _is_calculator_page_request(user_message) and not plan.steps:
        notes.append("needs_clarification: A target project folder is required before editing calculator files.")
    converted_steps: list[PlanStep] = []
    for step in plan.steps:
        tool_name = step.tool_name
        if not tool_name:
            tool_name = {
                "open_app": "open_application",
                "type_text": "type_text",
                "write_file": "write_file",
                "delete_path": "delete_path",
                "open_path": "open_path",
                "list_tree": "list_directory_tree",
                "copy_path": "copy_path",
                "move_path": "move_path",
                "shell_command": "run_shell_command",
                "inspect_screen": "inspect_desktop_screen",
                "screenshot": "take_screenshot",
                "dynamic_desktop_task": "desktop_dynamic_loop",
                "dynamic_browser_task": "browser_dynamic_loop",
                "dynamic_search": "browser_dynamic_loop",
                "click_first_result": "browser_dynamic_loop",
                "browser_get_state": "browser_get_state",
                "verify_video_opened": "browser_get_state",
                "verify_result_opened": "browser_get_state",
                "open_url": "open_url",
                "start_screen_recording": "start_screen_recording",
                "stop_screen_recording": "stop_screen_recording",
                "analyze_screen_recording": "analyze_screen_recording",
                "check_project_path": "list_directory_tree",
                "verify_react_project": "run_shell_command",
                "browser_observe": "search_web",
                "browser_submit_form": "browser_submit_form",
                "status": "get_host_control_status",
            }.get(step.action_type, step.action_type)

        parameters = dict(step.parameters)
        if step.action_type == "write_file":
            path_value = str(parameters.get("path") or ("report.md" if "report" in lowered else "generated_by_friday.txt"))
            parameters = {
                "file_path": path_value,
                "content": parameters.get("content", ""),
            }
        verification_target = ""
        if step.action_type == "write_file":
            from friday.path_utils import resolve_user_path

            verification_target = str(resolve_user_path(str(parameters["file_path"])))
        elif step.action_type == "open_app":
            verification_target = str(parameters.get("app_name", ""))
        elif step.action_type in {"delete_path", "list_tree", "open_path"}:
            verification_target = str(parameters.get("path", ""))
        elif step.action_type in {"dynamic_browser_task", "dynamic_desktop_task", "dynamic_search", "click_first_result"}:
            verification_target = str(parameters.get("goal", user_message))
        elif step.action_type in {"check_project_path", "verify_react_project", "confirm_existing_project"}:
            verification_target = step.verification_target or str(parameters.get("project_path") or parameters.get("path") or "")
        elif step.action_type in {"open_url", "verify_video_opened", "verify_result_opened"}:
            verification_target = step.verification_target or str(parameters.get("url", ""))
        elif step.action_type in {"screenshot", "inspect_screen", "start_screen_recording", "stop_screen_recording", "analyze_screen_recording"}:
            verification_target = step.verification_target or step.action_type

        verification_method = step.verification_method
        if step.action_type == "shell_command":
            verification_method = "command_output_ok"

        converted_steps.append(
            PlanStep(
                id=step.id,
                description=step.description,
                executor=step.executor,
                action_type=step.action_type,
                tool_name=tool_name,
                parameters=parameters,
                expected_result=step.expected_result,
                risk_level=step.risk_level,
                needs_approval=step.needs_approval,
                verification_method=verification_method,
                verification_target=verification_target,
                fallback_strategy=step.fallback_strategy,
            )
        )

    return ExecutionPlan(
        goal=user_message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=list(route.required_capabilities),
        suggested_executor=route.suggested_executor,
        steps=converted_steps,
        notes=notes,
    )
