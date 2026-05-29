from app.services.dialogue_state import is_similar_text
from app.services.agents.user_simulator_agent import UserSimulatorAgent
from app.services.target_model_client import TargetModelClient


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


def _business_messages(messages):
    return [item for item in messages if item.get("turn_index") != 0]


def test_rider_full_flow_progresses_through_recursive_call_flow(client):
    _, case, result, messages = _run_case(client, RIDER_TASK, "飞毛腿骑手合同生效外呼用例")

    assert result["task_type"] == "rider_outbound"
    assert case["case_mode"] == "full_flow"
    assert case["initial_message"] == "是我，你说。"
    assert case["max_turns"] >= 10
    assert messages[0]["turn_index"] == 0
    assert "王师傅" in messages[0]["assistant_message"]
    assert "美团外卖骑手的站长" in messages[0]["assistant_message"]
    assert messages[1]["user_message"] == "是我，你说。"
    _assert_no_adjacent_repeats(messages, "assistant_message")
    _assert_no_adjacent_repeats(messages, "user_message")
    assistant_text = _joined(messages, "assistant_message")
    user_text = _joined(messages, "user_message")
    assert len(messages) >= 6
    assert any(term in assistant_text for term in ["合同已签署", "合同已生效"])
    assert "开始配送" in assistant_text
    assert any(term in assistant_text for term in ["午晚高峰", "午餐", "晚餐", "高峰"])
    assert any(term in assistant_text for term in ["X 单", "X单"])
    assert any(term in assistant_text for term in ["Y 单", "Y单"])
    assert any(term in assistant_text for term in ["少拒单", "少取消", "别超时"])
    assert "注意安全" in assistant_text
    assert any(term in user_text for term in ["名额", "资格", "站长"])
    assert any(term in assistant_text for term in ["按系统排名", "按排名"])
    assert any(term in assistant_text for term in ["不是站长人工干预", "不是站长", "非站长"])
    assert any(term in assistant_text for term in ["资格", "名额"])
    stop_decision = messages[-1]["detail"]["stop_decision"]
    assert stop_decision["case_mode"] == "full_flow"
    assert stop_decision["full_flow_status"]["complete"] is True


def test_course_live_difference_uses_split_short_replies(client):
    _, _, result, messages = _run_case(client, COURSE_TASK, "课程直播产品升级外呼用例")

    assert result["task_type"] == "course_platform_outbound"
    _assert_no_adjacent_repeats(messages, "assistant_message")
    assert messages[0]["turn_index"] == 0
    assert messages[0]["detail"]["message_phase"] == "opening"
    assert messages[0]["detail"]["memory_state"]["scope"] == "run"
    assert messages[0]["detail"]["memory_state"]["updated_at_turn"] == 0
    assert "负责人" in messages[0]["assistant_message"]
    assistant_replies = [item["assistant_message"] for item in _business_messages(messages)]
    standard_reply_index = next(index for index, reply in enumerate(assistant_replies) if "5-10秒" in reply)
    low_latency_reply_index = next(index for index, reply in enumerate(assistant_replies) if "1-2秒" in reply)
    assert standard_reply_index < low_latency_reply_index
    assert "1-2秒" not in assistant_replies[standard_reply_index]
    assert all(len("".join(reply.split())) <= 22 for reply in assistant_replies)
    user_text = _joined(messages, "user_message")
    assert "区别" in user_text
    assert any(term in user_text for term in ["低延迟呢", "低延迟具体", "低延迟适合", "低延迟用在", "低延迟差"])


def test_course_owner_full_flow_does_not_stop_after_opening(client):
    _, case, result, messages = _run_case(client, COURSE_TASK, "课程直播产品升级外呼用例")

    assert result["task_type"] == "course_platform_outbound"
    assert case["case_mode"] == "full_flow"
    assert messages[0]["turn_index"] == 0
    assert messages[0]["detail"]["message_phase"] == "opening"
    assert "负责人" in messages[0]["assistant_message"]
    assert "是否没有串场" not in messages[0]["matched_rules"]
    assert "是否没有串场" in messages[0]["detail"]["hidden_guardrail_rules"]["matched"]
    assert messages[0]["detail"]["deduction_reason"] == ""
    assert messages[1]["user_message"] == "我是负责人，你说吧。"
    assert messages[1]["assistant_message"] == "直播产品升级了，新增低延迟直播选项。"
    assert any("独立的低延迟直播选项" in item["assistant_message"] for item in messages)
    assert messages[1]["detail"]["memory_state"]["run_id"] == result["run_id"]
    assert messages[1]["detail"]["memory_state"]["flow_memory"]["pending_steps"]
    assert case["max_turns"] >= 12
    assert case["expected_steps"] == [
        "身份确认",
        "确认是否知情",
        "传达升级内容",
        "说明标准直播和低延迟直播区别",
        "说明价格差异",
        "询问发布方式",
        "确认前端是否可见并说明配置路径",
        "检查学员端费用/加速线路费",
        "企业微信添加",
        "结束确认",
    ]
    assert len(messages) >= 10
    assistant_text = _joined(messages, "assistant_message")
    user_text = _joined(messages, "user_message")
    assert any(term in assistant_text for term in ["独立的低延迟直播选项", "发布页", "新增", "两个选项"])
    assert "我之前不知道" in user_text
    assert any(term in user_text for term in ["怎么用", "怎么操作"])
    assert any(term in user_text for term in ["流程会变吗", "流程会改", "流程变不变"])
    assert "不知道。" in user_text
    assert "我之前选标准直播" not in user_text
    assert "5-10秒" in assistant_text
    assert "1-2秒" in assistant_text
    assert any(term in assistant_text for term in ["Web", "校务A", "SaaS"])
    assert any(term in assistant_text for term in ["进【我的】", "直播平台管理", "勾选"])
    assert any(term in assistant_text for term in ["学员端", "低延迟费用", "加速费", "费用略高"])
    assert "企业微信" in assistant_text
    assert any(term in assistant_text for term in ["后续", "没问题", "祝课程顺利"])
    stop_decision = messages[-1]["detail"]["stop_decision"]
    assert stop_decision["case_mode"] == "full_flow"
    assert stop_decision["full_flow_status"]["complete"] is True
    assert stop_decision["full_flow_status"]["coverage_ratio"] >= 0.7
    final_memory = messages[-1]["detail"]["memory_state"]
    assert final_memory["scope"] == "run"
    assert final_memory["unfinished_items_memory"]["required_pending"] == []
    assert "主流程关键项已覆盖" in final_memory["summary"] or final_memory["unfinished_items_memory"]["required_pending"] == []


def test_course_driver_closes_early(client):
    task = _find_task(client, COURSE_TASK)
    case = _find_case(client, task["id"], "课程直播产品升级外呼用例")
    result = TargetModelClient(provider="mock_fallback").generate_reply(
        task,
        case,
        "我在开车，不方便说。",
        [],
    )
    assert result.content == "那我稍后再打。"
    assert result.should_close is True


def test_course_full_flow_user_simulator_uses_branch_answers():
    agent = UserSimulatorAgent()
    case = {
        "name": "课程直播产品升级外呼用例",
        "case_mode": "full_flow",
        "user_profile": "机构负责人，已知情，Web 控制台，已显示，未设置费用，不可添加。",
        "initial_message": "我是负责人，你说吧。",
    }

    assert agent._course_branch_answer(case, "awareness") == "知道。"
    assert agent._course_branch_answer(case, "publish_method") == "Web控制台。"
    assert agent._course_branch_answer(case, "visibility") == "已显示。"
    assert agent._course_branch_answer(case, "fee") == "没设置费用。"
    assert agent._course_branch_answer(case, "wechat") == "这个号加不了。"


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


def test_agent_rider_initial_response_uses_case_initial_message():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "rider_outbound", "instruction_text": "飞毛腿骑手合同生效外呼"},
        {
            "name": "询问如何退出飞毛腿",
            "user_profile": "信息咨询骑手。",
            "initial_message": "我想退出飞毛腿，怎么取消？",
            "case_mode": "branch",
        },
        [{"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅吗？我是站长。"}],
        1,
    )

    assert result["content"] == "我想退出飞毛腿，怎么取消？"
    assert result["should_continue"] is True


def test_agent_rider_full_flow_prompts_rank_rule_after_safety():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "rider_outbound", "instruction_text": "飞毛腿骑手合同生效外呼"},
        {
            "name": "飞毛腿骑手合同生效外呼用例",
            "user_profile": "递进式综合骑手。",
            "initial_message": "是我，你说。",
            "case_mode": "full_flow",
            "expected_steps": [
                "确认身份",
                "告知今天飞毛腿合同已生效",
                "说明午晚高峰和单量要求",
                "询问是否可以开始配送",
                "根据骑手态度鼓励挽留或安抚",
                "提醒注意安全",
                "说明排名与保资格规则",
                "结束确认",
            ],
        },
        [
            {"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅吗？我是美团外卖骑手的站长。"},
            {"turn_index": 1, "user_message": "是我，你说。", "assistant_message": "飞毛腿合同已生效，可以开始配送吗？"},
            {"turn_index": 2, "user_message": "可以，我今天能跑。", "assistant_message": "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。"},
            {"turn_index": 3, "user_message": "我能跑，你简单鼓励下就行。", "assistant_message": "好的，尽量完成，注意安全。"},
        ],
        4,
    )

    assert result["should_continue"] is True
    assert any(term in result["content"] for term in ["名额", "资格", "站长"])
    assert result["user_state"]["goal_progress"] == "in_progress"


def test_agent_rider_full_flow_does_not_prompt_exit_or_reward_as_required_steps():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "rider_outbound", "instruction_text": "飞毛腿骑手合同生效外呼"},
        {
            "name": "飞毛腿骑手合同生效外呼用例",
            "user_profile": "递进式综合骑手。",
            "initial_message": "是我，你说。",
            "case_mode": "full_flow",
        },
        [
            {"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅吗？我是美团外卖骑手的站长。"},
            {"turn_index": 1, "user_message": "是我，你说。", "assistant_message": "飞毛腿合同已生效，可以开始配送吗？"},
            {"turn_index": 2, "user_message": "可以，我今天能跑。", "assistant_message": "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。"},
            {"turn_index": 3, "user_message": "我能跑，你简单鼓励下就行。", "assistant_message": "好的，尽量完成，注意安全。"},
        ],
        4,
    )

    assert result["should_continue"] is True
    assert all(term not in result["content"] for term in ["退出", "取消", "奖励", "激励", "W 天"])
    assert any(term in result["content"] for term in ["名额", "资格", "站长"])
    assert result["user_state"]["goal_progress"] == "in_progress"


def test_agent_uses_run_variant_for_user_question_wording():
    agent = UserSimulatorAgent()
    task = {"task_type": "rider_outbound", "instruction_text": "飞毛腿骑手合同生效外呼"}
    case = {
        "name": "飞毛腿骑手合同生效外呼用例",
        "user_profile": "递进式综合骑手。",
        "initial_message": "是我，你说。",
        "case_mode": "full_flow",
        "expected_steps": [
            "确认身份",
            "告知今天飞毛腿合同已生效",
            "说明午晚高峰和单量要求",
            "询问是否可以开始配送",
            "根据骑手态度鼓励挽留或安抚",
            "提醒注意安全",
            "说明排名与保资格规则",
            "结束确认",
        ],
    }
    history = [
        {"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅吗？我是美团外卖骑手的站长。"},
        {"turn_index": 1, "user_message": "是我，你说。", "assistant_message": "飞毛腿合同已生效，可以开始配送吗？"},
        {"turn_index": 2, "user_message": "可以，我今天能跑。", "assistant_message": "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。"},
        {"turn_index": 3, "user_message": "我能跑，你简单鼓励下就行。", "assistant_message": "好的，尽量完成，注意安全。"},
    ]

    first = agent.generate_message(task, case, history, 4, memory_state={"run_context": {"variant_id": 0}})
    second = agent.generate_message(task, case, history, 4, memory_state={"run_context": {"variant_id": 1}})

    assert first["content"] != second["content"]
    assert any(term in first["content"] for term in ["名额", "资格", "站长"])
    assert any(term in second["content"] for term in ["名额", "资格", "站长"])


def test_agent_rider_full_flow_uses_single_case_optional_faq_branch():
    agent = UserSimulatorAgent()
    task = {"task_type": "rider_outbound", "instruction_text": "飞毛腿骑手合同生效外呼"}
    case = {
        "name": "飞毛腿骑手合同生效外呼用例",
        "user_profile": "递进式综合骑手。",
        "initial_message": "是我，你说。",
        "case_mode": "full_flow",
        "expected_steps": [
            "确认身份",
            "告知今天飞毛腿合同已生效",
            "说明午晚高峰和单量要求",
            "询问是否可以开始配送",
            "根据骑手态度鼓励挽留或安抚",
            "提醒注意安全",
            "说明排名与保资格规则",
            "结束确认",
        ],
    }
    history = [
        {"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅吗？我是美团外卖骑手的站长。"},
        {"turn_index": 1, "user_message": "是我，你说。", "assistant_message": "飞毛腿合同已生效，可以开始配送吗？"},
        {"turn_index": 2, "user_message": "可以，我今天能跑。", "assistant_message": "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。"},
        {"turn_index": 3, "user_message": "好，我今天按要求跑。", "assistant_message": "好的，跑单注意安全。"},
        {"turn_index": 4, "user_message": "那飞毛腿名额是你们站长定的吗？", "assistant_message": "名额按系统排名，非站长定；少拒单取消超时保资格。"},
    ]

    reward = agent.generate_message(task, case, history, 5, memory_state={"run_context": {"variant_id": 1}})
    exit_flow = agent.generate_message(task, case, history, 5, memory_state={"run_context": {"variant_id": 2}})

    assert "激励" in reward["content"] or "奖励" in reward["content"]
    assert reward["should_continue"] is True
    assert "取消" in exit_flow["content"] or "退" in exit_flow["content"]
    assert exit_flow["should_continue"] is True


def test_agent_course_driver_rejects_product_pitch():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "course_platform_outbound", "instruction_text": "课程直播产品升级外呼"},
        {
            "name": "开车优先中断验证",
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


def test_agent_uses_memory_for_busy_interruption():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "course_platform_outbound", "instruction_text": "课程直播产品升级外呼"},
        {
            "name": "忙碌记忆验证",
            "user_profile": "课程机构负责人，刚说自己很忙。",
            "initial_message": "我是负责人，你说吧。",
            "case_mode": "full_flow",
        },
        [
            {"turn_index": 1, "user_message": "我现在很忙。", "assistant_message": "标准直播延迟大约5到10秒，低延迟延迟大约1到2秒，互动更流畅，适合小班实操课程。"},
        ],
        2,
        memory_state={
            "user_branch_memory": {"is_busy": True},
            "model_performance_memory": {"too_verbose_count": 1},
            "unfinished_memory": {"required_rules_pending": ["传达升级内容"], "next_best_action": "传达升级内容"},
        },
    )

    assert result["content"] == "你说重点，我没时间。"
    assert result["metadata"]["intent"] == "忙碌后打断"
    assert result["metadata"]["should_continue"] is True


def test_agent_uses_memory_for_driving_stop():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "course_platform_outbound", "instruction_text": "课程直播产品升级外呼"},
        {
            "name": "开车记忆验证",
            "user_profile": "课程机构负责人，正在开车。",
            "initial_message": "我在开车，不方便说。",
        },
        [
            {"turn_index": 1, "user_message": "我在开车，不方便说。", "assistant_message": "发布页新增低延迟直播选项，费用略高。"},
        ],
        2,
        memory_state={"user_branch_memory": {"is_driving": True}},
    )

    assert result["should_continue"] is False
    assert result["metadata"]["intent"] == "开车后拒绝继续沟通"
    assert "先不说" in result["content"]


def test_agent_uses_unfinished_memory_next_action():
    agent = UserSimulatorAgent()
    result = agent.generate_message(
        {"task_type": "course_platform_outbound", "instruction_text": "课程直播产品升级外呼"},
        {
            "name": "未完成事项记忆验证",
            "user_profile": "课程机构负责人。",
            "initial_message": "我是负责人，你说吧。",
        },
        [
            {"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "直播产品升级，新增低延迟直播。"},
        ],
        2,
        memory_state={
            "flow_memory": {"pending_stages": ["询问发布方式"]},
            "unfinished_memory": {"required_rules_pending": ["询问发布方式"], "next_best_action": "询问发布方式"},
        },
    )

    assert result["content"] == "这个跟我现在发布方式有关系吗？"
    assert result["metadata"]["branch_update"] == {}


def test_course_user_event_is_seeded_and_metadata_exposed():
    agent = UserSimulatorAgent()
    case = {
        "id": 1001,
        "name": "反复追问商家",
        "user_profile": "反复追问商家，被打断后继续追问商家。",
        "initial_message": "我是负责人，你说吧。",
        "case_mode": "full_flow",
    }
    memory = {
        "run_context": {"run_seed": 17},
        "flow_memory": {"current_stage": "live_difference"},
    }

    first = agent.generate_message(
        {"task_type": "course_platform_outbound", "instruction_text": "课程直播产品升级外呼"},
        case,
        [{"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "发布页新增低延迟直播选项。"}],
        3,
        memory_state=memory,
    )
    second = agent.generate_message(
        {"task_type": "course_platform_outbound", "instruction_text": "课程直播产品升级外呼"},
        case,
        [{"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "发布页新增低延迟直播选项。"}],
        3,
        memory_state=memory,
    )

    assert first["content"] == second["content"]
    assert first["metadata"]["user_event"] == second["metadata"]["user_event"]
    assert first["metadata"]["current_step"] == "difference_explain"
    assert "下一步" not in first["content"]
    assert "Step" not in first["content"]


def test_course_mock_handles_busy_driving_and_interrupts():
    client = TargetModelClient(provider="mock_fallback")
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {"name": "课程直播产品升级外呼用例", "initial_message": "我是负责人，你说吧。", "case_mode": "full_flow"}

    busy = client.generate_reply(task, case, "我现在很忙。", [], memory_state={})
    driving = client.generate_reply(task, case, "我在开车，不方便说。", [], memory_state={})
    interrupt = client.generate_reply(
        task,
        case,
        "等等，低延迟是啥？",
        [{"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "发布页新增低延迟直播选项。"}],
        memory_state={"interaction_memory": {"interrupted": True, "pending_return_step": "option_intro"}},
    )

    assert busy.content == "就1分钟，保证简短。"
    assert driving.content == "那我稍后再打。"
    assert driving.should_close is True
    assert interrupt.content == "就是互动更顺。"


def test_course_mock_guides_third_party_configuration_step_by_step():
    client = TargetModelClient(provider="mock_fallback")
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {"name": "技术不熟悉商家", "initial_message": "我是负责人，你说吧。", "case_mode": "full_flow"}
    history = [
        {"turn_index": 1, "user_message": "第三方系统看不到是哪一步？", "assistant_message": "先进入【我的】。"},
        {"turn_index": 2, "user_message": "到了，继续。", "assistant_message": "点直播平台管理。"},
        {"turn_index": 3, "user_message": "到了，继续。", "assistant_message": "选择【直播平台】。"},
    ]

    first = client.generate_reply(task, case, "第三方系统看不到是哪一步？", [], memory_state={})
    second = client.generate_reply(task, case, "到了，继续。", history[:1], memory_state={})
    third = client.generate_reply(task, case, "到了，继续。", history[:2], memory_state={})
    fourth = client.generate_reply(task, case, "到了，继续。", history, memory_state={})

    assert first.content == "先进入【我的】。"
    assert second.content == "点直播平台管理。"
    assert third.content == "选择【直播平台】。"
    assert fourth.content == "勾选低延迟并保存。"
