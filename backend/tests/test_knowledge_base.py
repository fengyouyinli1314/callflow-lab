from app.services.knowledge_base import build_knowledge_chunks, retrieve_knowledge


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
    run = response.json()
    messages = client.get(f"/api/runs/{run['run_id']}/messages").json()
    report = client.get(f"/api/reports/{run['report_id']}").json()
    return task, case, run, messages, report


def _first_business_message(messages):
    return next(item for item in messages if item.get("turn_index") != 0)


def _message_with_user_text(messages, *keywords):
    return next(
        item
        for item in messages
        if all(keyword in (item.get("user_message") or "") for keyword in keywords)
    )


def test_build_knowledge_chunks_has_expected_structure():
    task = {
        "id": 7,
        "task_type": "rider_outbound",
        "opening_line": "你好，我是站长。",
        "call_flow": "先确认合同是否生效，再说明配送要求。",
        "knowledge_points": "退出：需前一天 Z 点前在 App 的飞毛腿报名中取消，次日生效。",
        "constraints": "禁止承诺额外奖励。",
    }

    chunks = build_knowledge_chunks(task)

    assert chunks
    assert all({"task_id", "chunk_type", "title", "content", "source"} <= set(chunk) for chunk in chunks)
    assert any(chunk["title"] == "退出飞毛腿流程" for chunk in chunks)
    assert any(chunk["chunk_type"] == "opening" for chunk in chunks)


def test_retrieve_rider_exit_knowledge():
    task = {"id": 1, "task_type": "rider_outbound", "knowledge_points": ""}

    chunks = retrieve_knowledge(task, "我想退出飞毛腿，怎么取消？")

    assert chunks[0]["title"] == "退出飞毛腿流程"
    assert "App" in chunks[0]["content"]
    assert "次日生效" in chunks[0]["content"]


def test_retrieve_rider_rank_qualification_knowledge():
    task = {"id": 1, "task_type": "rider_outbound", "knowledge_points": ""}

    chunks = retrieve_knowledge(task, "拒单取消超时会不会影响飞毛腿资格？")

    assert chunks[0]["title"] == "报名排名规则"
    assert "系统排名" in chunks[0]["content"]
    assert "拒单" in chunks[0]["content"]
    assert "资格" in chunks[0]["content"]


def test_retrieve_rider_reward_and_unwilling_knowledge():
    task = {"id": 1, "task_type": "rider_outbound", "knowledge_points": ""}

    reward_chunks = retrieve_knowledge(task, "连续跑完会有奖励或补贴吗？")
    unwilling_chunks = retrieve_knowledge(task, "我今天不想干，不想配送，跑不了。")

    assert reward_chunks[0]["title"] == "连续完成激励"
    assert "W 天" in reward_chunks[0]["content"]
    assert "+$" in reward_chunks[0]["content"]
    assert unwilling_chunks[0]["title"] == "不想配送挽留"
    assert "许多骑手" in unwilling_chunks[0]["content"]
    assert "连续配送 Y 天" in unwilling_chunks[0]["content"]
    assert "名额可能会被他人占用" in unwilling_chunks[0]["content"]
    assert "尽量挽留" in unwilling_chunks[0]["content"]


def test_retrieve_course_live_difference_knowledge():
    task = {"id": 2, "task_type": "course_platform_outbound", "knowledge_points": ""}

    chunks = retrieve_knowledge(task, "标准直播和低延迟有什么区别？")

    assert chunks[0]["title"] == "标准直播与低延迟直播区别"
    assert "5-10 秒" in chunks[0]["content"]
    assert "1-2 秒" in chunks[0]["content"]


def test_rider_rank_run_saves_retrieved_knowledge_metadata(client):
    _, _, _, messages, report = _run_case(client, RIDER_TASK, "飞毛腿骑手合同生效外呼用例")

    rank_message = _message_with_user_text(messages, "名额", "站长")
    titles = [item["title"] for item in rank_message["detail"]["retrieved_knowledge"]]
    assert "报名排名规则" in titles
    assert "系统排名" in rank_message["assistant_message"]
    assert any(term in rank_message["assistant_message"] for term in ["不是站长人工干预", "非站长"])
    assert "资格" in rank_message["assistant_message"]
    knowledge_assessment = report["llm_judge_result"]["knowledge_assessment"]
    assert "报名排名规则" in knowledge_assessment["retrieved_titles"]
    assert "报名排名规则" in knowledge_assessment["used_knowledge"]


def test_course_difference_run_saves_retrieved_knowledge_metadata(client):
    _, _, _, messages, report = _run_case(client, COURSE_TASK, "课程直播产品升级外呼用例")

    difference_message = _message_with_user_text(messages, "区别")
    titles = [item["title"] for item in difference_message["detail"]["retrieved_knowledge"]]
    assert "标准直播与低延迟直播区别" in titles
    assert "5-10秒" in difference_message["assistant_message"]
    assert any("1-2秒" in item["assistant_message"] for item in messages)
    knowledge_assessment = report["llm_judge_result"]["knowledge_assessment"]
    assert "标准直播与低延迟直播区别" in knowledge_assessment["retrieved_titles"]
    assert "标准直播与低延迟直播区别" in knowledge_assessment["used_knowledge"]
