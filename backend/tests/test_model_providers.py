from types import SimpleNamespace

from app.core.config import settings
from app.services.target_model_client import TargetModelClient, TargetModelError


def test_list_model_providers_hides_api_key(client):
    response = client.get("/api/model-providers")
    assert response.status_code == 200
    providers = response.json()
    names = {item["name"] for item in providers}
    assert names == {"mock_fallback", "openai_compatible", "custom_endpoint"}
    assert all("api_key" not in item for item in providers)
    assert all("description" in item for item in providers)


def test_mock_fallback_provider_connection_test(client):
    response = client.post("/api/model-providers/test", json={"provider": "mock_fallback"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True
    assert result["success"] is True
    assert result["provider"] == "mock_fallback"


def test_mock_fallback_model_name_stays_fallback():
    settings.target_model_name = "qwen-plus"
    client = TargetModelClient("mock_fallback")
    assert client.model_info()["model_name"] == "mock_fallback"


def test_qianwen_provider_alias_maps_to_openai_compatible(monkeypatch):
    monkeypatch.setattr(settings, "target_model_name", "qwen-plus")
    client = TargetModelClient("qianwen")

    assert client.model_info()["model_provider"] == "openai_compatible"
    assert client.model_info()["model_name"] == "qwen-plus"


def test_openai_compatible_model_name_comes_from_env():
    settings.target_model_name = "qwen-plus"
    client = TargetModelClient("openai_compatible", "wrong-model")
    assert client.model_info()["model_name"] == "qwen-plus"


def test_model_provider_list_cleans_inline_url_comments(client, monkeypatch):
    monkeypatch.setattr(settings, "target_model_provider", "qianwen")
    monkeypatch.setattr(settings, "target_model_api_key", "test-key")
    monkeypatch.setattr(settings, "target_model_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1  # comment")
    monkeypatch.setattr(settings, "target_model_endpoint", "https://example.test/reply  # comment")

    response = client.get("/api/model-providers")

    assert response.status_code == 200
    providers = response.json()
    openai_provider = next(item for item in providers if item["name"] == "openai_compatible")
    custom_provider = next(item for item in providers if item["name"] == "custom_endpoint")
    assert openai_provider["active"] is True
    assert openai_provider["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert custom_provider["endpoint"] == "https://example.test/reply"


def test_openai_compatible_chat_prefers_stream_true(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            assert kwargs.get("stream") is True
            return [
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="O"))]),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="K"))]),
            ]

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.services.target_model_client.OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "target_model_api_key", "test-key")
    monkeypatch.setattr(settings, "target_model_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "target_model_name", "qwen-plus")

    client = TargetModelClient("openai_compatible")
    assert client._call_openai_chat([{"role": "user", "content": "ping"}], temperature=0) == "OK"
    assert calls and calls[0]["stream"] is True


def test_openai_compatible_folds_system_role_into_user(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            roles = [item["role"] for item in kwargs["messages"]]
            assert roles == ["user"]
            assert "系统约束" in kwargs["messages"][0]["content"]
            assert "任务上下文" in kwargs["messages"][0]["content"]
            assert "上一轮回复" in kwargs["messages"][0]["content"]
            assert "继续" in kwargs["messages"][0]["content"]
            return [
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="O"))]),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="K"))]),
            ]

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.services.target_model_client.OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "target_model_api_key", "test-key")
    monkeypatch.setattr(settings, "target_model_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "target_model_name", "qwen-plus")

    client = TargetModelClient("openai_compatible")
    content = client._call_openai_chat(
        [
            {"role": "system", "content": "系统约束"},
            {"role": "user", "content": "任务上下文"},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "上一轮回复"},
            {"role": "user", "content": "继续"},
        ],
        temperature=0,
    )
    assert content == "OK"
    assert calls and all(item["role"] in {"user", "assistant"} for item in calls[0]["messages"])
    assert len(calls[0]["messages"]) == 1


def test_openai_connection_error_message_is_actionable(monkeypatch):
    class FakeCompletions:
        def create(self, **_kwargs):
            raise RuntimeError("Connection error.")

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.services.target_model_client.OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "target_model_api_key", "test-key")
    monkeypatch.setattr(settings, "target_model_base_url", "https://openai.qianwenapi.com")
    monkeypatch.setattr(settings, "target_model_name", "qianwen")

    client = TargetModelClient("openai_compatible")
    try:
        client._call_openai_chat([{"role": "user", "content": "ping"}], temperature=0)
    except TargetModelError as exc:
        assert exc.code == "openai_compatible_connection_failed"
        assert "外接模型连接失败" in exc.message
        assert "Base URL=https://openai.qianwenapi.com" in exc.message
        assert "dashscope.aliyuncs.com/compatible-mode/v1" in exc.message
        assert "TARGET_MODEL_BASE_URL" in exc.message
        assert "原始错误：Connection error." in exc.message
    else:
        raise AssertionError("expected TargetModelError")


def test_opening_reply_sanitizes_overlong_provider_content():
    client = TargetModelClient("mock_fallback")
    opening = "你好，请问是王师傅吗？我是美团外卖骑手的站长。"
    provider_content = (
        "你好，请问是${rider_name}吗？我是站长。"
        "我看到你已报名飞毛腿。单日合同生效当天必须完成 X 单。"
    )

    assert client._safe_opening_reply(provider_content, opening, "rider_outbound") == opening


def test_rider_opening_replaces_rider_name_placeholder():
    client = TargetModelClient("mock_fallback")

    opening = client.opening_line_for_task(
        {
            "task_type": "rider_outbound",
            "opening_line": (
                "你好，请问是${rider_name}吗？我是站长。"
                "我看到你已报名飞毛腿。请记住，午晚高峰需要上线。"
            ),
        },
        {"name": "正常愿意配送", "user_profile": "普通骑手，愿意配合。"},
    )

    assert opening == "你好，请问是王师傅吗？我是美团外卖骑手的站长。"
    assert "${rider_name}" not in opening


def test_rider_reply_normalization_removes_markdown_bold_markers():
    client = TargetModelClient("mock_fallback")

    content = client.validate_reply_by_task_type(
        "单日合同需要完成 **X 单**，多日合同每天需要完成 **Y 单**。",
        "rider_outbound",
    )

    assert "**" not in content
    assert "X 单" in content
    assert "Y 单" in content


def test_rider_exit_question_repairs_external_safety_reply():
    client = TargetModelClient("openai_compatible")

    repaired, repaired_used = client._repair_rider_external_reply(
        "少拒单少取消，别超时，注意安全。",
        {"name": "询问如何退出飞毛腿", "user_profile": "信息咨询骑手。"},
        [{"turn_index": 3, "user_message": "我想退出飞毛腿，怎么取消？"}],
        {
            "current_stage": "exit",
            "assistant_said_topics": ["已说明合同已生效", "已提醒高峰上线", "已说明 X 单/Y 单"],
        },
    )

    assert repaired_used is True
    assert repaired == "前一天Z点前在App飞毛腿报名取消，次日生效。"


def test_rider_exit_question_with_not_participating_repairs_to_exact_flow():
    client = TargetModelClient("openai_compatible")

    repaired, repaired_used = client._repair_rider_external_reply(
        "单日合同生效当天必须完成 X 单；多日合同每天必须完成 Y 单。",
        {"name": "飞毛腿骑手合同生效外呼用例", "user_profile": "递进式综合骑手。"},
        [{"turn_index": 6, "user_message": "如果不参加了在哪里取消？"}],
        {
            "current_stage": "exit",
            "assistant_said_topics": ["已说明合同已生效", "已提醒高峰上线", "已说明 X 单/Y 单"],
        },
    )

    assert repaired_used is True
    assert repaired == "前一天Z点前在App飞毛腿报名取消，次日生效。"


def test_rider_reward_question_answers_reward_before_contract_rules():
    client = TargetModelClient("openai_compatible")

    repaired, repaired_used = client._repair_rider_external_reply(
        "单日合同生效当天必须完成 X 单；多日合同每天必须完成 Y 单；未完成合同及派单可能受影响。",
        {"name": "飞毛腿骑手合同生效外呼用例", "user_profile": "递进式综合骑手。"},
        [{"turn_index": 4, "user_message": "多日都完成会有激励吗？"}],
        {
            "current_stage": "reward",
            "assistant_said_topics": ["已说明合同已生效", "已提醒高峰上线", "已说明 X 单/Y 单"],
        },
    )

    assert repaired_used is True
    assert repaired == "连续W天每天Y单，可获额外奖励，每单多+$。"


def test_rider_reward_generate_reply_does_not_need_second_prompt():
    client = TargetModelClient("mock_fallback")

    result = client.generate_reply(
        {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"},
        {"name": "飞毛腿骑手合同生效外呼用例", "user_profile": "递进式综合骑手。"},
        "多日都完成会有激励吗？",
        [],
    )

    assert result.content == "连续W天每天Y单，可获额外奖励，每单多+$。"


def test_rider_rank_question_repairs_to_full_qualification_rule():
    client = TargetModelClient("openai_compatible")

    repaired, repaired_used = client._repair_rider_external_reply(
        "报名按排名，不是站长定的。",
        {"name": "质疑报名排名", "user_profile": "质疑规则骑手。"},
        [{"turn_index": 3, "user_message": "那飞毛腿名额是你们站长定的吗？"}],
        {
            "current_stage": "rank",
            "assistant_said_topics": ["已说明合同已生效", "已提醒高峰上线", "已说明 X 单/Y 单"],
        },
    )

    assert repaired_used is True
    assert repaired == "名额按系统排名，非站长定；少拒单取消超时保资格。"


def test_rider_contract_requirement_repairs_wrong_x_or_y_wording():
    client = TargetModelClient("openai_compatible")

    repaired, repaired_used = client._repair_rider_external_reply(
        "好的，午餐和晚餐高峰记得上线。每天至少完成 X 单或 Y 单，少拒单、取消和超时。注意安全。",
        {"name": "飞毛腿骑手合同生效外呼用例", "user_profile": "正常愿意配送骑手。"},
        [{"turn_index": 2, "user_message": "可以，我今天能跑。"}],
        {
            "current_stage": "peak_online",
            "assistant_said_topics": ["已说明合同已生效"],
        },
    )

    assert repaired_used is True
    assert repaired == "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。"


def test_rider_weather_reply_includes_safety_and_qualification():
    client = TargetModelClient("mock_fallback")

    result = client.generate_reply(
        {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"},
        {"name": "抱怨恶劣天气", "user_profile": "情绪不满骑手。"},
        "今天下雨这么大，怎么还让我跑？",
        [],
    )

    assert "安全" in result.content
    assert any(term in result.content for term in ["订单更多", "单量更多"])
    assert "资格" in result.content


def test_rider_safety_question_does_not_use_qualification_rule_as_safety():
    client = TargetModelClient("mock_fallback")

    result = client.generate_reply(
        {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"},
        {"name": "飞毛腿骑手合同生效外呼用例", "user_profile": "递进式综合骑手。"},
        "配送时有什么安全要注意？",
        [],
    )

    assert "安全" in result.content
    assert "拒单" not in result.content
    assert "取消" not in result.content
    assert "超时" not in result.content


def test_rider_reply_after_contract_advances_without_repeating():
    client = TargetModelClient("mock_fallback")
    history = [
        {"turn_index": 0, "user_message": "", "assistant_message": "你好，请问是王师傅吗？我是美团外卖骑手的站长。"},
        {"turn_index": 1, "user_message": "是我，你说。", "assistant_message": "飞毛腿合同已生效，可以开始配送吗？"},
        {
            "turn_index": 2,
            "user_message": "可以，我今天能跑。",
            "assistant_message": "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。",
        },
    ]

    result = client.generate_reply(
        {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"},
        {"name": "飞毛腿骑手合同生效外呼用例", "user_profile": "递进式综合骑手。"},
        "行，我尽量完成。",
        history,
    )

    assert len(result.content) <= 30
    assert "安全" in result.content
    assert "单日" not in result.content
    assert result.should_close is False


def test_rider_unwilling_reply_tries_to_retain_without_forcing():
    client = TargetModelClient("mock_fallback")

    result = client.generate_reply(
        {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"},
        {"name": "骑手不想配送", "user_profile": "不想配送骑手。"},
        "我今天不想干了，能不能不送？",
        [],
    )

    assert "理解" in result.content
    assert "许多骑手" in result.content
    assert "名额可能被占" in result.content
    assert len(result.content) <= 30


def test_rider_unwilling_external_reply_repairs_to_faq_retention():
    client = TargetModelClient("openai_compatible")

    repaired, repaired_used = client._repair_rider_external_reply(
        "注意安全，今天能跑就跑。",
        {"name": "骑手不想配送", "user_profile": "不想干的骑手。"},
        [{"turn_index": 3, "user_message": "我不想干了，今天不跑行不行？"}],
        {
            "current_stage": "reject_delivery",
            "assistant_said_topics": ["已说明合同已生效", "已提醒高峰上线", "已说明 X 单/Y 单"],
        },
    )

    assert repaired_used is True
    assert "许多骑手" in repaired
    assert "名额可能被占" in repaired
    assert len(repaired) <= 30


def test_rider_prompt_contains_unwilling_faq_requirements():
    client = TargetModelClient("openai_compatible")
    messages = client._messages(
        {"task_type": "rider_outbound", "name": "飞毛腿骑手合同生效外呼评测"},
        {"name": "骑手不想配送", "user_profile": "不想配送骑手。"},
        [{"turn_index": 1, "user_message": "我不想干了，今天不跑行不行？", "assistant_message": ""}],
        [{"title": "不想配送挽留", "content": "目前许多骑手正在申请飞毛腿。"}],
    )

    prompt = "\n".join(item["content"] for item in messages)
    assert "如果骑手说不想干" in prompt
    assert "许多骑手正在申请飞毛腿" in prompt
    assert "无法连续配送 Y 天" in prompt
    assert "合同及派单" in prompt
    assert "每单多 +$ 元" in prompt


def test_course_prompt_contains_reply_contract():
    client = TargetModelClient("openai_compatible")
    messages = client._messages(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "直播区别触发验证", "initial_message": "标准直播和低延迟直播有什么区别？"},
        [{"turn_index": 1, "user_message": "标准直播和低延迟直播有什么区别？", "assistant_message": ""}],
        [{"title": "标准直播与低延迟直播区别", "content": "标准直播延迟5-10秒；低延迟直播1-2秒，互动更流畅。"}],
    )

    system_prompt = messages[0]["content"]
    task_context = messages[1]["content"]

    assert "本轮回复契约" in system_prompt
    assert "当前阶段=live_difference" in system_prompt
    assert "标准直播费用低，延迟5-10秒。" in system_prompt
    assert "reply_contract" in task_context
    assert "retrieved_knowledge" in task_context


def test_custom_endpoint_payload_includes_prompt_messages_and_reply_contract(monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return "标准直播费用低，延迟5-10秒。"

    monkeypatch.setattr(settings, "target_model_endpoint", "https://example.test/reply")
    client = TargetModelClient("custom_endpoint")
    monkeypatch.setattr(client, "_post_json", fake_post_json)

    content = client._call_custom_endpoint(
        {"task_type": "course_platform_outbound", "name": "课程直播产品升级外呼评测"},
        {"name": "直播区别触发验证", "initial_message": "标准直播和低延迟直播有什么区别？"},
        [{"turn_index": 1, "user_message": "标准直播和低延迟直播有什么区别？", "assistant_message": ""}],
        [{"title": "标准直播与低延迟直播区别", "content": "标准直播延迟5-10秒；低延迟直播1-2秒，互动更流畅。"}],
    )

    payload = captured["payload"]
    assert content == "标准直播费用低，延迟5-10秒。"
    assert captured["url"] == "https://example.test/reply"
    assert payload["reply_contract"]["current_stage"] == "live_difference"
    assert payload["reply_contract"]["recommended_reply"] == "标准直播费用低，延迟5-10秒。"
    assert payload["prompt_messages"][0]["role"] == "system"
    assert "本轮回复契约" in payload["prompt_messages"][0]["content"]


def test_openai_compatible_missing_config_raises_without_fallback():
    settings.target_model_allow_fallback = False
    client = TargetModelClient("openai_compatible")
    try:
        client.generate_reply({"task_type": "generic_outbound"}, {"name": "case"}, "你好", [])
    except TargetModelError as exc:
        assert exc.code == "missing_target_model_api_key"
    else:
        raise AssertionError("expected TargetModelError")


def test_legacy_mock_provider_maps_to_fallback(client):
    response = client.post("/api/model-providers/test", json={"provider": "mock_strong"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True
    assert result["success"] is True
    assert result["provider"] == "mock_fallback"
