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
    first_reply = messages[0]["assistant_message"]
    all_replies = "\n".join(item["assistant_message"] for item in messages)
    return first_reply, all_replies, result


def _assert_no_terms(text, terms):
    for term in terms:
        assert term not in text


def _assert_has_any(text, terms):
    assert any(term in text for term in terms), text


def test_rider_contract_impact_reply_is_task_scoped(client):
    first_reply, all_replies, result = _run_case(client, "飞毛腿骑手合同生效外呼评测", "询问合同影响")

    assert result["task_type"] == "rider_outbound"
    _assert_no_terms(all_replies, RIDER_FORBIDDEN)
    _assert_has_any(first_reply, ["X 单", "合同", "派单", "影响", "完成"])


def test_rider_bad_weather_reply_is_task_scoped(client):
    first_reply, all_replies, result = _run_case(client, "飞毛腿骑手合同生效外呼评测", "抱怨恶劣天气")

    assert result["task_type"] == "rider_outbound"
    _assert_no_terms(all_replies, RIDER_FORBIDDEN)
    _assert_has_any(first_reply, ["安全", "雨天", "资格", "能跑", "记录"])


def test_course_non_owner_reply_is_task_scoped(client):
    first_reply, all_replies, result = _run_case(client, "课程直播产品升级外呼评测", "非负责人转达")

    assert result["task_type"] == "course_platform_outbound"
    _assert_no_terms(all_replies, COURSE_FORBIDDEN)
    _assert_has_any(first_reply, ["负责人", "转达", "直播", "低延迟", "发布页"])
