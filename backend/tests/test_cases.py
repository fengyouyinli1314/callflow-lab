def test_cases_can_filter_by_task(client):
    tasks = client.get("/api/tasks").json()
    task_id = tasks[0]["id"]
    response = client.get(f"/api/cases?task_id={task_id}")
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) >= 1
    assert all(item["task_id"] == task_id for item in cases)


def test_manual_case_create_update_delete_flow(client):
    task = client.get("/api/tasks").json()[0]
    payload = {
        "task_id": task["id"],
        "name": "手动构建飞毛腿用例",
        "user_profile": "手动构建的情绪不满骑手",
        "initial_message": "我今天雨太大，不想接单了。",
        "expected_goals": ["安抚用户情绪", "提醒安全第一"],
        "required_rules": ["必须提醒安全", "必须说明合同影响"],
        "forbidden_rules": ["禁止强迫恶劣天气配送"],
        "trigger_conditions": ["用户提到下雨", "用户拒绝接单"],
        "expected_final_state": "用户理解安全边界或结束咨询",
        "user_behavior_type": "情绪不满",
        "difficulty": "困难",
        "max_turns": 5,
        "data_source": "manual",
    }

    created = client.post("/api/cases", json=payload)
    assert created.status_code == 200
    created_data = created.json()
    assert created_data["user_behavior_type"] == "情绪不满"
    assert created_data["trigger_conditions"] == payload["trigger_conditions"]

    updated = client.put(
        f"/api/cases/{created_data['id']}",
        json={"name": "手动构建飞毛腿用例-已编辑", "difficulty": "中等", "max_turns": 4},
    )
    assert updated.status_code == 200
    updated_data = updated.json()
    assert updated_data["name"] == "手动构建飞毛腿用例-已编辑"
    assert updated_data["difficulty"] == "中等"
    assert updated_data["max_turns"] == 4

    listed = client.get(f"/api/cases?task_id={task['id']}").json()
    assert any(item["id"] == created_data["id"] for item in listed)

    run = client.post(
        "/api/runs/start",
        json={"task_id": task["id"], "case_id": created_data["id"], "model_provider": "mock_fallback"},
    )
    assert run.status_code == 200
    assert run.json()["report_id"]

    deleted = client.delete(f"/api/cases/{created_data['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/cases/{created_data['id']}").status_code == 404
