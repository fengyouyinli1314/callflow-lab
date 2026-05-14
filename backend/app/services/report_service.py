from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session

from app.models.report import EvaluationReport


class ReportService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_report(
        self,
        run_id: int,
        task_id: int,
        case_id: int,
        rule_result: Dict[str, Any],
        llm_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> EvaluationReport:
        metrics = self._combine_metrics(rule_result, llm_result)
        report = EvaluationReport(
            run_id=run_id,
            task_id=task_id,
            case_id=case_id,
            total_score=metrics["total_score"],
            task_completion=metrics["task_completion"],
            instruction_following=metrics["instruction_following"],
            context_consistency=metrics["context_consistency"],
            safety_compliance=metrics["safety_compliance"],
            response_quality=metrics["response_quality"],
            avg_latency_ms=rule_result["metrics"]["avg_latency_ms"],
            total_turns=len(messages),
            failed_rules=rule_result["failed_rules"],
            suggestions=rule_result["suggestions"],
            metric_details=rule_result["metric_details"],
            failure_cases=rule_result["failure_cases"],
            explainability=rule_result["explainability"],
            messages=messages,
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def _combine_metrics(self, rule_result: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, float]:
        fields = [
            "task_completion",
            "instruction_following",
            "context_consistency",
            "safety_compliance",
            "response_quality",
        ]
        combined = {}
        for field in fields:
            rule_value = float(rule_result["metrics"][field])
            llm_value = float(llm_result.get(field, rule_value))
            combined[field] = round(rule_value * 0.75 + llm_value * 0.25, 2)
        combined["total_score"] = round(float(rule_result["score"]) * 0.75 + float(llm_result.get("score", 0)) * 0.25, 2)
        return combined
