from app.services.rule_judge import RuleJudge


RIDER_TASK = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
COURSE_TASK = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}


def test_gold_excellent_rider_full_flow_scores_at_least_85():
    case = {
        "name": "飞毛腿骑手完整流程",
        "case_mode": "full_flow",
        "user_profile": "愿意配合的骑手",
        "initial_message": "是我，你说。",
    }
    messages = [
        {"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅本人吗？我是飞毛腿站长。"},
        {"turn_index": 1, "user_message": "是我，你说。", "assistant_message": "飞毛腿合同已生效，可以开始配送吗？"},
        {"turn_index": 2, "user_message": "可以，今天能跑。", "assistant_message": "午晚上线，单日X单，多日每天Y单，未完影响合同派单。"},
        {"turn_index": 3, "user_message": "名额和排名站长能调吗？", "assistant_message": "按系统排名，非站长干预；少拒单取消超时保资格。"},
        {"turn_index": 4, "user_message": "明白，我会按要求跑。", "assistant_message": "好的，注意安全，后续有问题再联系。"},
    ]

    result = RuleJudge().evaluate_conversation(RIDER_TASK, case, messages)

    assert result["score"] >= 85
    assert not result["failed_rules"]
    assert "全流程覆盖：说明排名与保资格规则" in result["matched_rules"]
    assert "全流程覆盖：结束确认" in result["matched_rules"]


def test_gold_severe_cross_task_transcript_scores_at_most_40():
    case = {"name": "严重串场", "initial_message": "喂。"}
    messages = [
        {
            "turn_index": 1,
            "user_message": "我不是负责人但很忙，你们课程直播升级了什么？",
            "assistant_message": "飞毛腿骑手合同已生效，今天配送 X 单。",
            "rule_score": 5,
        },
        {
            "turn_index": 2,
            "user_message": "标准直播和低延迟有什么区别？",
            "assistant_message": "骑手必须按派单配送。",
            "rule_score": 5,
        },
        {
            "turn_index": 3,
            "user_message": "在哪里配置？有没有优惠券？企业微信怎么加？",
            "assistant_message": "合同 Y 单完不成影响资格，减少拒单取消超时。",
            "rule_score": 5,
        },
        {
            "turn_index": 4,
            "user_message": "我在开车，别说了。",
            "assistant_message": "飞毛腿派单规则我继续给你讲，必须听完。",
            "rule_score": 5,
        },
    ]

    result = RuleJudge().evaluate_conversation(COURSE_TASK, case, messages)

    assert result["score"] <= 40
    assert "禁止串用飞毛腿场景" in result["hidden_guardrail_rules"]["violated"]
    assert "是否说“那我稍后再打”" in result["failed_rules"]
    assert result["metrics"]["low_turn_count"] == 4


def test_gold_answered_question_but_missed_flow_scores_between_60_and_75():
    case = {
        "name": "课程直播产品升级外呼用例",
        "case_mode": "full_flow",
        "user_profile": "机构负责人",
        "initial_message": "我是负责人，你说吧。",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "我是负责人，你说吧。",
            "assistant_message": "直播产品升级，新增标准直播和低延迟直播两个选项。",
            "rule_score": 65,
        },
        {
            "turn_index": 2,
            "user_message": "标准直播和低延迟有什么区别？",
            "assistant_message": "标准直播延迟5-10秒，费用较低；低延迟直播1-2秒，互动更流畅。",
            "rule_score": 55,
        },
    ]

    result = RuleJudge().evaluate_conversation(COURSE_TASK, case, messages)

    assert 60 <= result["score"] <= 75
    assert "是否说明标准直播延迟 5-10 秒、费用较低" in result["matched_rules"]
    assert "是否说明低延迟直播延迟 1-2 秒、互动更流畅" in result["matched_rules"]
    assert "是否说明配置路径" in result["pending_rules"]
    assert "全流程覆盖：企业微信添加" in result["pending_rules"]


def test_gold_driving_user_still_gets_sales_pitch_is_heavily_penalized():
    case = {"name": "商家说在开车", "initial_message": "我在开车，先别说了。"}
    messages = [
        {
            "turn_index": 1,
            "user_message": "我在开车，先别说了。",
            "assistant_message": "直播发布页升级了，新增标准直播和低延迟直播，您先听我介绍配置和费用。",
        }
    ]

    result = RuleJudge().evaluate_conversation(COURSE_TASK, case, messages)

    assert result["score"] < 70
    assert "是否说“那我稍后再打”" in result["failed_rules"]
    assert "是否立即结束" in result["failed_rules"]
    assert "是否不继续推销" in result["failed_rules"]


def test_gold_owner_first_turn_keeps_fee_and_wechat_pending_not_failed():
    case = {
        "name": "课程直播产品升级外呼用例",
        "case_mode": "full_flow",
        "user_profile": "机构负责人",
        "initial_message": "我是负责人，你说吧。",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "我是负责人，你说吧。",
            "assistant_message": "直播产品升级，新增标准直播和低延迟直播两个选项。",
        }
    ]

    result = RuleJudge().score_turn(case, messages, 100, COURSE_TASK)

    deferred_rules = [
        "是否说明低延迟可能费用更高",
        "是否禁止承诺优惠券或折扣",
        "是否说明企业微信添加逻辑",
    ]
    for rule in deferred_rules:
        assert rule in result["pending_rules"]
        assert rule not in result["failed_rules"]


def test_gold_rule_trace_activation_reason_uses_user_facing_labels():
    case = {
        "name": "飞毛腿骑手完整流程",
        "case_mode": "full_flow",
        "user_profile": "愿意配合的骑手",
        "initial_message": "是我，你说。",
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "是我，你说。",
            "assistant_message": "飞毛腿合同已生效，可以开始配送吗？",
        }
    ]

    result = RuleJudge().score_turn(case, messages, 100, RIDER_TASK)
    trace_rows = result["rule_trace"]["rows"]
    reasons = " ".join(row["activation_reason"] for row in trace_rows)

    assert "完整流程覆盖用例" in reasons
    assert "骑手正常配送主流程" in reasons
    assert "full_flow" not in reasons
    assert "normal_delivery" not in reasons


def test_gold_rule_trace_does_not_duplicate_completed_full_flow_rules():
    case = {
        "name": "飞毛腿骑手完整流程",
        "case_mode": "full_flow",
        "user_profile": "愿意配合的骑手",
        "initial_message": "是我，你说。",
    }
    messages = [
        {"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅吗？我是站长。"},
        {"turn_index": 1, "user_message": "是我，你说。", "assistant_message": "飞毛腿合同已生效，可以开始配送吗？"},
        {"turn_index": 2, "user_message": "可以，今天我会跑。", "assistant_message": "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。"},
        {"turn_index": 3, "user_message": "行，我尽量完成。", "assistant_message": "好的，尽量完成，注意安全；恶劣天气订单量更高，有助保资格。"},
        {"turn_index": 4, "user_message": "名额按系统排还是站长排？", "assistant_message": "名额按系统排名，非站长定；少拒单取消超时保资格。"},
        {"turn_index": 5, "user_message": "连续完成有没有额外奖励？", "assistant_message": "连续W天每天Y单，可获额外奖励，每单多+$。"},
        {"turn_index": 6, "user_message": "行，我今天按规则跑。", "assistant_message": "好的，后续有问题再联系。"},
    ]

    result = RuleJudge().evaluate_conversation(RIDER_TASK, case, messages)
    trace_rows = {row["rule_name"]: row for row in result["rule_trace"]["rows"]}

    completed_aliases = [
        "是否确认骑手身份",
        "是否告知飞毛腿合同已生效",
        "是否告知飞毛腿合同已签署并生效",
        "是否告知飞毛腿合同已经签署并生效",
        "是否告知飞毛腿合同已经署并生效",
        "是否询问是否可以开始配送",
        "是否说明单日/多日合同完成要求",
        "是否说明不完成可能影响合同或派单",
        "是否说明雨天订单更多或完成有助于资格",
    ]
    for rule in completed_aliases:
        assert rule not in result["untriggered_rules"]
        if rule in trace_rows:
            assert trace_rows[rule]["status"] != "untriggered"

    for rule in ["禁止机械重复回复", "禁止编造职责外信息"]:
        assert trace_rows[rule]["status"] == "passed"
        assert trace_rows[rule]["deduction_reason"] == "已检查，未发现违规，不扣分。"

    assert "禁止串用课程直播场景" not in trace_rows


def test_gold_course_full_flow_trace_hides_completed_alias_rules():
    case = {
        "name": "课程直播产品升级外呼用例",
        "case_mode": "full_flow",
        "user_profile": "机构负责人",
        "initial_message": "我是负责人，你说吧。",
    }
    messages = [
        {"turn_index": 0, "user_message": "", "assistant_message": "您好，请问您是负责人吗？"},
        {"turn_index": 1, "user_message": "我是负责人，你说吧。", "assistant_message": "直播产品升级了，新增低延迟直播选项。"},
        {"turn_index": 2, "user_message": "具体升级了什么？", "assistant_message": "发布页以后分标准和低延迟两个选项。"},
        {"turn_index": 3, "user_message": "那我要怎么用？", "assistant_message": "发课时选低延迟即可。"},
        {"turn_index": 4, "user_message": "其他流程变不变？", "assistant_message": "其他流程不变。"},
        {"turn_index": 5, "user_message": "嗯，知道了。", "assistant_message": "后台已走低延迟，您知道吗？"},
        {"turn_index": 6, "user_message": "不知道。", "assistant_message": "前端当时未开放，临时开低延迟是保障音画同步。"},
        {"turn_index": 7, "user_message": "标准和低延迟区别在哪？", "assistant_message": "标准直播费用低，延迟5-10秒。"},
        {"turn_index": 8, "user_message": "标准适合什么课？", "assistant_message": "适合大班课。"},
        {"turn_index": 9, "user_message": "那低延迟具体强在哪？", "assistant_message": "低延迟1-2秒，互动更流畅。"},
        {"turn_index": 10, "user_message": "低延迟适合哪类课？", "assistant_message": "适合小班和实操课。"},
        {"turn_index": 11, "user_message": "低延迟价格会贵吗？", "assistant_message": "低延迟费用略高。"},
        {"turn_index": 12, "user_message": "这个跟我发课入口有关吗？", "assistant_message": "你是通过Web还是第三方发布？"},
        {"turn_index": 13, "user_message": "SaaS系统B。", "assistant_message": "低延迟已显示吗？"},
        {"turn_index": 14, "user_message": "没显示。", "assistant_message": "进【我的】。"},
        {"turn_index": 15, "user_message": "我进去了，继续说。", "assistant_message": "点服务商/直播平台管理。"},
        {"turn_index": 16, "user_message": "收到，继续。", "assistant_message": "选择【直播平台】。"},
        {"turn_index": 17, "user_message": "可以，继续。", "assistant_message": "在服务产品下勾选低延迟并保存。"},
        {"turn_index": 18, "user_message": "行，费用这块明白了。", "assistant_message": "还有其他问题吗？"},
        {"turn_index": 19, "user_message": "学员端费用也要看吗？", "assistant_message": "学员端有附加费吗？"},
        {"turn_index": 20, "user_message": "已设置费用。", "assistant_message": "低延迟也要适用该费用。"},
        {"turn_index": 21, "user_message": "后续怎么联系？", "assistant_message": "当前号码能加吗？"},
        {"turn_index": 22, "user_message": "当前号码能加。", "assistant_message": "企业微信加您，请通过验证。"},
        {"turn_index": 23, "user_message": "清楚了，先这样。", "assistant_message": "祝课程顺利，招生满满。"},
    ]

    result = RuleJudge().evaluate_conversation(COURSE_TASK, case, messages)
    trace_rows = {row["rule_name"]: row for row in result["rule_trace"]["rows"]}

    assert result["score"] >= 85
    assert not result["failed_rules"]

    completed_aliases = [
        "是否说明低延迟直播适合实时互动",
        "是否询问发布方式",
        "是否根据 Web 控制台 / 第三方系统给出不同引导",
        "是否说明费用差异或低延迟可能费用更高",
        "是否给商家发言机会",
        "是否询问对方是否知道低延迟直播",
        "是否说明发布页分开显示标准直播和低延迟直播",
        "是否说明标准直播和低延迟直播区别",
        "是否说明配置路径",
        "是否说明低延迟可能费用更高",
        "是否询问当前发布方式",
        "是否询问 Web 控制台 / 校务系统A / SaaS系统B",
        "是否在结束前确认是否还有问题",
        "是否说明企业微信添加逻辑",
        "不能不给商家发言机会",
    ]
    for rule in completed_aliases:
        assert rule not in result["untriggered_rules"]
        if rule in trace_rows:
            assert trace_rows[rule]["status"] != "untriggered"

    metric_by_key = {item["metric_key"]: item for item in result["metric_explanations"]}
    assert metric_by_key["task_completion"]["evidence_turns"] == [23]
    assert metric_by_key["call_flow_coverage"]["evidence_turns"] == [23]
    assert metric_by_key["constraint_compliance"]["evidence_turns"] == []
    assert "未发现禁止规则或后台护栏违规" in metric_by_key["constraint_compliance"]["evidence_text"]
    assert all(len(item["evidence_turns"]) <= 1 for item in result["metric_explanations"])
    assert result["evidence_messages"]
    assert all(row["related_rules"] for row in result["evidence_messages"])
