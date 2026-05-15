def test_report_contains_explainability_fields(client):
    task = client.get("/api/tasks").json()[0]
    case = client.get(f"/api/cases?task_id={task['id']}").json()[0]
    run = client.post("/api/runs/start", json={"task_id": task["id"], "case_id": case["id"]}).json()

    response = client.get(f"/api/reports/{run['report_id']}")
    assert response.status_code == 200
    report = response.json()
    assert "metric_details" in report
    assert "metric_explanations" in report
    assert "failure_cases" in report
    assert "explainability" in report
    assert "evidence_messages" in report
    assert "score_formula" in report
    assert "task_completion" in report["metric_details"]
    assert len(report["metric_explanations"]) == 6
    assert "call_flow_coverage" in report
    assert "constraint_compliance" in report
    assert "failed_rule_count" in report
