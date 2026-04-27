from friday.core.operator_loop import OperatorLoop, OperatorLoopConfig


def test_operator_loop_observe_act_verify_cycle():
    calls = {"observed": 0, "executed": 0}

    def observe():
        calls["observed"] += 1
        return {"state": "ready", "elements": []}

    def decide(_observation, steps):
        if steps:
            return {"type": "complete", "message": "done"}
        return {"type": "click", "target": "ok"}

    def permission(_action):
        return {"decision": "allow", "reason": "ok"}

    def execute(_action):
        calls["executed"] += 1
        return {"ok": True, "message": "clicked"}

    def verify(_observation, _action, _result):
        return {"success": True, "goal_completed": False, "reason": "progress"}

    def recover(_observation, _action, _result):
        return {"retryable": False, "reason": "not needed"}

    result = OperatorLoop(config=OperatorLoopConfig(max_steps=3)).run(
        observe=observe,
        decide=decide,
        permission=permission,
        execute=execute,
        verify=verify,
        recover=recover,
    )

    assert result.completed is True
    assert calls["observed"] == 2
    assert calls["executed"] == 1


def test_operator_loop_stops_on_permission_request():
    result = OperatorLoop(config=OperatorLoopConfig(max_steps=2)).run(
        observe=lambda: {"elements": []},
        decide=lambda _observation, _steps: {"type": "submit_form"},
        permission=lambda _action: {"decision": "ask", "reason": "approval required"},
        execute=lambda _action: {"ok": True},
        verify=lambda _observation, _action, _result: {"success": True},
        recover=lambda _observation, _action, _result: {"retryable": False},
    )

    assert result.completed is False
    assert result.status == "approval_required"
