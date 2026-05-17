from app.services.dialogue_state import is_similar_text
from app.services.agents.user_simulator_agent import UserSimulatorAgent


RIDER_TASK = "飞毛腿骑手合同生效外呼评测"
COURSE_TASK = "课程直播产品升级外呼评测"


def _find_task(client, task_name):
    tasks = client.get("/api/tasks").json()
    task = next((item for item in tasks if item["name"] == task_name), None)
    assert task, f"task not found: {task_name}"
    return task


def _find_case(client, task_id, case_name):
    cases = client.get(f"/api/cases?task_id={task_id}").json()
    case = next((item for item in cases if item["name"] == case_name), None)
    assert case, f"case not found: {case_name}"
    return case


def _run_case(client, task_name, case_name):
    task = _find_task(client, task_name)
    case = _find_case(client, task["id"], case_name)
    response = client.post("/api/runs/start", json={"task_id": task["id"], "case_id": case["id"]})
    assert response.status_code == 200, response.text
    result = response.json()
    messages_response = client.get(f"/api/runs/{result['run_id']}/messages")
    assert messages_response.status_code == 200
    messages = messages_response.json()
    assert messages
    return task, case, result, messages


def _assert_no_adjacent_repeats(messages, key):
    values = [item[key] for item in messages if item.get(key)]
    for previous, current in zip(values, values[1:]):
        assert not is_similar_text(current, previous), values


def _joined(messages, key):
    return "\n".join(item.get(key, "") for item in messages)


def test_rider_contract_impact_dialogue_does_not_repeat(client):
    _, _, result, messages = _run_case(client, RIDER_TASK, "询问合同影响")

    assert result["task_type"] == "rider_outbound"
    _assert_no_adjacent_repeats(messages, "assistant_message")
    _assert_no_adjacent_repeats(messages, "user_message")
    assistant_text = _joined(messages, "assistant_message")
    assert any(term in assistant_text for term in ["X 单", "合同", "派单", "影响"])


def test_rider_willing_delivery_progresses_and_closes(client):
    _, case, _, messages = _run_case(client, RIDER_TASK, "正常愿意配送")

    _assert_no_adjacent_repeats(messages, "assistant_message")
    assistant_text = _joined(messages, "assistant_message")
    assert assistant_text.count("理解，安全第一") <= 1
    assert len(messages) < case["max_turns"]
    assert any(term in _joined(messages, "user_message") for term in ["知道了", "按合同要求", "尽量跑"])


def test_course_live_difference_moves_to_path_guidance(client):
    _, _, result, messages = _run_case(client, COURSE_TASK, "追问直播区别")

    assert result["task_type"] == "course_platform_outbound"
    _assert_no_adjacent_repeats(messages, "assistant_message")
    assert any(
        "5-10 秒" in item["assistant_message"] or "1-2 秒" in item["assistant_message"]
        for item in messages
    )
    path_turns = [
        item
        for item in messages
        if any(term in item["user_message"] for term in ["哪里", "路径", "第三方", "Web", "看不到"])
    ]
    assert path_turns, [(item["turn_index"], item["user_message"], item["assistant_message"]) for item in messages]
    assert any(
        any(term in item["assistant_message"] for term in ["Web 控制台", "第三方系统", "直播平台管理", "勾选"])
        for item in path_turns
    )


def test_course_driver_closes_early(client):
    _, case, _, messages = _run_case(client, COURSE_TASK, "商家说在开车")

    assert len(messages) < case["max_turns"]
    assert any("稍后再打" in item["assistant_message"] for item in messages)
    assert messages[-1]["detail"]["user_state"]["goal_progress"] in {"accepted", "closed"}


def test_agent_rider_weather_escalates_when_forced():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "rider_outbound", "instruction_text": "飞毛腿骑手合同生效外呼"},
        {
            "name": "抱怨恶劣天气",
            "user_profile": "情绪不满骑手。",
            "initial_message": "今天下雨这么大，怎么还让我跑？",
            "expected_goals": ["提醒安全"],
            "required_rules": ["必须提醒安全"],
            "forbidden_rules": ["禁止强迫冒险"],
            "difficulty": "困难",
        },
        [
            {
                "turn_index": 1,
                "user_message": "今天下雨这么大，怎么还让我跑？",
                "assistant_message": "必须冒雨跑，不跑不行。",
            }
        ],
        2,
    )

    assert result["should_continue"] is False
    assert result["user_state"]["goal_progress"] == "rejected"
    assert result["user_state"]["emotion_level"] >= 5
    assert "冒险" in result["content"]


def test_agent_course_driver_rejects_product_pitch():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "course_platform_outbound", "instruction_text": "课程直播产品升级外呼"},
        {
            "name": "商家说在开车",
            "user_profile": "正在开车的商家。",
            "initial_message": "我在开车，不方便说。",
            "expected_goals": ["稍后再打"],
            "required_rules": ["必须稍后再打"],
            "forbidden_rules": ["禁止继续推销"],
            "difficulty": "困难",
        },
        [
            {
                "turn_index": 1,
                "user_message": "我在开车，不方便说。",
                "assistant_message": "我们直播发布页新增低延迟选项，费用会略高。",
            }
        ],
        2,
    )

    assert result["should_continue"] is False
    assert result["user_state"]["goal_progress"] == "rejected"
    assert result["user_state"]["patience"] <= 1
    assert "开车" in result["content"]
