def _default_tasks(client, limit=2):
    tasks = client.get("/api/tasks").json()
    selected = [task for task in tasks if task.get("task_type") in {"rider_outbound", "course_platform_outbound"}]
    return (selected or tasks)[:limit]


def test_single_model_batch_run_generates_reports(client):
    tasks = _default_tasks(client, 2)
    payload = {
        "task_ids": [task["id"] for task in tasks],
        "case_ids": [],
        "model_providers": ["mock_fallback"],
        "repeat_times": 1,
    }
    response = client.post("/api/batch-runs/start", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["batch_id"] > 0
    assert result["total_runs"] >= len(tasks)
    assert result["finished_runs"] == result["total_runs"]
    assert result["failed_runs"] == 0

    summary_response = client.get(f"/api/batch-runs/{result['batch_id']}/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["average_score"] > 0
    assert "failed_rule_top5" in summary
    assert "pass_rate" in summary
    assert len(summary["report_list"]) == summary["total_runs"]
    assert all(item["report_id"] for item in summary["report_list"])


def test_multi_model_batch_run_returns_model_summary(client):
    task = _default_tasks(client, 1)[0]
    case = client.get(f"/api/cases?task_id={task['id']}").json()[0]
    payload = {
        "task_ids": [task["id"]],
        "case_ids": [case["id"]],
        "model_providers": ["mock_fallback", "openai_compatible"],
        "repeat_times": 1,
    }
    response = client.post("/api/batch-runs/start", json=payload)
    assert response.status_code == 200
    summary = client.get(f"/api/batch-runs/{response.json()['batch_id']}/summary").json()
    assert summary["total_runs"] == 2
    assert len(summary["model_score_summary"]) == 2
    assert summary["best_model_provider"] in {"mock_fallback", "openai_compatible"}
