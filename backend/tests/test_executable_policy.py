import json

from app.services.policy_generator import generate_executable_policy


def _json(value):
    return json.loads(value or "{}")


def test_course_executable_policy_contains_short_turn_strategy():
    task = {
        "task_type": "course_platform_outbound",
        "constraints": json.dumps(["每次回复极简——最多15-20个字", "给出信息后，暂停等待商家回应"], ensure_ascii=False),
        "steps": json.dumps([{"step_no": str(index), "title": f"Step {index}", "content": ""} for index in range(1, 8)], ensure_ascii=False),
    }

    policy = generate_executable_policy(task)

    assert policy["reply_rules"]["max_chars_per_reply"] == 20
    assert policy["reply_rules"]["hard_limit_chars"] == 25
    assert policy["reply_rules"]["one_assistant_message_per_turn"] is True
    assert policy["reply_rules"]["wait_user_after_each_reply"] is True
    assert policy["reply_rules"]["no_multi_step_in_one_reply"] is True
    assert [step["step_no"] for step in policy["step_policies"]] == ["1", "2", "3", "4", "5", "6", "7"]

    priority_text = json.dumps(policy["global_priority_rules"], ensure_ascii=False)
    assert "那我稍后再打。" in priority_text
    assert "should_continue" in priority_text
    assert "就1分钟，保证简短。" in priority_text
    assert "您刚才问区别，对吗？" in priority_text
    assert "先回答用户问题" in priority_text

    step2 = next(step for step in policy["step_policies"] if step["step_no"] == "2")
    step2_text = json.dumps(step2, ensure_ascii=False)
    assert "您之前选的是标准直播，但我们后台其实已为您走低延迟线路以保障质量，您知道吗？" not in step2_text
    assert "您之前选标准直播，对吗？" in step2_text
    assert "后台已走低延迟，您知道吗？" in step2_text

    step3_text = json.dumps(next(step for step in policy["step_policies"] if step["step_no"] == "3"), ensure_ascii=False)
    assert "之后会显示两个选项。" in step3_text
    assert "标准直播和低延迟直播。" in step3_text
    assert "标准便宜，适合大班课。" in step3_text
    assert "互动更顺，适合小班课。" in step3_text


def test_rider_executable_policy_contains_core_branches():
    policy = generate_executable_policy(
        {
            "task_type": "rider_outbound",
            "constraints": "约30字以内",
            "steps": "[]",
        }
    )

    assert policy["reply_rules"]["max_chars_per_reply"] == 30
    assert policy["reply_rules"]["hard_limit_chars"] == 40
    branch_text = json.dumps(policy["branch_policies"], ensure_ascii=False)
    assert "天气抱怨分支" in branch_text
    assert "拒绝配送分支" in branch_text
    assert "排名质疑分支" in branch_text
    assert "退出流程分支" in branch_text
    assert "超范围兜底分支" in branch_text


def test_task_detail_returns_policy_but_list_does_not(client):
    tasks = client.get("/api/tasks").json()
    assert tasks
    assert "executable_policy" not in tasks[0]
    assert "instruction_text" not in tasks[0]

    course = next(task for task in tasks if task["task_type"] == "course_platform_outbound")
    detail = client.get(f"/api/tasks/{course['id']}").json()
    policy = _json(detail["executable_policy"])

    assert policy["reply_rules"]["max_chars_per_reply"] == 20
    assert [step["step_no"] for step in policy["step_policies"]] == ["1", "2", "3", "4", "5", "6", "7"]
    assert detail["instruction_text"]
