import json

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
    assert "rule_trace" in report
    assert "judge_source" in report
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
    assert report["judge_source"]["label"] == "规则辅助评审"
    assert report["judge_source"]["config_hint"] == ""
    assert "mock evaluator" not in report["llm_judge_result"]["overall_reason"]
    assert report["llm_judge_result"]["judge_source"]["source_type"] == "mock_fallback"
    assert report["score_formula"]["combine_formula_text"] == "各指标融合分 = rule_score * 0.7 + judge_score * 0.3"
    component = report["score_formula"]["components"]["task_completion"]
    assert {"rule_score", "judge_score", "combined_score", "combine_formula"} <= set(component)
    assert component["combine_formula"] == "rule_score * 0.7 + judge_score * 0.3"
    metric_row = next(item for item in report["metric_explanations"] if item["metric_key"] == "task_completion")
    assert {"rule_score", "judge_score", "combined_score", "combine_formula_text"} <= set(metric_row)
    trace_rows = report["rule_trace"]["rows"]
    assert trace_rows
    assert {
        "rule_name",
        "source",
        "activation_reason",
        "activation_turn",
        "status",
        "evidence_text",
        "deduction_reason",
    } <= set(trace_rows[0])


def test_report_service_enriches_failure_cases_with_audit():
    rule = "是否说明需要前一天 Z 点前取消"
    messages = [
        {
            "turn_index": 1,
            "user_message": "我想退出飞毛腿，怎么取消？",
            "assistant_message": "您可以先在 App 里看看报名入口。",
        },
        {
            "turn_index": 2,
            "user_message": "具体什么时候生效？",
            "assistant_message": "在 App 的飞毛腿报名里操作即可。",
        },
    ]
    rule_result = {
        "failure_cases": [
            {
                "rule_name": rule,
                "severity": "high",
                "turn_index": 1,
                "evidence": f"全程未稳定体现规则：{rule}",
                "deduction_reason": f"必须满足的规则“{rule}”没有在对话中形成有效证据。",
                "dialogue_snippet": "您可以先在 App 里看看报名入口。",
                "suggestion": "补充明确取消时限。",
            }
        ],
        "missed_rules": [rule],
        "violated_rules": [],
        "hidden_guardrail_rules": {"violated": []},
        "rule_trace": {
            "rows": [
                {
                    "rule_name": rule,
                    "activation_turn": 1,
                    "activation_reason": "用户第 1 轮发言触发：我想退出飞毛腿，怎么取消？",
                }
            ]
        },
    }

    cases = ReportService(None)._combine_failure_cases(rule_result, {}, messages)

    audit = cases[0]["audit"]
    assert audit["activation_turn"] == 1
    assert audit["checked_turns"] == [1, 2]
    assert "前一天 Z 点前" in audit["missing_facts"]
    assert audit["closest_reply"]["turn_index"] == 2
    assert audit["estimated_deduction_points"] == 8.0
    assert "规则层估算影响约 8 分" in audit["deduction_impact"]


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


def test_evaluator_marks_openai_compatible_when_external_json_is_valid():
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
        "fallback_reason": "old reason",
    }
    content = json.dumps(
        {
            "task_completion": 90,
            "instruction_following": 91,
            "call_flow_coverage": 92,
            "constraint_compliance": 93,
            "context_consistency": 94,
            "response_quality": 95,
            "overall_reason": "external judge ok",
            "evidence": [],
            "suggestions": [],
            "knowledge_assessment": {},
        },
        ensure_ascii=False,
    )

    result = EvaluatorAgent()._safe_json(content, fallback)

    assert result["provider"] == "openai_compatible"
    assert result["provider_requested"] == "openai_compatible"
    assert result["fallback_used"] is False
    assert result["fallback_reason"] == ""


def test_evaluator_marks_fallback_when_external_json_is_invalid():
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

    result = EvaluatorAgent()._safe_json("只给自然语言总结，不给 JSON", fallback)

    assert result["provider"] == "mock"
    assert result["provider_requested"] == "openai_compatible"
    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "openai_compatible evaluator returned invalid JSON response"


def test_evaluator_uses_configured_timeout():
    agent = EvaluatorAgent()

    assert agent.timeout_seconds >= 10
    assert agent.max_tokens >= 256
