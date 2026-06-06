from app.services.memory_service import load_memory, reset_memory_for_new_run, update_after_model, update_after_user


def _first_case(client):
    task = client.get("/api/tasks").json()[0]
    case = client.get(f"/api/cases?task_id={task['id']}").json()[0]
    return task, case


def _task_case_by_type(client, task_type):
    tasks = client.get("/api/tasks").json()
    task = next((item for item in tasks if item.get("task_type") == task_type), tasks[0])
    case = client.get(f"/api/cases?task_id={task['id']}").json()[0]
    return task, case


def test_start_evaluation_and_get_messages(client):
    task, case = _first_case(client)
    response = client.post("/api/runs/start", json={"task_id": task["id"], "case_id": case["id"]})
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["run_id"] > 0
    assert result["report_id"] > 0
    assert result["total_score"] > 0
    assert result["provider_requested"] == "mock_fallback"
    assert result["provider_used"] == "mock_fallback"
    assert result["fallback_used"] is False
    run_response = client.get(f"/api/runs/{result['run_id']}")
    assert run_response.status_code == 200
    run_memory = run_response.json()["memory_state"]
    assert {
        "flow_memory",
        "user_branch_memory",
        "model_performance_memory",
        "unfinished_memory",
        "conversation_memory",
        "run_context",
    }.issubset(set(run_memory))
    assert "interaction_memory" in run_memory
    assert run_memory["run_context"]["run_seed"] == result["run_id"]
    assert isinstance(run_memory["run_context"]["variant_id"], int)
    assert run_memory["flow_memory"]["current_stage"]
    assert isinstance(run_memory["model_performance_memory"]["interrupted_count"], int)
    assert "current_step" in run_memory["interaction_memory"]
    assert "user_event" in run_memory["interaction_memory"]

    messages = client.get(f"/api/runs/{result['run_id']}/messages")
    assert messages.status_code == 200
    # Opening Line tasks store the model opening as turn 0, so total messages
    # can be one more than the configured business max_turns.
    assert 1 <= len(messages.json()) <= case["max_turns"] + 1


def test_quick_check_manual_user_messages(client):
    task, case = _task_case_by_type(client, "rider_outbound")
    response = client.post(
        "/api/runs/quick-check",
        json={
            "task_id": task["id"],
            "case_id": case["id"],
            "model_provider": "mock_fallback",
            "user_messages": ["我想退出飞毛腿"],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["provider_used"] == "mock_fallback"
    assert result["total_score"] == 100
    assert len(result["turns"]) == 1
    assert result["turns"][-1]["assistant_message"]
    assert result["turns"][-1]["rule_score"] == 100
    assert "说明前一天 Z 点前取消" in result["turns"][-1]["matched_rules"]
    assert "说明在 App 的飞毛腿报名中取消" in result["turns"][-1]["matched_rules"]
    assert "说明次日生效" in result["turns"][-1]["matched_rules"]
    assert "run_id" not in result
    assert "report_id" not in result


def test_quick_check_rider_driving_stops_delivery_push(client):
    task, case = _task_case_by_type(client, "rider_outbound")
    response = client.post(
        "/api/runs/quick-check",
        json={
            "task_id": task["id"],
            "case_id": case["id"],
            "model_provider": "mock_fallback",
            "user_messages": ["我在开车"],
        },
    )

    assert response.status_code == 200
    result = response.json()
    turn = result["turns"][-1]
    assert "稍后再打" in turn["assistant_message"]
    assert turn["rule_score"] == 100
    assert "说明稍后再联系" in turn["matched_rules"]
    assert "不继续推进配送" in turn["matched_rules"]
    assert not turn["missed_rules"]


def test_quick_check_rider_benefit_answers_directly(client):
    task, case = _task_case_by_type(client, "rider_outbound")
    response = client.post(
        "/api/runs/quick-check",
        json={
            "task_id": task["id"],
            "case_id": case["id"],
            "model_provider": "mock_fallback",
            "user_messages": ["飞毛腿有什么好处"],
        },
    )

    assert response.status_code == 200
    result = response.json()
    turn = result["turns"][-1]
    assert "保资格" in turn["assistant_message"]
    assert "额外奖励" in turn["assistant_message"]
    assert "合同已生效" not in turn["assistant_message"]
    assert turn["rule_score"] == 100
    assert "说明完成有助保资格" in turn["matched_rules"]
    assert "不回到主流程开场" in turn["matched_rules"]


def test_memory_service_returns_fresh_initial_state():
    first = reset_memory_for_new_run({"name": "task"}, {"required_rules": ["规则A"]})
    second = reset_memory_for_new_run({"name": "task"}, {"required_rules": ["规则A"]})

    first["flow_memory"]["completed_stages"].append("污染")
    first["unfinished_memory"]["required_rules_pending"].append("规则B")

    assert second["flow_memory"]["current_stage"] == "start"
    assert second["flow_memory"]["completed_stages"] == []
    assert second["unfinished_memory"]["required_rules_pending"] == ["规则A"]


def test_load_memory_falls_back_to_default_on_empty():
    class Run:
        memory_state = None

    memory = load_memory(Run())

    assert memory["flow_memory"]["current_stage"] == "start"
    assert memory["conversation_memory"]["short_summary"] == ""


def test_memory_updates_after_user_driving():
    memory = reset_memory_for_new_run({"name": "task"}, {"required_rules": ["说明升级"]})

    updated = update_after_user(
        memory,
        "我在开车，不方便说。",
        {"intent": "开车不方便沟通", "should_continue": True},
    )

    assert updated["user_branch_memory"]["is_driving"] is True
    assert updated["conversation_memory"]["last_user_intent"] == "开车不方便沟通"
    assert updated["unfinished_memory"]["next_best_action"] == "礼貌说明稍后再打并结束"


def test_memory_updates_after_model_judge_result():
    memory = reset_memory_for_new_run({"name": "task"}, {"required_rules": ["说明升级", "询问发布方式"]})
    memory = update_after_user(memory, "费用会不会更高？", {})

    updated = update_after_model(
        memory,
        "直播产品升级，新增低延迟直播。",
        {
            "current_stage": "upgrade_intro",
            "matched_rules": ["说明升级"],
            "missed_rules": ["询问发布方式"],
            "violated_rules": ["禁止承诺优惠"],
            "is_too_long": True,
            "answered_user_question": False,
            "is_off_topic": True,
            "is_repetitive": True,
        },
    )

    assert updated["flow_memory"]["current_stage"] == "upgrade_intro"
    assert "说明升级" in updated["unfinished_memory"]["required_rules_done"]
    assert "询问发布方式" in updated["unfinished_memory"]["required_rules_pending"]
    assert "禁止承诺优惠" in updated["unfinished_memory"]["forbidden_rules_hit"]
    assert updated["model_performance_memory"]["too_verbose_count"] == 1
    assert updated["model_performance_memory"]["unanswered_question_count"] == 1
    assert updated["model_performance_memory"]["off_topic_count"] == 1
    assert updated["model_performance_memory"]["repeat_count"] == 1
    assert updated["model_performance_memory"]["constraint_violation_count"] == 1
