from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session

from app.models.report import EvaluationReport
from app.services.rule_judge import METRIC_NAMES, SCORE_WEIGHTS


METRIC_FIELDS = list(SCORE_WEIGHTS.keys())


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
        score_formula = self._score_formula(metrics)
        evidence_messages = self._combine_evidence_messages(rule_result, llm_result, messages)
        failure_cases = self._combine_failure_cases(rule_result, llm_result)
        suggestions = self._combine_suggestions(rule_result, llm_result)
        metric_explanations = self._sync_metric_explanation_scores(
            rule_result.get("metric_explanations", []),
            metrics,
            llm_result,
        )

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
            suggestions=suggestions,
            metric_details=self._sync_metric_detail_scores(rule_result["metric_details"], metrics),
            metric_explanations=metric_explanations,
            failure_cases=failure_cases,
            explainability={
                **rule_result["explainability"],
                "overall_reason": llm_result.get(
                    "overall_reason",
                    rule_result["explainability"].get("overall_reason", ""),
                ),
                "llm_judge_result": llm_result,
                "llm_evidence": llm_result.get("evidence", []),
                "score_formula": score_formula,
            },
            evidence_messages=evidence_messages,
            score_formula=score_formula,
            messages=messages,
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def _combine_metrics(self, rule_result: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, float]:
        combined = {}
        for field in METRIC_FIELDS:
            rule_value = float(rule_result["metrics"][field])
            llm_value = float(llm_result.get(field, rule_value))
            combined[field] = round(rule_value * 0.7 + llm_value * 0.3, 2)
        combined["total_score"] = round(sum(combined[field] * SCORE_WEIGHTS[field] for field in METRIC_FIELDS), 2)
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
            item.setdefault("deduction_reason", "暂无明显扣分原因")
            item.setdefault("evidence_turns", [])
            item.setdefault("evidence_text", "")
            item.setdefault("suggestion", "暂无优化建议")
            item["llm_score"] = llm_result.get(key, item["score"])
            item["llm_overall_reason"] = llm_result.get("overall_reason", "")
            llm_evidence = self._llm_evidence_for_metric(key, llm_result)
            if llm_evidence:
                item["llm_evidence"] = llm_evidence
                if item.get("deduction_reason") == "暂无明显扣分原因":
                    item["deduction_reason"] = llm_evidence[0].get("deduction", item["deduction_reason"])
                if not item.get("evidence_text"):
                    item["evidence_text"] = llm_evidence[0].get("quote", "")
                if not item.get("evidence_turns"):
                    item["evidence_turns"] = [llm_evidence[0].get("turn_index", 1)]
            rows.append(item)
        return rows

    def _combine_evidence_messages(
        self,
        rule_result: Dict[str, Any],
        llm_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        rows = [dict(item) for item in rule_result.get("evidence_messages", [])]
        message_by_turn = {int(item.get("turn_index", 1)): item for item in messages}
        seen = {
            (
                int(item.get("turn_index", 1)),
                str(item.get("assistant_message", "")),
                str(item.get("issue", "")),
            )
            for item in rows
        }
        for item in llm_result.get("evidence", []) or []:
            if not isinstance(item, dict):
                continue
            turn_index = int(item.get("turn_index") or 1)
            source_message = message_by_turn.get(turn_index, {})
            quote = str(item.get("quote") or "")
            row = {
                "turn_index": turn_index,
                "user_message": source_message.get("user_message", ""),
                "assistant_message": quote or source_message.get("assistant_message", ""),
                "related_rules": [item.get("issue", "LLM 语义评估")],
                "issue": item.get("issue", ""),
                "deduction": item.get("deduction", ""),
                "source": "llm_judge",
            }
            key = (turn_index, row["assistant_message"], row["issue"])
            if key not in seen:
                rows.append(row)
                seen.add(key)
        if not rows:
            rows = [
                {
                    "turn_index": item.get("turn_index", 1),
                    "user_message": item.get("user_message", ""),
                    "assistant_message": item.get("assistant_message", ""),
                    "related_rules": [],
                    "source": "conversation",
                }
                for item in messages
            ]
        return sorted(rows, key=lambda item: int(item.get("turn_index", 1)))

    def _combine_failure_cases(
        self,
        rule_result: Dict[str, Any],
        llm_result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        cases = [dict(item) for item in rule_result.get("failure_cases", [])]
        for item in llm_result.get("evidence", []) or []:
            if not isinstance(item, dict):
                continue
            issue = str(item.get("issue") or "").strip()
            deduction = str(item.get("deduction") or "").strip()
            quote = str(item.get("quote") or "").strip()
            if not issue and not deduction:
                continue
            if "未发现" in issue and ("无明显" in deduction or "无扣分" in deduction):
                continue
            cases.append(
                {
                    "rule_name": issue or "LLM 语义评估扣分点",
                    "severity": "medium",
                    "turn_index": int(item.get("turn_index") or 1),
                    "evidence": quote,
                    "deduction_reason": deduction or llm_result.get("overall_reason", ""),
                    "dialogue_snippet": quote,
                    "suggestion": self._first_suggestion(llm_result),
                    "source": "llm_judge",
                }
            )
        return cases

    def _first_suggestion(self, llm_result: Dict[str, Any]) -> str:
        suggestions = llm_result.get("suggestions") or []
        return suggestions[0] if suggestions else "结合任务指令补齐缺失流程，并引用用户问题直接回应。"

    def _llm_evidence_for_metric(self, metric_key: str, llm_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        evidence = llm_result.get("evidence") or []
        keywords = {
            "task_completion": ["任务", "目标", "完成", "流程"],
            "instruction_following": ["指令", "规则", "禁止", "必须"],
            "call_flow_coverage": ["流程", "节点", "覆盖", "下一步"],
            "constraint_compliance": ["约束", "禁止", "越权", "安全", "串场"],
            "context_consistency": ["上下文", "重复", "追问", "承接"],
            "response_quality": ["质量", "自然", "简短", "话术"],
        }.get(metric_key, [])
        matched = []
        for item in evidence:
            text = f"{item.get('issue', '')} {item.get('deduction', '')}"
            if not keywords or any(keyword in text for keyword in keywords):
                matched.append(item)
        return matched[:2]
