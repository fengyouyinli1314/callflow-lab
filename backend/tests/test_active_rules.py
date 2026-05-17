from app.services.rule_judge import RuleJudge


def test_rider_exit_case_activates_only_exit_related_rules():
    task = {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"}
    case = {
        "name": "询问如何退出飞毛腿",
        "user_profile": "骑手想取消飞毛腿报名。",
        "initial_message": "我想退出飞毛腿，怎么取消？",
        "required_rules": ["是否正确说明退出飞毛腿流程", "是否说明需提前在 App 飞毛腿报名中取消"],
        "forbidden_rules": ["禁止编造站长手动取消", "禁止串用旧业务场景"],
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "我想退出飞毛腿，怎么取消？",
            "assistant_message": "需前一天 Z 点前在 App 报名页取消。",
            "latency_ms": 150,
        }
    ]

    active = RuleJudge().get_active_rules(task, case, messages)
    active_text = " ".join(
        active["global_rules"] + active["case_rules"] + active["triggered_rules"]
    )
    inactive_text = " ".join(active["not_applicable_rules"])

    assert "退出飞毛腿流程" in active_text
    assert "App 飞毛腿报名" in active_text
    assert "回复简短自然" in active_text
    assert "串用旧业务场景" in active_text
    assert "提醒安全" not in active_text
    assert "报名排名" not in active_text
    assert "开始配送" not in active_text
    assert "单日/多日合同完成要求" not in active_text
    assert "提醒安全" in inactive_text
    assert "报名排名" in inactive_text


def test_rider_exit_report_does_not_penalize_untriggered_task_rules(client):
    tasks = client.get("/api/tasks").json()
    rider_task = next(task for task in tasks if task.get("task_type") == "rider_outbound")
    case_payload = {
        "task_id": rider_task["id"],
        "name": "询问如何退出飞毛腿",
        "user_profile": "骑手只想知道如何退出飞毛腿报名。",
        "initial_message": "我想退出飞毛腿，怎么取消？",
        "max_turns": 1,
        "expected_goals": ["正确说明退出流程"],
        "required_rules": ["是否正确说明退出飞毛腿流程", "是否说明需提前在 App 飞毛腿报名中取消"],
        "forbidden_rules": ["禁止编造站长手动取消", "禁止串用旧业务场景"],
        "difficulty": "中等",
    }
    case = client.post("/api/cases", json=case_payload).json()
    run = client.post(
        "/api/runs/start",
        json={"task_id": rider_task["id"], "case_id": case["id"], "model_provider": "mock_baseline"},
    ).json()
    report = client.get(f"/api/reports/{run['report_id']}").json()
    displayed_rules = " ".join(report["matched_rules"] + report["failed_rules"])
    active = report["active_rules"]
    active_rules = " ".join(active["global_rules"] + active["case_rules"] + active["triggered_rules"])

    assert report["active_rules_explanation"]
    assert "退出飞毛腿流程" in active_rules
    assert "App 飞毛腿报名" in active_rules
    assert "提醒安全" not in displayed_rules
    assert "报名排名" not in displayed_rules
    assert "可以开始配送" not in displayed_rules
    assert "单日/多日合同完成要求" not in displayed_rules


def test_course_owner_first_turn_only_activates_identity_and_upgrade_intro_rules():
    judge = RuleJudge()
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {
        "name": "负责人正常沟通",
        "user_profile": "课程机构负责人，愿意听产品升级说明。",
        "initial_message": "我是负责人，你说吧。",
        "expected_goals": ["说明直播发布页升级内容"],
        "required_rules": [
            "是否确认对方是否负责人",
            "是否说明新增“标准直播”和“低延迟直播”",
            "是否说明费用差异或低延迟可能费用更高",
            "是否说明企业微信添加逻辑",
            "是否在结束前确认是否还有问题",
            "是否根据 Web 控制台 / 第三方系统给出不同引导",
        ],
        "forbidden_rules": ["不能承诺优惠券或折扣"],
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "我是负责人，你说吧。",
            "assistant_message": "我们直播发布页新增标准直播和低延迟直播。",
            "latency_ms": 150,
        }
    ]

    assert judge.get_conversation_stage(task, case, messages) == "upgrade_intro"
    active = judge.get_active_rules(task, case, messages)
    active_text = " ".join(active["global_rules"] + active["stage_rules"] + active["case_rules"] + active["triggered_rules"])
    pending_text = " ".join(active["pending_rules"])
    turn_score = judge.score_turn(case, messages, 150, task)
    displayed_rules = " ".join(turn_score["matched_rules"] + turn_score["missed_rules"] + turn_score["violated_rules"])

    assert "识别负责人" in active_text
    assert "进入升级说明" in active_text
    assert "新增“标准直播”和“低延迟直播”" in active_text
    assert "保持简短自然" in active_text
    assert "费用差异" not in displayed_rules
    assert "企业微信添加逻辑" not in displayed_rules
    assert "结束前确认是否还有问题" not in displayed_rules
    assert "Web 控制台 / 第三方系统给出不同引导" not in displayed_rules
    assert "低延迟直播可能费用更高" in pending_text
    assert "企业微信添加逻辑" in pending_text
    assert "确认是否还有问题" in pending_text


def test_course_configuration_followup_activates_path_rules_only_after_user_asks():
    judge = RuleJudge()
    task = {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"}
    case = {
        "name": "负责人正常沟通",
        "user_profile": "课程机构负责人。",
        "initial_message": "我是负责人，你说吧。",
        "expected_goals": ["说明区别和配置路径"],
        "required_rules": [
            "是否说明新增“标准直播”和“低延迟直播”",
            "是否根据 Web 控制台 / 第三方系统给出不同引导",
            "是否说明费用差异或低延迟可能费用更高",
        ],
        "forbidden_rules": [],
    }
    messages = [
        {
            "turn_index": 1,
            "user_message": "我是负责人，你说吧。",
            "assistant_message": "我们直播发布页新增标准直播和低延迟直播。",
            "latency_ms": 150,
        },
        {
            "turn_index": 2,
            "user_message": "你直接说区别和在哪里配置。",
            "assistant_message": "标准延迟约 5-10 秒，低延迟约 1-2 秒。您是用 Web 控制台还是第三方系统？",
            "latency_ms": 160,
        },
    ]

    assert judge.get_conversation_stage(task, case, messages) == "configuration_guidance"
    active = judge.get_active_rules(task, case, messages)
    active_text = " ".join(active["global_rules"] + active["stage_rules"] + active["case_rules"] + active["triggered_rules"])

    assert "标准直播费用低且延迟约 5-10 秒" in active_text
    assert "低延迟直播延迟约 1-2 秒且互动更流畅" in active_text
    assert "询问或判断当前发布方式" in active_text
    assert "说明配置路径" in active_text
    assert "说明低延迟直播可能费用更高" not in active_text
    assert "企业微信添加逻辑" not in active_text


def test_course_owner_first_turn_report_keeps_later_stage_rules_pending(client):
    tasks = client.get("/api/tasks").json()
    course_task = next(task for task in tasks if task.get("task_type") == "course_platform_outbound")
    case_payload = {
        "task_id": course_task["id"],
        "name": "负责人正常沟通首轮阶段测试",
        "user_profile": "课程机构负责人，愿意先听升级说明。",
        "initial_message": "我是负责人，你说吧。",
        "max_turns": 1,
        "expected_goals": ["说明直播发布页升级内容"],
        "required_rules": [
            "是否确认对方是否负责人",
            "是否说明新增“标准直播”和“低延迟直播”",
            "是否说明费用差异或低延迟可能费用更高",
            "是否说明企业微信添加逻辑",
            "是否在结束前确认是否还有问题",
            "是否根据 Web 控制台 / 第三方系统给出不同引导",
        ],
        "forbidden_rules": ["不能承诺优惠券或折扣"],
        "difficulty": "简单",
    }
    case = client.post("/api/cases", json=case_payload).json()
    run = client.post(
        "/api/runs/start",
        json={"task_id": course_task["id"], "case_id": case["id"], "model_provider": "mock_baseline"},
    ).json()
    report = client.get(f"/api/reports/{run['report_id']}").json()
    displayed_rules = " ".join(report["matched_rules"] + report["failed_rules"])
    pending_text = " ".join(report.get("pending_rules", []))

    assert report["current_stage"] == "upgrade_intro"
    assert "费用差异" not in displayed_rules
    assert "企业微信添加逻辑" not in displayed_rules
    assert "结束前确认是否还有问题" not in displayed_rules
    assert "Web 控制台 / 第三方系统给出不同引导" not in displayed_rules
    assert "低延迟直播可能费用更高" in pending_text
    assert "企业微信添加逻辑" in pending_text
