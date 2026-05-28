from app.services.agents.evaluator_agent import EvaluatorAgent
from app.services.report_service import ReportService


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
    assert "matched_rules" in report
    assert "llm_judge_result" in report
    assert "task_completion" in report["metric_details"]
    assert len(report["metric_explanations"]) == 6
    assert "call_flow_coverage" in report
    assert "constraint_compliance" in report
    assert "failed_rule_count" in report
    llm_result = report["llm_judge_result"]
    for key in [
        "task_completion",
        "instruction_following",
        "call_flow_coverage",
        "constraint_compliance",
        "context_consistency",
        "response_quality",
        "overall_reason",
        "evidence",
        "suggestions",
    ]:
        assert key in llm_result
    assert report["score_formula"]["weights"]["task_completion"] == 0.25


def test_report_service_accepts_dict_metric_values():
    rule_result = {
        "metrics": {
            "task_completion": 80,
            "instruction_following": 80,
            "call_flow_coverage": 80,
            "constraint_compliance": 80,
            "context_consistency": 80,
            "response_quality": 80,
            "avg_latency_ms": 0,
            "failed_rule_count": 0,
        },
        "failed_rules": [],
    }
    llm_result = {
        "task_completion": {"score": 90, "reason": "完成"},
        "instruction_following": {"value": 85},
        "call_flow_coverage": {"points": 82},
        "constraint_compliance": {"分数": 88},
        "context_consistency": 84,
        "response_quality": "86",
    }

    metrics = ReportService(None)._combine_metrics(rule_result, llm_result)

    assert metrics["task_completion"] == 83
    assert metrics["instruction_following"] == 81.5
    assert metrics["call_flow_coverage"] == 80.6
    assert metrics["constraint_compliance"] == 82.4


def test_evaluator_normalizes_dict_metric_values():
    fallback = {
        "task_completion": 70,
        "instruction_following": 70,
        "call_flow_coverage": 70,
        "constraint_compliance": 70,
        "context_consistency": 70,
        "response_quality": 70,
        "overall_reason": "fallback",
        "evidence": [],
        "suggestions": [],
        "knowledge_assessment": {},
        "retrieved_knowledge": [],
        "active_visible_rules": [],
    }
    data = {
        "task_completion": {"score": 91},
        "instruction_following": {"value": 82},
        "call_flow_coverage": {"points": 83},
        "constraint_compliance": {"分数": 84},
        "context_consistency": "85",
        "response_quality": 86,
    }

    result = EvaluatorAgent()._normalize_llm_result(data, fallback)

    assert result["task_completion"] == 91
    assert result["instruction_following"] == 82
    assert result["call_flow_coverage"] == 83
    assert result["constraint_compliance"] == 84
