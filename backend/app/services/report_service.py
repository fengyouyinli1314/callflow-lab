from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session

from app.models.report import EvaluationReport
from app.services.rule_judge import METRIC_NAMES, SCORE_WEIGHTS


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
            call_flow_coverage=metrics["call_flow_coverage"],
            constraint_compliance=metrics["constraint_compliance"],
            context_consistency=metrics["context_consistency"],
            safety_compliance=metrics["constraint_compliance"],
            response_quality=metrics["response_quality"],
            avg_latency_ms=rule_result["metrics"]["avg_latency_ms"],
            failed_rule_count=int(rule_result["metrics"].get("failed_rule_count", len(rule_result["failed_rules"]))),
            total_turns=len(messages),
            matched_rules=rule_result.get("matched_rules", []),
            failed_rules=rule_result["failed_rules"],
            active_rules=rule_result.get("active_rules", {}),
            pending_rules=rule_result.get("pending_rules", []),
            current_stage=rule_result.get("current_stage", ""),
            active_rules_explanation=rule_result.get("active_rules_explanation", ""),
            llm_judge_result=llm_result,
            suggestions=self._combine_suggestions(rule_result, llm_result),
            metric_details=self._sync_metric_detail_scores(rule_result["metric_details"], metrics),
            metric_explanations=self._sync_metric_explanation_scores(
                rule_result.get("metric_explanations", []),
                metrics,
                llm_result,
            ),
            failure_cases=rule_result["failure_cases"],
            explainability={
                **rule_result["explainability"],
                "overall_reason": llm_result.get(
                    "overall_reason",
                    rule_result["explainability"].get("overall_reason", ""),
                ),
                "llm_judge_result": llm_result,
                "score_formula": self._score_formula(metrics),
            },
            evidence_messages=rule_result.get("evidence_messages", []),
            score_formula=self._score_formula(metrics),
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
            "call_flow_coverage",
            "constraint_compliance",
            "context_consistency",
            "response_quality",
        ]
        combined = {}
        for field in fields:
            rule_value = float(rule_result["metrics"][field])
            llm_value = float(llm_result.get(field, rule_value))
            combined[field] = round(rule_value * 0.75 + llm_value * 0.25, 2)
        combined["total_score"] = round(sum(combined[field] * SCORE_WEIGHTS[field] for field in fields), 2)
        combined["failed_rule_count"] = float(rule_result["metrics"].get("failed_rule_count", 0))
        combined["safety_compliance"] = combined["constraint_compliance"]
        return combined

    def _score_formula(self, metrics: Dict[str, float]) -> Dict[str, Any]:
        components = {
            key: {
                "metric_name": METRIC_NAMES[key],
                "score": metrics.get(key, 0),
                "weight": SCORE_WEIGHTS[key],
                "weighted_score": round(metrics.get(key, 0) * SCORE_WEIGHTS[key], 2),
            }
            for key in SCORE_WEIGHTS
        }
        return {
            "formula_text": (
                "总分 = 任务完成度 * 0.25 + 指令遵循率 * 0.20 + 外呼流程覆盖率 * 0.20 "
                "+ 约束遵守率 * 0.15 + 上下文一致性 * 0.10 + 回复质量 * 0.10"
            ),
            "weights": SCORE_WEIGHTS,
            "components": components,
            "total_score": metrics["total_score"],
        }

    def _sync_metric_detail_scores(
        self,
        metric_details: Dict[str, Any],
        metrics: Dict[str, float],
    ) -> Dict[str, Any]:
        synced = dict(metric_details)
        for key in SCORE_WEIGHTS:
            detail = dict(synced.get(key, {}))
            detail["score"] = metrics.get(key, detail.get("score", 0))
            synced[key] = detail
        return synced

    def _combine_suggestions(self, rule_result: Dict[str, Any], llm_result: Dict[str, Any]) -> List[str]:
        values = list(rule_result.get("suggestions", [])) + list(llm_result.get("suggestions", []))
        return list(dict.fromkeys([item for item in values if item]))

    def _sync_metric_explanation_scores(
        self,
        metric_explanations: List[Dict[str, Any]],
        metrics: Dict[str, float],
        llm_result: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        llm_result = llm_result or {}
        by_key = {item.get("metric_key"): dict(item) for item in metric_explanations}
        rows: List[Dict[str, Any]] = []
        for key in SCORE_WEIGHTS:
            item = by_key.get(key, {})
            item.setdefault("metric_name", METRIC_NAMES[key])
            item["metric_key"] = key
            item["score"] = metrics.get(key, item.get("score", 0))
            item.setdefault("deduction_reason", "暂无扣分原因")
            item.setdefault("evidence_turns", [])
            item.setdefault("evidence_text", "")
            item.setdefault("suggestion", "暂无优化建议")
            item["llm_score"] = llm_result.get(key, item["score"])
            rows.append(item)
        return rows
