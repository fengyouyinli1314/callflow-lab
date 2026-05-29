from app.services.agents.evaluator_agent import EvaluatorAgent
from app.services.report_service import ReportService
from app.services.rule_judge import RuleJudge
from app.services.target_model_client import TargetModelClient


def _rules_text(rule_result):
    visible = rule_result["visible_business_rules"]
    return " ".join(
        rule_result.get("active_rule_names", [])
        + visible.get("matched", [])
        + visible.get("failed", [])
        + visible.get("pending", [])
        + visible.get("untriggered", [])
    )


def test_rider_rank_case_focus_matches_station_synonyms():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "质疑报名排名",
        "user_profile": "质疑规则骑手。",
        "initial_message": "为什么别人能报上，我排不上？",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "为什么别人能报上，我排不上？",
            "assistant_message": "名额按系统排名，非站长定；少拒单取消超时保资格。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)
    visible_text = _rules_text(result)

    assert result["case_focus"] == "ranking_question"
    assert "是否说明报名按排名进行" in result["matched_rules"]
    assert "是否说明不是站长干预" in result["matched_rules"]
    assert "是否提醒减少拒单取消超时有助于保住资格" in result["matched_rules"]
    assert "是否说明不是站长干预" not in result["failed_rules"]
    assert "是否避免承诺一定获得资格" in result["matched_rules"]
    assert "退出" not in visible_text
    assert "天气" not in visible_text
    assert "安全" not in visible_text
    assert "奖励" not in visible_text
    assert "订单号" not in visible_text
    assert "退款" not in visible_text


def test_rider_exit_case_focus_activates_only_exit_rules():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "询问如何退出飞毛腿",
        "user_profile": "信息咨询骑手。",
        "initial_message": "我想退出飞毛腿，怎么取消？",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "你还没说怎么退出飞毛腿。",
            "assistant_message": "前一天 Z 点前在 App 的飞毛腿报名中取消，次日生效。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)
    visible_text = _rules_text(result)

    assert result["case_focus"] == "exit_flying_leg"
    assert "是否说明前一天 Z 点前取消" in visible_text
    assert "是否说明在 App 的“飞毛腿报名”中取消" in visible_text
    assert "是否说明次日生效" in visible_text
    assert "是否避免编造其他退出方式" in visible_text
    assert "是否说明不是站长干预" not in visible_text
    assert "报名按排名" not in visible_text
    assert "天气" not in visible_text
    assert "奖励" not in visible_text


def test_rider_bad_weather_case_focus_activates_only_weather_rules():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "抱怨恶劣天气",
        "user_profile": "情绪不满骑手。",
        "initial_message": "今天下雨这么大，怎么还让我跑？",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "今天下雨这么大，怎么还让我跑？",
            "assistant_message": "理解，安全第一；雨天订单更多，完成也有助保持资格。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)
    visible_text = _rules_text(result)

    assert result["case_focus"] == "bad_weather"
    assert "是否先安抚" in visible_text
    assert "是否提醒安全" in visible_text
    assert "是否说明雨天订单更多或完成有助于资格" in visible_text
    assert "是否避免强迫冒险配送" in visible_text
    assert "退出" not in visible_text
    assert "报名按排名" not in visible_text
    assert "站长干预" not in visible_text
    assert "奖励" not in visible_text


def test_rider_unwilling_case_requires_faq_retention_and_reward():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "骑手不想干",
        "user_profile": "不想干的骑手。",
        "initial_message": "我今天不想干了，能不能不送？",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "我今天不想干了，能不能不送？",
            "assistant_message": "理解；许多骑手申请，跑不了名额可能被占。",
            "latency_ms": 120,
        },
        {
            "turn_index": 2,
            "user_message": "那不完成会影响什么？",
            "assistant_message": "单日合同当天X单，多日每天Y单，未完影响合同派单。",
            "latency_ms": 120,
        },
        {
            "turn_index": 3,
            "user_message": "连续跑完会有激励吗？",
            "assistant_message": "连续W天每天Y单，可获额外奖励，每单多+$。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)

    assert result["case_focus"] == "unwilling_delivery"
    assert "是否说明许多骑手正在申请且名额可能被占用" in result["matched_rules"]
    assert "是否说明单日/多日合同完成要求" in result["matched_rules"]
    assert "是否说明不完成可能影响合同或派单" in result["matched_rules"]
    assert "是否说明连续完成多日合同可能有额外奖励" in result["matched_rules"]


def test_rider_in_scope_contract_questions_do_not_trigger_out_of_scope_rule():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "飞毛腿骑手合同生效外呼用例",
        "user_profile": "飞毛腿骑手，已报名但不清楚合同生效后的配送要求。",
        "initial_message": "喂，哪位？我现在能接电话，你说吧。",
        "required_rules": ["必须说明合同已生效", "必须提醒完成配送任务", "必须说明任务要求", "必须遵守外呼约束"],
        "forbidden_rules": ["禁止承诺额外奖励", "禁止强迫配送", "禁止超出知识库答复"],
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "那个单日和多日分别要完成多少单？",
            "assistant_message": "单日完成 X 单，多日每天完成 Y 单。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)
    visible_text = _rules_text(result)

    assert "超范围问题是否说明向同事确认后再回电" not in visible_text
    assert "超出职责范围是否说明" not in visible_text
    assert "是否说明单日/多日合同完成要求" in visible_text
    assert "是否说明单日/多日合同完成要求" in result["matched_rules"]


def test_rider_recoverable_flow_rule_is_pending_then_late_satisfied():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "飞毛腿骑手合同生效外呼用例",
        "case_mode": "full_flow",
        "user_profile": "递进式综合骑手。",
        "initial_message": "是我，你说。",
    }
    first_messages = [
        {
            "turn_index": 0,
            "user_message": "",
            "assistant_message": "你好，请问是王师傅吗？我是美团外卖骑手的站长。",
            "latency_ms": 90,
        },
        {
            "turn_index": 1,
            "user_message": "是我，你说。",
            "assistant_message": "飞毛腿合同已生效，可以开始配送吗？",
            "latency_ms": 120,
        },
    ]

    turn_result = RuleJudge().score_turn(case, first_messages, 120, task)

    assert "是否说明单日/多日合同完成要求" not in turn_result["failed_rules"]
    assert "是否说明单日/多日合同完成要求" in turn_result["pending_rules"]
    assert "是否说明单日/多日合同完成要求" in turn_result["rule_lifecycle"]["pending"]

    final_messages = first_messages + [
        {
            "turn_index": 2,
            "user_message": "可以，我今天能跑。",
            "assistant_message": "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。",
            "latency_ms": 130,
        }
    ]
    final_result = RuleJudge().evaluate_conversation(task, case, final_messages)

    assert "是否说明单日/多日合同完成要求" in final_result["matched_rules"]
    assert "是否说明单日/多日合同完成要求" not in final_result["failed_rules"]
    assert "是否说明单日/多日合同完成要求" in final_result["late_satisfied_rules"]


def test_rider_real_out_of_scope_question_triggers_callback_rule():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "骑手超范围咨询",
        "user_profile": "咨询职责外问题骑手。",
        "initial_message": "那我工伤赔偿怎么算？",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "那我工伤赔偿怎么算？",
            "assistant_message": "我向同事确认后再回电给你。我现在能回答的先回答。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)

    assert "超范围问题是否说明向同事确认后再回电" in result["matched_rules"]


def test_course_owner_first_turn_does_not_activate_driver_coupon_or_wechat_rules():
    judge = RuleJudge()
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {
        "name": "课程直播产品升级外呼用例",
        "user_profile": "机构负责人，愿意了解。",
        "initial_message": "我是负责人，你说吧。",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "我是负责人，你说吧。",
            "assistant_message": "您是负责人就好，这次发布页升级，新增标准直播和低延迟直播，您看方便吗？",
            "latency_ms": 120,
        }
    ]

    result = judge.score_turn(case, messages, 120, task)
    active = judge.get_active_rules(task, case, messages)
    active_text = " ".join(active["case_rules"])
    scored_text = " ".join(result["matched_rules"] + result["failed_rules"])

    assert result["case_focus"] == "responsible_person"
    assert "是否识别负责人" in active_text
    assert "是否进入产品升级说明" in active_text
    assert "是否询问对方是否知道低延迟直播" not in scored_text
    assert "开车" not in active_text
    assert "优惠券" not in active_text
    assert "企业微信" not in active_text
    assert "结束确认" not in scored_text
    assert "优惠券" not in scored_text
    assert "企业微信" not in scored_text


def test_llm_evaluator_filters_failed_rules_outside_active_rules():
    fallback = {
        "task_completion": 80,
        "instruction_following": 80,
        "call_flow_coverage": 80,
        "constraint_compliance": 80,
        "context_consistency": 80,
        "response_quality": 80,
        "overall_reason": "fallback",
        "evidence": [],
        "suggestions": [],
        "knowledge_assessment": {},
        "retrieved_knowledge": [],
        "active_visible_rules": ["是否说明前一天 Z 点前取消"],
    }
    data = {
        "evidence": [
            {"turn_index": 1, "issue": "是否说明不是站长干预", "quote": "x", "deduction": "越界扣分"},
            {"turn_index": 1, "issue": "是否说明前一天 Z 点前取消", "quote": "y", "deduction": "允许扣分"},
        ],
        "failed_rules": ["是否说明不是站长干预", "是否说明前一天 Z 点前取消"],
    }

    normalized = EvaluatorAgent()._normalize_llm_result(data, fallback)
    report_filtered = ReportService(None)._filter_llm_result_to_active_rules(
        {"active_rule_names": ["是否说明前一天 Z 点前取消"]},
        normalized,
    )

    assert [item["issue"] for item in normalized["evidence"]] == ["是否说明前一天 Z 点前取消"]
    assert normalized["failed_rules"] == ["是否说明前一天 Z 点前取消"]
    assert [item["issue"] for item in report_filtered["evidence"]] == ["是否说明前一天 Z 点前取消"]


def test_course_live_difference_short_first_step_is_not_no_turn_violation():
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {
        "name": "直播区别触发验证",
        "user_profile": "反复追问商家。",
        "initial_message": "你直接说标准直播和低延迟直播的区别。",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "你直接说标准直播和低延迟直播的区别。",
            "assistant_message": "标准直播费用低，延迟5-10秒。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)

    assert result["case_focus"] == "live_type_difference"
    assert "是否回复简短自然" in result["matched_rules"]
    assert "是否说明标准直播延迟 5-10 秒、费用较低" in result["matched_rules"]
    assert "是否给商家发言机会" in result["matched_rules"]
    assert "禁止不给用户发言机会" not in " ".join(result["failed_rules"] + result["violated_rules"])
    visible_text = _rules_text(result)
    assert "企业微信" not in visible_text
    assert "结束确认" not in visible_text
    assert "优惠券" not in visible_text
    assert "配置路径" not in visible_text


def test_course_live_difference_combined_reply_is_not_multiple_failures():
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {
        "name": "直播区别触发验证",
        "user_profile": "反复追问商家。",
        "initial_message": "标准直播和低延迟直播有什么区别？",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "标准直播和低延迟直播有什么区别？",
            "assistant_message": "标准直播延迟5-10秒，费用低；低延迟直播1-2秒，互动更流畅。",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)

    assert "是否说明标准直播延迟 5-10 秒、费用较低" in result["matched_rules"]
    assert "是否说明低延迟直播延迟 1-2 秒、互动更流畅" in result["matched_rules"]
    assert "是否给商家发言机会" in result["matched_rules"]
    assert "禁止不给用户发言机会" not in " ".join(result["failed_rules"] + result["violated_rules"])
    assert len(result["failed_rules"]) <= 1


def test_course_publish_method_question_gives_user_turn():
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {
        "name": "发布方式追问",
        "user_profile": "机构商家。",
        "initial_message": "怎么确认发布方式？",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "怎么确认发布方式？",
            "assistant_message": "您用 Web 控制台还是第三方系统发课？",
            "latency_ms": 120,
        }
    ]

    result = RuleJudge().score_turn(case, messages, 120, task)

    assert "是否询问当前发布方式" in result["matched_rules"]
    assert "是否给商家发言机会" in result["matched_rules"]
    assert "禁止不给用户发言机会" not in " ".join(result["failed_rules"] + result["violated_rules"])


def test_course_target_prompt_emphasizes_short_stepwise_replies():
    client = TargetModelClient(provider="mock_fallback")
    messages = client._messages(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "直播区别触发验证", "initial_message": "标准直播和低延迟直播有什么区别？"},
        [{"turn_index": 1, "user_message": "标准直播和低延迟直播有什么区别？"}],
        [],
        {
            "scope": "run",
            "flow_memory": {"current_stage": "live_difference", "pending_steps": ["说明价格差异"]},
            "unfinished_items_memory": {"next_suggested_step": "说明价格差异"},
        },
    )
    system_prompt = messages[0]["content"]
    task_context = messages[1]["content"]

    assert "每次最多 15-20 个中文字符左右" in system_prompt
    assert "每次只说一个信息点" in system_prompt
    assert "说完必须停下来等商家回应" in system_prompt
    assert "memory_state 是本次评测 run 内的上下文状态" in system_prompt
    assert "说明价格差异" in task_context
    assert "那我稍后再打。" in system_prompt
    assert "就1分钟，保证简短。" in system_prompt


def test_course_mock_live_difference_reply_is_split_into_first_step():
    client = TargetModelClient(provider="mock_fallback")
    result = client.generate_reply(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "直播区别触发验证", "initial_message": "标准直播和低延迟直播有什么区别？"},
        "你直接说标准直播和低延迟直播的区别。",
        [],
    )

    assert result.content == "标准直播费用低，延迟5-10秒。"


def test_course_external_reply_repaired_when_non_driver_says_call_later():
    client = TargetModelClient(provider="mock_fallback")
    client._provider_reply = lambda *args, **kwargs: "好的，那我稍后再打。"

    result = client.generate_reply(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "课程直播产品升级外呼用例", "initial_message": "我是负责人，你说吧。", "case_mode": "full_flow"},
        "我是负责人，你说吧。",
        [{"turn_index": 0, "user_message": "", "assistant_message": "您好，请问您是负责人吗？"}],
    )

    assert result.content == "直播产品升级了，新增低延迟直播选项。"
    assert "好的" not in result.content
    assert "稍后再打" not in result.content
    assert result.should_close is False


def test_course_external_reply_repaired_when_skipping_upgrade_to_publish_method():
    client = TargetModelClient(provider="mock_fallback")
    client._provider_reply = lambda *args, **kwargs: "Web、校务A还是SaaS B？"

    result = client.generate_reply(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "课程直播产品升级外呼用例", "initial_message": "我是负责人，你说吧。", "case_mode": "full_flow"},
        "你先说升级了什么。",
        [
            {"turn_index": 0, "user_message": "", "assistant_message": "您好，请问您是负责人吗？"},
            {"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "之前后台走低延迟，您知道吗？"},
        ],
    )

    assert result.content == "发布页新增了独立的低延迟直播选项。"


def test_course_external_compliant_reply_is_not_templated():
    client = TargetModelClient(provider="mock_fallback")
    client._provider_reply = lambda *args, **kwargs: "标准更便宜，低延迟略高。"

    result = client.generate_reply(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "课程直播产品升级外呼用例", "initial_message": "我是负责人，你说吧。", "case_mode": "full_flow"},
        "费用会不会更高？",
        [
            {"turn_index": 0, "user_message": "", "assistant_message": "您好，请问您是负责人吗？"},
            {"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "直播产品升级，新增低延迟直播。"},
            {"turn_index": 2, "user_message": "不知道。", "assistant_message": "前端没开放，先保障音画同步。"},
            {"turn_index": 3, "user_message": "你先说升级了什么。", "assistant_message": "发布页分标准直播和低延迟直播。"},
        ],
    )

    assert result.content == "标准更便宜，低延迟略高。"
    assert result.fallback_used is False


def test_course_external_long_reply_is_kept_for_interruption_scoring():
    long_reply = "标准直播费用较低，延迟大约5到10秒，低延迟直播延迟约1到2秒，互动更流畅，适合小班课和实操课。"
    client = TargetModelClient(provider="mock_fallback")
    client._provider_reply = lambda *args, **kwargs: long_reply

    result = client.generate_reply(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "课程直播产品升级外呼用例", "initial_message": "我是负责人，你说吧。", "case_mode": "full_flow"},
        "区别是什么？",
        [
            {"turn_index": 0, "user_message": "", "assistant_message": "您好，请问您是负责人吗？"},
            {"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "直播产品升级，新增低延迟直播。"},
            {"turn_index": 2, "user_message": "不知道。", "assistant_message": "前端没开放，先保障音画同步。"},
            {"turn_index": 3, "user_message": "你先说升级了什么。", "assistant_message": "发布页分标准直播和低延迟直播。"},
        ],
    )

    assert result.content == long_reply
    assert result.fallback_used is False


def test_course_driver_external_reply_keeps_call_later_close():
    client = TargetModelClient(provider="mock_fallback")
    client._provider_reply = lambda *args, **kwargs: "那我稍后再打。"

    result = client.generate_reply(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "课程直播产品升级外呼用例", "initial_message": "我是负责人，你说吧。", "case_mode": "full_flow"},
        "我在开车，不方便说。",
        [],
    )

    assert result.content == "那我稍后再打。"
    assert result.should_close is True
