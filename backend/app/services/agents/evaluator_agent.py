from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from app.core.config import settings
from app.services.rule_judge import SCORE_WEIGHTS


METRIC_FIELDS = [
    "task_completion",
    "instruction_following",
    "call_flow_coverage",
    "constraint_compliance",
    "context_consistency",
    "response_quality",
]


class EvaluatorAgent:
    """LLM-as-a-Judge evaluator focused on task-instruction performance."""

    def __init__(self) -> None:
        self.provider = (settings.evaluator_provider or "mock").strip().lower()
        self.api_key = settings.evaluator_api_key or ""
        self.base_url = (settings.evaluator_base_url or "").rstrip("/")
        self.model = (settings.evaluator_model or "mock-evaluator").strip() or "mock-evaluator"

    def evaluate(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        full_messages: List[Dict[str, Any]],
        rule_judge_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        fallback = self._mock_evaluate(task_payload, case_payload, full_messages, rule_judge_result)
        if self.provider != "openai_compatible" or not self.api_key or not self.base_url:
            return fallback

        content = self._call_openai_compatible(task_payload, case_payload, full_messages, rule_judge_result)
        if not content:
            return fallback
        return self._safe_json(content, fallback)

    def _mock_evaluate(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        metrics = dict(rule_result.get("metrics", {}))
        failed_rules = rule_result.get("failed_rules", [])
        failure_cases = rule_result.get("failure_cases", [])
        evidence = self._evidence_from_failure_cases(failure_cases, messages)
        repeat_penalty = self._repeat_penalty(messages)
        unanswered_penalty = self._unanswered_penalty(messages)

        adjusted: Dict[str, float] = {}
        for field in METRIC_FIELDS:
            base = float(metrics.get(field, 70))
            if field == "context_consistency":
                base -= repeat_penalty + unanswered_penalty
            if field == "response_quality":
                base -= repeat_penalty * 0.7
            adjusted[field] = self._clamp(base)

        total = round(sum(adjusted[field] * SCORE_WEIGHTS[field] for field in METRIC_FIELDS), 2)
        suggestions = list(rule_result.get("suggestions", []))
        if repeat_penalty:
            suggestions.append("减少机械重复，承接用户上一轮新增问题后再推进。")
        if unanswered_penalty:
            suggestions.append("对用户追问的问题直接给出结论，避免只重复基础介绍。")
        if not suggestions:
            suggestions.append("保持当前任务指令覆盖方式，继续关注高风险分支。")

        return {
            **adjusted,
            "score": total,
            "overall_reason": (
                "mock evaluator 基于硬规则结果评估被测对话模型在复杂任务指令下的表现："
                f"命中 {len(rule_result.get('matched_rules', []))} 条规则，失败 {len(failed_rules)} 条。"
            ),
            "evidence": evidence,
            "suggestions": suggestions,
            "provider": "mock",
            "model": self.model,
        }

    def _call_openai_compatible(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> str:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是复杂外呼任务对话模型评测器。只评估被测对话模型在任务指令下的表现，"
                        "不要评价本系统代码质量。只输出 JSON，字段必须包含 task_completion、"
                        "instruction_following、call_flow_coverage、constraint_compliance、"
                        "context_consistency、response_quality、overall_reason、evidence、suggestions。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction_text": task_payload.get("instruction_text", ""),
                            "task_type": task_payload.get("task_type", ""),
                            "expected_goals": case_payload.get("expected_goals", []),
                            "required_rules": case_payload.get("required_rules", []),
                            "forbidden_rules": case_payload.get("forbidden_rules", []),
                            "full_messages": messages,
                            "rule_judge_result": rule_result,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return ""

        choices = data.get("choices") if isinstance(data, dict) else None
        if choices and isinstance(choices, list):
            return str(choices[0].get("message", {}).get("content", "") or "")
        return ""

    def _safe_json(self, content: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(content[start : end + 1])
                merged = {**fallback, **data}
                for field in METRIC_FIELDS:
                    merged[field] = self._clamp(float(merged.get(field, fallback[field])))
                merged.setdefault("evidence", fallback.get("evidence", []))
                merged.setdefault("suggestions", fallback.get("suggestions", []))
                merged.setdefault("overall_reason", fallback.get("overall_reason", ""))
                merged["provider"] = "openai_compatible"
                merged["model"] = self.model
                return merged
        except Exception:
            return fallback
        return fallback

    def _evidence_from_failure_cases(
        self,
        failure_cases: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if failure_cases:
            return [
                {
                    "turn_index": item.get("turn_index", 1),
                    "issue": item.get("rule_name", ""),
                    "quote": item.get("dialogue_snippet") or item.get("evidence", ""),
                    "deduction": item.get("deduction_reason", ""),
                }
                for item in failure_cases[:6]
            ]
        if messages:
            first = messages[0]
            return [
                {
                    "turn_index": first.get("turn_index", 1),
                    "issue": "未发现明显硬规则失败",
                    "quote": first.get("assistant_message", ""),
                    "deduction": "无明显扣分，仅保留样例证据。",
                }
            ]
        return []

    def _repeat_penalty(self, messages: List[Dict[str, Any]]) -> float:
        replies = [item.get("assistant_message", "") for item in messages if item.get("assistant_message")]
        return 5 if len(replies) != len(set(replies)) else 0

    def _unanswered_penalty(self, messages: List[Dict[str, Any]]) -> float:
        penalty = 0.0
        for item in messages:
            user = item.get("user_message", "")
            assistant = item.get("assistant_message", "")
            if any(term in user for term in ["怎么", "哪里", "费用", "影响", "退出"]) and not assistant:
                penalty += 4
        return min(penalty, 8)

    def _clamp(self, value: float) -> float:
        return round(max(0, min(100, value)), 2)
