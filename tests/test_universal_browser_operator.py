from friday.browser.operator import BrowserOperator, build_element_map_from_html
from friday.core.planner import build_execution_plan
from friday.core.router import route_user_command


def test_browser_observation_parses_inputs_links_buttons():
    html = """
    <html>
      <title>Demo Search</title>
      <input type="search" placeholder="Search">
      <button>Submit</button>
      <a href="/watch?v=1">First video result</a>
    </html>
    """

    observation = build_element_map_from_html(html, url="https://example.test")

    roles = {element.role for element in observation.elements}
    labels = " ".join(element.label for element in observation.elements).lower()
    assert "searchbox" in roles
    assert "button" in roles
    assert "link" in roles
    assert "first video" in labels


def test_dynamic_target_ranking_prefers_searchbox():
    observation = build_element_map_from_html(
        "<input placeholder='Search videos'><button>Search</button><a href='/watch?v=1'>MKBHD review</a>",
        url="https://youtube.test",
    )
    operator = BrowserOperator()

    match = operator.find_element_by_goal("search input", observation)

    assert match is not None
    assert match.element.role == "searchbox"
    assert match.confidence >= 0.3


def test_first_video_detection_is_generic():
    observation = build_element_map_from_html(
        """
        <a href="/ads">Sponsored</a>
        <a href="/watch?v=abc">MKBHD first video</a>
        <a href="/watch?v=def">Another video</a>
        """,
        url="https://youtube.test/results",
    )
    operator = BrowserOperator()

    action = operator.decide_next_action("open youtube search MKBHD and open first video", observation)

    assert action.type == "click_element"
    assert action.element_id


def test_sensitive_browser_goal_requires_approval():
    observation = build_element_map_from_html(
        "<input type='password' placeholder='Password'><button>Sign in</button>",
        url="https://bank.example/login",
    )
    operator = BrowserOperator()

    action = operator.decide_next_action("open chrome and login to my bank", observation)
    decision = operator.permission_for_action(action, observation)

    assert decision["decision"] in {"ask", "block"}
    assert decision["risk_level"] >= 3


def test_browser_plan_uses_dynamic_operator_for_websites():
    route = route_user_command("open youtube and search MKBHD")
    plan = build_execution_plan("open youtube and search MKBHD", route)

    assert plan.supported is True
    assert plan.intent == "browser"
    assert any(step.action_type == "dynamic_browser_task" for step in plan.steps)
    dynamic_step = next(step for step in plan.steps if step.action_type == "dynamic_browser_task")
    assert dynamic_step.tool_name == "browser_dynamic_loop"
    assert "hardcoded" not in dynamic_step.description.lower()


def test_youtube_search_and_open_first_video_gets_end_to_end_plan():
    route = route_user_command("open youtube search MKBHD and open first video")
    plan = build_execution_plan("open youtube search MKBHD and open first video", route)

    assert plan.supported is True
    assert plan.intent == "browser"
    assert [step.action_type for step in plan.steps] == [
        "open_url",
        "dynamic_search",
        "click_first_result",
        "verify_video_opened",
    ]
    assert plan.steps[0].parameters["url"] == "https://www.youtube.com"
    assert plan.steps[1].tool_name == "browser_dynamic_loop"
    assert plan.steps[2].tool_name == "browser_dynamic_loop"
    assert plan.steps[3].tool_name == "browser_get_state"
