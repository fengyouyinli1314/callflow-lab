def _task_by_type(client, task_type):
    tasks = client.get("/api/tasks").json()
    return next(item for item in tasks if item["task_type"] == task_type)


def test_generate_case_drafts_for_rider_task_without_persisting(client):
    task = _task_by_type(client, "rider_outbound")
    before = client.get(f"/api/cases?task_id={task['id']}").json()

    response = client.post(
        "/api/cases/generate",
        json={
            "task_id": task["id"],
            "case_count": 6,
            "difficulty_distribution": ["简单", "中等", "困难"],
            "user_behavior_types": ["正常配合", "拒绝配合", "情绪不满", "反复追问", "信息缺失", "超范围问题"],
        },
    )

    assert response.status_code == 200
    drafts = response.json()
    assert len(drafts) == 6
    assert all(item["data_source"] == "ai_generated" for item in drafts)
    assert any("排名" in item["name"] or "排名" in item["initial_message"] for item in drafts)
    assert any("退出" in item["name"] or "取消" in item["initial_message"] for item in drafts)
    assert all("id" not in item for item in drafts)

    after = client.get(f"/api/cases?task_id={task['id']}").json()
    assert len(after) == len(before)


def test_generated_case_draft_can_be_saved_idempotently(client):
    task = _task_by_type(client, "course_platform_outbound")
    drafts = client.post(
        "/api/cases/generate",
        json={
            "task_id": task["id"],
            "case_count": 1,
            "difficulty_distribution": ["简单", "中等", "困难"],
            "user_behavior_types": ["正常配合"],
        },
    ).json()
    draft = drafts[0]
    payload = {
        "task_id": task["id"],
        "name": draft["name"],
        "user_profile": draft["user_profile"],
        "initial_message": draft["initial_message"],
        "max_turns": draft["max_turns"],
        "expected_goals": draft["expected_goals"],
        "required_rules": draft["required_rules"],
        "forbidden_rules": draft["forbidden_rules"],
        "difficulty": draft["difficulty"],
        "trigger_conditions": draft["trigger_conditions"],
        "expected_final_state": draft["expected_final_state"],
        "user_behavior_type": draft["user_behavior_type"],
        "data_source": draft["data_source"],
    }

    first = client.post("/api/cases", json=payload)
    second = client.post("/api/cases", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    cases = client.get(f"/api/cases?task_id={task['id']}").json()
    matches = [
        item
        for item in cases
        if item["name"] == payload["name"] and item["initial_message"] == payload["initial_message"]
    ]
    assert len(matches) == 1
    assert matches[0]["data_source"] == "ai_generated"
    assert matches[0]["user_behavior_type"] == payload["user_behavior_type"]
