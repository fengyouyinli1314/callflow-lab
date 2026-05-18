from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List

from app.core.config import settings
from app.services.rule_judge import SCORE_WEIGHTS


logger = logging.getLogger(__name__)

METRIC_FIELDS = [
    "task_completion",
    "instruction_following",
    "call_flow_coverage",
    "constraint_compliance",
    "context_consistency",
    "response_quality",
]

DEFAULT_EVALUATOR_MODEL = "mock-evaluator"


class EvaluatorAgent:
    """LLM-as-a-Judge evaluator focused only on the evaluated model's behavior."""

    def __init__(self) -> None:
        provider = (settings.evaluator_provider or "mock").strip().lower()
        self.provider = provider if provider in {"mock", "openai_compatible"} else "mock"
        self.api_key = settings.evaluator_api_key or ""
        self.base_url = (settings.evaluator_base_url or "").rstrip("/")
        self.model = (settings.evaluator_model or DEFAULT_EVALUATOR_MODEL).strip() or DEFAULT_EVALUATOR_MODEL

    def evaluate(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        full_messages: List[Dict[str, Any]],
        rule_judge_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        fallback = self._mock_evaluate(task_payload, case_payload, full_messages, rule_judge_result)
        if self.provider != "openai_compatible":
            return fallback
        if not self.api_key or not self.base_url:
            fallback["provider_requested"] = "openai_compatible"
            fallback["fallback_used"] = True
            fallback["fallback_reason"] = "EVALUATOR_API_KEY or EVALUATOR_BASE_URL is not configured"
            return fallback

        content = self._call_openai_compatible(task_payload, case_payload, full_messages, rule_judge_result)
        if not content:
            fallback["provider_requested"] = "openai_compatible"
            fallback["fallback_used"] = True
            fallback["fallback_reason"] = "openai_compatible evaluator returned empty or invalid response"
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
        failed_rules = list(rule_result.get("failed_rules", []))
        failure_cases = list(rule_result.get("failure_cases", []))
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

        suggestions = list(rule_result.get("suggestions", []))
        if repeat_penalty:
            suggestions.append("减少机械重复，先承接用户本轮问题，再推进下一步。")
        if unanswered_penalty:
            suggestions.append("对用户追问的问题直接给出结论，避免只重复基础介绍。")
        if failed_rules:
            suggestions.append("围绕失败规则补齐话术：" + "、".join(failed_rules[:4]))
        if not suggestions:
            suggestions.append("保持当前任务指令覆盖方式，继续关注高风险分支。")

        result = {
            **adjusted,
            "overall_reason": (
                "mock evaluator 基于规则评分结果生成语义评估兜底："
                f"命中 {len(rule_result.get('matched_rules', []))} 条规则，失败 {len(failed_rules)} 条。"
            ),
            "evidence": evidence,
            "suggestions": self._dedupe(suggestions),
            "provider": "mock",
            "provider_requested": self.provider,
            "model": self.model,
            "fallback_used": False,
        }
        result["score"] = self._weighted_score(result)
        return result

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
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(task_payload, case_payload, messages, rule_result)},
            ],
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            logger.warning("evaluator openai_compatible request failed: %s", exc)
            return ""

        if isinstance(data, dict):
            choices = data.get("choices")
            if choices and isinstance(choices, list):
                return str(choices[0].get("message", {}).get("content", "") or "")
            for key in ["content", "text", "message", "output_text"]:
                if data.get(key):
                    return str(data[key])
        return ""

    def _system_prompt(self) -> str:
        return (
            "你是 callflow-lab 的 LLM-as-a-Judge 评估器。"
            "你的任务是评估“被测对话模型”在复杂外呼任务指令下的表现。"
            "只评价被测模型的回复质量、任务完成度、指令遵循、流程覆盖、约束遵守、上下文一致性。"
            "不要评价用户模拟器，不要评价用户是否配合，不要评价系统代码、平台实现或测试框架。"
            "必须给出 0-100 分的六项指标分，必须给出扣分原因，必须引用对话证据，必须给出优化建议。"
            "证据 quote 必须来自 full_messages 中的用户或被测模型原话。"
            "不允许只输出一句总结，不允许输出 Markdown。"
            "只输出合法 JSON，字段必须严格包含："
            "task_completion, instruction_following, call_flow_coverage, constraint_compliance, "
            "context_consistency, response_quality, overall_reason, evidence, suggestions。"
            "evidence 每项必须包含 turn_index, issue, quote, deduction。"
        )

    def _user_prompt(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> str:
        payload = {
            "instruction_text": task_payload.get("instruction_text", ""),
            "task_type": task_payload.get("task_type", ""),
            "case": {
                "name": case_payload.get("name", ""),
                "user_profile": case_payload.get("user_profile", ""),
                "initial_message": case_payload.get("initial_message", ""),
                "expected_goals": case_payload.get("expected_goals", []),
                "required_rules": case_payload.get("required_rules", []),
                "forbidden_rules": case_payload.get("forbidden_rules", []),
                "trigger_conditions": case_payload.get("trigger_conditions", []),
                "expected_final_state": case_payload.get("expected_final_state", ""),
                "user_behavior_type": case_payload.get("user_behavior_type", ""),
            },
            "full_messages": [
                {
                    "turn_index": item.get("turn_index"),
                    "user_message": item.get("user_message", ""),
                    "assistant_message": item.get("assistant_message", ""),
                    "latency_ms": item.get("latency_ms", 0),
                }
                for item in messages
            ],
            "rule_judge_result": {
                "score": rule_result.get("score", 0),
                "matched_rules": rule_result.get("matched_rules", []),
                "failed_rules": rule_result.get("failed_rules", []),
                "active_rules": rule_result.get("active_rules", {}),
                "pending_rules": rule_result.get("pending_rules", []),
                "failure_cases": rule_result.get("failure_cases", []),
                "metric_explanations": rule_result.get("metric_explanations", []),
            },
            "score_schema": {
                "task_completion": "0-100，任务目标完成程度",
                "instruction_following": "0-100，是否遵守任务指令和用例规则",
                "call_flow_coverage": "0-100，当前对话应覆盖流程节点的覆盖度",
                "constraint_compliance": "0-100，是否避免禁止项、越权、串场和安全风险",
                "context_consistency": "0-100，是否承接上下文、避免重复和答非所问",
                "response_quality": "0-100，话术是否简短、自然、可执行",
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    def _safe_json(self, content: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                return fallback
            data = json.loads(content[start : end + 1])
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
        return self._normalize_llm_result(data, fallback)

    def _normalize_llm_result(self, data: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
        merged = {**fallback, **data}
        for field in METRIC_FIELDS:
            merged[field] = self._clamp(float(merged.get(field, fallback[field])))
        merged["overall_reason"] = str(merged.get("overall_reason") or fallback.get("overall_reason") or "")
        merged["evidence"] = self._normalize_evidence(merged.get("evidence"), fallback.get("evidence", []))
        merged["suggestions"] = self._normalize_suggestions(merged.get("suggestions"), fallback.get("suggestions", []))
        merged["provider"] = "openai_compatible"
        merged["provider_requested"] = "openai_compatible"
        merged["model"] = self.model
        merged["fallback_used"] = False
        merged["score"] = self._weighted_score(merged)
        return merged

    def _normalize_evidence(self, value: Any, fallback: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = value if isinstance(value, list) else []
        normalized: List[Dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            try:
                turn_index = int(item.get("turn_index") or 1)
            except (TypeError, ValueError):
                turn_index = 1
            row = {
                "turn_index": turn_index,
                "issue": str(item.get("issue") or item.get("rule_name") or "语义评估扣分点"),
                "quote": str(item.get("quote") or item.get("evidence") or ""),
                "deduction": str(item.get("deduction") or item.get("deduction_reason") or ""),
            }
            if row["quote"] or row["deduction"]:
                normalized.append(row)
        return normalized[:8] or fallback

    def _normalize_suggestions(self, value: Any, fallback: List[str]) -> List[str]:
        rows = value if isinstance(value, list) else []
        suggestions = [str(item).strip() for item in rows if str(item).strip()]
        return self._dedupe(suggestions or fallback)

    def _evidence_from_failure_cases(
        self,
        failure_cases: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if failure_cases:
            return [
                {
                    "turn_index": item.get("turn_index", 1),
                    "issue": item.get("rule_name", "") or "规则失败",
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
                    "deduction": "无明显扣分，保留首轮被测模型回复作为语义评估证据。",
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

    def _weighted_score(self, metrics: Dict[str, Any]) -> float:
        return round(sum(float(metrics.get(field, 0)) * SCORE_WEIGHTS[field] for field in METRIC_FIELDS), 2)

    def _clamp(self, value: float) -> float:
        return round(max(0, min(100, value)), 2)

    def _dedupe(self, values: List[str]) -> List[str]:
        return list(dict.fromkeys([item for item in values if item]))
