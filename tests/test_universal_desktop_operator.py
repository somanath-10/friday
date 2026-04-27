from friday.core.planner import build_execution_plan
from friday.core.router import route_user_command
from friday.desktop.operator import DesktopOperator, build_control_map


def test_desktop_control_map_detects_notepad_editable_control():
    observation = build_control_map(
        [
            {"control_id": "title", "role": "Text", "name": "Untitled - Notepad"},
            {"control_id": "editor", "role": "Edit", "name": "Text Editor", "enabled": True, "focused": True},
        ],
        active_app="notepad",
        active_window="Untitled - Notepad",
    )
    operator = DesktopOperator()

    action = operator.decide_next_action("open notepad and type meeting notes", observation)

    assert action["type"] == "type_text"
    assert action["element_id"] == "editor"
    assert action["text"] == "meeting notes"


def test_desktop_target_ranking_detects_calculator_buttons():
    observation = build_control_map(
        [
            {"control_id": "num5", "role": "Button", "name": "Five"},
            {"control_id": "plus", "role": "Button", "name": "Plus"},
            {"control_id": "equals", "role": "Button", "name": "Equals"},
        ],
        active_app="calculator",
        active_window="Calculator",
    )
    operator = DesktopOperator()

    plus = operator.find_control_by_goal("plus", observation, {"preferred_roles": {"button"}})
    equals = operator.find_control_by_goal("equals", observation, {"preferred_roles": {"button"}})

    assert plus is not None
    assert plus.element.element_id == "plus"
    assert equals is not None
    assert equals.element.element_id == "equals"


def test_desktop_plan_uses_dynamic_step_for_typing():
    route = route_user_command("open notepad and type meeting notes")
    plan = build_execution_plan("open notepad and type meeting notes", route)

    assert plan.supported is True
    assert plan.steps[0].tool_name == "open_application"
    assert plan.steps[1].action_type == "dynamic_desktop_task"
    assert plan.steps[1].tool_name == "desktop_dynamic_loop"
    assert plan.steps[1].parameters["text"] == "meeting notes"


def test_close_notepad_requires_approval_plan():
    route = route_user_command("close notepad")
    plan = build_execution_plan("close notepad", route)

    assert plan.intent == "desktop"
    assert plan.steps[0].action_type == "close_app"
    assert plan.steps[0].needs_approval is True
