from __future__ import annotations

import json
from typing import Any, Dict, List

from app.services.llm_client import LLMClient
from app.services.rule_judge import SCORE_WEIGHTS


class LLMJudge:
    def __init__(self) -> None:
        self.llm_client = LLMClient()

    def evaluate(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        fallback = self._mock_judgement(rule_result, messages)
        if self.llm_client.use_mock:
            return fallback

        content = self.llm_client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是对话模型评测裁判。请只输出 JSON，字段包括 score、task_completion、"
                        "instruction_following、call_flow_coverage、constraint_compliance、"
                        "context_consistency、response_quality、"
                        "reason、suggestions。"
                    ),
                },
                {
                    "role": "user",
                    "content": str(
                        {
                            "task": task_payload,
                            "case": case_payload,
                            "messages": messages,
                            "rule_result": rule_result,
                        }
                    ),
                },
            ],
            json.dumps(fallback, ensure_ascii=False),
        )
        return self._safe_json(content, fallback)

    def _mock_judgement(self, rule_result: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        metrics = rule_result["metrics"]
        repeat_adjustment = self._repeat_adjustment(messages)
        suggestions = list(rule_result.get("suggestions", []))
        if repeat_adjustment:
            suggestions.append("裁判建议减少相似句式，增强每轮回复的信息增量。")
        adjusted_metrics = {
            "task_completion": metrics["task_completion"],
            "instruction_following": metrics["instruction_following"],
            "call_flow_coverage": metrics["call_flow_coverage"],
            "constraint_compliance": metrics["constraint_compliance"],
            "context_consistency": max(0, metrics["context_consistency"] - repeat_adjustment),
            "response_quality": max(0, metrics["response_quality"] - repeat_adjustment),
        }
        score = round(sum(adjusted_metrics[key] * SCORE_WEIGHTS[key] for key in SCORE_WEIGHTS), 2)
        return {
            "score": score,
            "task_completion": adjusted_metrics["task_completion"],
            "instruction_following": adjusted_metrics["instruction_following"],
            "call_flow_coverage": adjusted_metrics["call_flow_coverage"],
            "constraint_compliance": adjusted_metrics["constraint_compliance"],
            "context_consistency": adjusted_metrics["context_consistency"],
            "safety_compliance": adjusted_metrics["constraint_compliance"],
            "response_quality": adjusted_metrics["response_quality"],
            "failed_rule_count": metrics.get("failed_rule_count", len(rule_result.get("failed_rules", []))),
            "reason": rule_result["explainability"]["overall_reason"],
            "suggestions": suggestions,
            "score_breakdown": rule_result["explainability"].get("score_breakdown", {}),
            "key_findings": rule_result["explainability"].get("key_findings", []),
        }

    def _repeat_adjustment(self, messages: List[Dict[str, Any]]) -> float:
        replies = [item.get("assistant_message", "") for item in messages]
        return 3 if len(replies) != len(set(replies)) else 0

    def _safe_json(self, content: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(content[start : end + 1])
                return {**fallback, **data}
        except Exception:
            return fallback
        return fallback
