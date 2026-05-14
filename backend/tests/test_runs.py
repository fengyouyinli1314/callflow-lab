def _first_case(client):
    task = client.get("/api/tasks").json()[0]
    case = client.get(f"/api/cases?task_id={task['id']}").json()[0]
    return task, case


def test_start_evaluation_and_get_messages(client):
    task, case = _first_case(client)
    response = client.post("/api/runs/start", json={"task_id": task["id"], "case_id": case["id"]})
    assert response.status_code == 200
    result = response.json()
    assert result["run_id"] > 0
    assert result["report_id"] > 0
    assert result["total_score"] > 0

    messages = client.get(f"/api/runs/{result['run_id']}/messages")
    assert messages.status_code == 200
    assert len(messages.json()) == case["max_turns"]
