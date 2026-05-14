def test_cases_can_filter_by_task(client):
    tasks = client.get("/api/tasks").json()
    task_id = tasks[0]["id"]
    response = client.get(f"/api/cases?task_id={task_id}")
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) >= 3
    assert all(item["task_id"] == task_id for item in cases)
