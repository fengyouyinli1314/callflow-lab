RIDER_FORBIDDEN = [
    "订单号",
    "手机号后四位",
    "退款",
    "商家出餐",
    "平台超时",
    "配送状态",
    "超时节点",
    "核销",
    "酒店",
    "标准直播",
    "低延迟直播",
]

COURSE_FORBIDDEN = [
    "骑手",
    "飞毛腿",
    "配送",
    "派单",
    "合同",
    "X 单",
    "Y 单",
    "退款",
    "订单号",
    "核销",
    "酒店",
]


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
    business_messages = [item for item in messages if item.get("turn_index") != 0]
    assert messages[0]["detail"].get("message_phase") == "opening"
    first_reply = business_messages[0]["assistant_message"]
    all_replies = "\n".join(item["assistant_message"] for item in messages)
    return first_reply, all_replies, result


def _assert_no_terms(text, terms):
    for term in terms:
        assert term not in text


def _assert_has_any(text, terms):
    assert any(term in text for term in terms), text


def test_rider_recursive_full_flow_reply_is_task_scoped(client):
    first_reply, all_replies, result = _run_case(client, "飞毛腿骑手合同生效外呼评测", "飞毛腿骑手合同生效外呼用例")

    assert result["task_type"] == "rider_outbound"
    _assert_no_terms(all_replies, RIDER_FORBIDDEN)
    _assert_has_any(first_reply, ["合同已签署", "合同已生效", "开始配送"])
    _assert_has_any(all_replies, ["X 单", "X单"])
    _assert_has_any(all_replies, ["Y 单", "Y单"])
    _assert_has_any(all_replies, ["按排名", "按系统排名"])
    _assert_has_any(all_replies, ["不是站长人工干预", "不是站长干预", "非站长干预", "非站长"])
    _assert_has_any(all_replies, ["拒单", "取消", "超时"])
    _assert_has_any(all_replies, ["资格", "名额"])


def test_course_full_flow_reply_is_task_scoped(client):
    first_reply, all_replies, result = _run_case(client, "课程直播产品升级外呼评测", "课程直播产品升级外呼用例")

    assert result["task_type"] == "course_platform_outbound"
    _assert_no_terms(all_replies, COURSE_FORBIDDEN)
    _assert_has_any(first_reply, ["了解低延迟直播"])
    _assert_has_any(all_replies, ["独立的低延迟直播选项", "低延迟直播选项"])
    _assert_has_any(all_replies, ["标准直播", "低延迟直播"])
    _assert_has_any(all_replies, ["Web", "校务A", "SaaS"])
    _assert_has_any(all_replies, ["进【我的】", "直播平台管理", "勾选低延迟"])
    _assert_has_any(all_replies, ["企业微信"])
