"""Short-term task context for contextual follow-up commands."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


CONTEXT_TTL_SECONDS = 15 * 60


@dataclass
class TaskContext:
    last_user_goal: str = ""
    resolved_goal: str = ""
    current_task_status: str = ""
    last_intent: str = ""
    last_app: str = ""
    last_folder_path: str = ""
    last_file_path: str = ""
    last_project_path: str = ""
    last_browser_url: str = ""
    last_browser_title: str = ""
    last_search_query: str = ""
    last_site: str = ""
    last_visible_page_state: str = ""
    last_plan: dict[str, Any] = field(default_factory=dict)
    last_unfinished_goal: str = ""
    last_successful_step: str = ""
    remaining_steps: list[str] = field(default_factory=list)
    last_shell_command: str = ""
    last_shell_output: str = ""
    last_error: str = ""
    last_screenshot_path: str = ""
    last_selected_target: str = ""
    last_approval_request: dict[str, Any] = field(default_factory=dict)
    last_created_artifact: str = ""
    last_visible_elements: list[dict[str, Any]] = field(default_factory=list)
    last_active_window: str = ""
    current_browser_page: dict[str, Any] = field(default_factory=dict)
    last_artifacts: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["age_seconds"] = max(0.0, time.time() - self.updated_at) if self.updated_at else None
        return data


_CONTEXT = TaskContext()


def get_task_context() -> TaskContext:
    if _CONTEXT.updated_at and time.time() - _CONTEXT.updated_at > CONTEXT_TTL_SECONDS:
        reset_task_context()
    return _CONTEXT


def reset_task_context() -> None:
    global _CONTEXT
    _CONTEXT = TaskContext()


def update_task_context(**fields: Any) -> TaskContext:
    context = get_task_context()
    for key, value in fields.items():
        if hasattr(context, key) and value not in (None, ""):
            setattr(context, key, value)
    context.updated_at = time.time()
    return context


def _site_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "youtube." in host or host == "youtu.be":
        return "youtube"
    if "google." in host:
        return "google"
    if "github." in host:
        return "github"
    return host.split(".")[-2] if "." in host else host


def _query_from_url(url: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query)
    for key in ("search_query", "q", "query"):
        if values.get(key):
            return str(values[key][0]).strip()
    return ""


def remember_browser_shortcut(
    *,
    url: str,
    site: str = "",
    search_query: str = "",
    page_title: str = "",
    visible_page_state: str = "",
    unfinished_goal: str = "",
) -> TaskContext:
    resolved_site = site or _site_from_url(url)
    resolved_query = search_query or _query_from_url(url)
    return update_task_context(
        last_user_goal=unfinished_goal,
        last_intent="browser",
        last_browser_url=url,
        last_browser_title=page_title or ("YouTube search results" if resolved_site == "youtube" else ""),
        last_search_query=resolved_query,
        last_site=resolved_site,
        last_visible_page_state=visible_page_state,
        last_unfinished_goal=unfinished_goal,
        current_browser_page={"url": url, "title": page_title, "site": resolved_site, "query": resolved_query},
    )


def remember_plan_context(
    plan: Any,
    *,
    visible_page_state: str = "",
    artifacts: dict[str, Any] | None = None,
    result: Any | None = None,
) -> TaskContext:
    plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan or {})
    intent = str(plan_dict.get("intent") or "")
    steps = list(plan_dict.get("steps") or [])
    goal = str(plan_dict.get("goal") or "")
    browser_url = ""
    browser_goal = ""
    app_name = ""
    folder_path = ""
    file_path = ""
    project_path = ""
    successful_step = ""
    shell_command = ""
    for step in steps:
        params = dict(step.get("parameters") or {})
        browser_url = str(params.get("url") or browser_url)
        browser_goal = str(params.get("goal") or browser_goal)
        app_name = str(params.get("app_name") or app_name)
        folder_path = str(params.get("path") or folder_path)
        file_path = str(params.get("file_path") or params.get("path") or file_path)
        project_path = str(params.get("project_path") or project_path)
        shell_command = str(params.get("command") or shell_command)
        successful_step = str(step.get("id") or successful_step)

    site = _site_from_url(browser_url) if browser_url else ""
    query = _query_from_url(browser_url) if browser_url else ""
    if not query and browser_goal:
        query = _extract_search_query_text(browser_goal)

    unfinished_goal = ""
    if intent == "browser" and _looks_like_search_results_goal(browser_goal or str(plan_dict.get("goal", ""))):
        unfinished_goal = "open first video" if (site == "youtube" or "youtube" in browser_goal.lower()) else "open first result"

    task_status = str(getattr(result, "task_status", "") or "")
    completed_steps = list(getattr(result, "completed_steps", []) or [])
    remaining_steps = list(getattr(result, "remaining_steps", []) or [])
    approval_requests = list(getattr(result, "approval_requests", []) or [])
    step_results = list(getattr(result, "step_results", []) or [])
    last_output = ""
    last_error = ""
    for step_result in step_results:
        output = str(getattr(step_result, "output", "") or "")
        error = str(getattr(step_result, "error", "") or "")
        if output:
            last_output = output
        if error:
            last_error = error

    created_artifact = str((artifacts or {}).get("artifact_path") or "")
    screenshot_path = str((artifacts or {}).get("screenshot_path") or "")
    for value in (last_output, last_error, visible_page_state):
        extracted = _extract_artifact_path(value)
        if extracted:
            created_artifact = created_artifact or extracted
            if extracted.lower().endswith((".png", ".jpg", ".jpeg")):
                screenshot_path = screenshot_path or extracted

    return update_task_context(
        last_user_goal=goal,
        resolved_goal=goal,
        current_task_status=task_status,
        last_intent=intent,
        last_app=app_name,
        last_folder_path=folder_path,
        last_file_path=file_path,
        last_project_path=project_path or str((artifacts or {}).get("react_project_path") or ""),
        last_browser_url=browser_url,
        last_search_query=query,
        last_site=site,
        last_visible_page_state=visible_page_state,
        last_plan=plan_dict,
        last_unfinished_goal=unfinished_goal,
        last_successful_step=str(completed_steps[-1]) if completed_steps else successful_step,
        remaining_steps=remaining_steps,
        last_shell_command=shell_command,
        last_shell_output=last_output,
        last_error=last_error,
        last_screenshot_path=screenshot_path,
        last_approval_request=approval_requests[0] if approval_requests else {},
        last_created_artifact=created_artifact,
        last_artifacts=artifacts or {},
    )


def _extract_artifact_path(text: str) -> str:
    import re

    match = re.search(r"([A-Za-z]:\\[^\s]+|/[^\s]+?\.(?:png|jpg|jpeg|mp4|webm|txt|json|md))", str(text or ""))
    return match.group(1).strip(".,;") if match else ""


def _extract_search_query_text(text: str) -> str:
    lowered = " ".join(text.strip().split())
    for marker in ("search for ", "search youtube for ", "search google for "):
        index = lowered.lower().find(marker)
        if index >= 0:
            return lowered[index + len(marker) :].strip(" .,:;")
    return ""


def _looks_like_search_results_goal(text: str) -> bool:
    lowered = text.lower()
    return "search" in lowered and not _wants_first_result_click(lowered)


def _wants_first_result_click(text: str) -> bool:
    lowered = text.lower()
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


def is_contextual_follow_up(message: str) -> bool:
    lowered = " ".join(message.strip().lower().split())
    if not lowered:
        return False
    if _wants_first_result_click(lowered):
        return True
    return lowered in {
        "open it",
        "click it",
        "do that",
        "continue",
        "go ahead",
        "open that",
        "click that",
        "delete it",
        "delete that",
        "rename it",
        "rename that",
        "move it there",
        "try again",
        "fix this",
        "fix it",
        "save it",
    }


def _clarify_reference(action: str, candidates: list[tuple[str, str]]) -> str:
    labels = [label for label, value in candidates if value]
    if not labels:
        return f"needs_clarification: I need to know what '{action}' refers to."
    if len(labels) == 1:
        return ""
    return "needs_clarification: Do you mean " + ", ".join(labels[:-1]) + f", or {labels[-1]}?"


def _reference_candidates(current: TaskContext) -> list[tuple[str, str]]:
    return [
        ("the current folder", current.last_folder_path),
        ("the last file", current.last_file_path),
        ("the current browser page", current.last_browser_url),
        ("the active app/window", current.last_app or current.last_active_window),
        ("the last created artifact", current.last_created_artifact),
    ]


def contextualize_user_message(message: str, context: TaskContext | None = None) -> str:
    current = context or get_task_context()
    lowered_message = message.lower()
    project_hint = current.last_project_path or str(current.last_artifacts.get("react_project_path") or "")
    if "react" in lowered_message and "project" in lowered_message and any(marker in lowered_message for marker in ("initialize", "initialise", "create", "setup", "set up")):
        if project_hint and " name " not in lowered_message and "named" not in lowered_message and "called" not in lowered_message:
            project_name = Path(project_hint).name
            parent_name = Path(project_hint).parent.name or "Documents"
            if project_name:
                return f"{message} in {parent_name} in the name {project_name}"
    if any(marker in lowered_message for marker in ("calculator webpage", "calculator page")) and project_hint and " at " not in lowered_message and " in project" not in lowered_message:
        return f"{message} in the project at {project_hint}"
    if lowered_message in {"run it", "run that", "now run it"} and project_hint:
        return f"run the project at {project_hint}"
    if lowered_message in {"build it", "now build it", "build that"} and project_hint:
        return f"run build for the project at {project_hint}"
    if lowered_message in {"fix it", "fix that error", "fix that", "fix this"}:
        if project_hint and (current.last_error or current.last_shell_output):
            return f"fix the current error in the project at {project_hint}"
        if current.last_screenshot_path:
            return f"analyze this error from screenshot {current.last_screenshot_path}"
        return "needs_clarification: I need the error text, file, or screenshot before I can fix it."
    if lowered_message in {"open it", "open that"}:
        clarification = _clarify_reference("open it", _reference_candidates(current))
        if clarification:
            return clarification
        if current.last_folder_path:
            return f"open {current.last_folder_path} in file explorer"
        if current.last_file_path:
            return f"open {current.last_file_path}"
        if current.last_browser_url:
            return f"open {current.last_browser_url}"
        if current.last_app:
            return f"open {current.last_app}"
        if current.last_created_artifact:
            return f"open {current.last_created_artifact}"
    if lowered_message in {"delete it", "delete that", "rename it", "rename that", "move it there"}:
        file_candidates = [
            ("the last file", current.last_file_path),
            ("the current folder", current.last_folder_path),
            ("the last created artifact", current.last_created_artifact),
        ]
        clarification = _clarify_reference(lowered_message, file_candidates)
        if clarification:
            return clarification
        target = current.last_file_path or current.last_created_artifact or current.last_folder_path
        if not target:
            return f"needs_clarification: I need to know what '{lowered_message}' refers to."
        if lowered_message.startswith("delete"):
            return f"delete {target}"
        if lowered_message.startswith("rename"):
            return f"rename {target}"
        return f"move {target}"
    if lowered_message in {"continue", "do that", "do the same"}:
        if current.last_unfinished_goal:
            return current.last_unfinished_goal
        if current.remaining_steps and current.last_user_goal:
            return f"continue: {current.last_user_goal}"
        if current.last_user_goal:
            return f"continue: {current.last_user_goal}"
    if lowered_message == "try again" and current.last_user_goal:
        return current.last_user_goal
    if not is_contextual_follow_up(message):
        return message
    if current.last_intent != "browser" and not current.last_browser_url and not current.last_site:
        return message

    site_label = current.last_site.title() if current.last_site else "browser"
    page = f"current {site_label} page"
    if current.last_search_query:
        page = f"current {site_label} search results page for '{current.last_search_query}'"

    lowered = message.lower()
    target = "video result" if "video" in lowered or current.last_site == "youtube" else "result"
    if "first" in lowered or "1st" in lowered or "only click" in lowered:
        return f"On the {page}, click the first {target}."
    if current.last_unfinished_goal:
        return f"On the {page}, {current.last_unfinished_goal}."
    return f"On the {page}, continue the previous browser task."
