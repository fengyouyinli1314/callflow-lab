from __future__ import annotations

import json
import logging
import re
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
        retrieved_knowledge: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        retrieved_knowledge = retrieved_knowledge or self._knowledge_from_messages(full_messages)
        fallback = self._mock_evaluate(
            task_payload,
            case_payload,
            full_messages,
            rule_judge_result,
            retrieved_knowledge,
        )
        if self.provider != "openai_compatible":
            return fallback
        if not self.api_key or not self.base_url:
            fallback["provider_requested"] = "openai_compatible"
            fallback["fallback_used"] = True
            fallback["fallback_reason"] = "EVALUATOR_API_KEY or EVALUATOR_BASE_URL is not configured"
            return fallback

        content = self._call_openai_compatible(
            task_payload,
            case_payload,
            full_messages,
            rule_judge_result,
            retrieved_knowledge,
        )
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
        retrieved_knowledge: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        metrics = dict(rule_result.get("metrics", {}))
        failed_rules = list(rule_result.get("failed_rules", []))
        failure_cases = list(rule_result.get("failure_cases", []))
        evidence = self._evidence_from_failure_cases(failure_cases, messages)
        repeat_penalty = self._repeat_penalty(messages)
        unanswered_penalty = self._unanswered_penalty(messages)
        knowledge_assessment = self._knowledge_assessment(messages, retrieved_knowledge)
        active_visible_rules = self._active_visible_rules(rule_result)

        adjusted: Dict[str, float] = {}
        for field in METRIC_FIELDS:
            base = self._numeric_score(metrics.get(field, 70), 70)
            if field == "context_consistency":
                base -= repeat_penalty + unanswered_penalty
            if field == "response_quality":
                base -= repeat_penalty * 0.7
            if field in {"task_completion", "instruction_following", "call_flow_coverage"}:
                base -= min(12, len(knowledge_assessment["missed_knowledge"]) * 4)
            if field == "constraint_compliance":
                base -= min(18, len(knowledge_assessment["fabricated_knowledge"]) * 9)
            adjusted[field] = self._clamp(base)

        suggestions = list(rule_result.get("suggestions", []))
        if repeat_penalty:
            suggestions.append("减少机械重复，先承接用户本轮问题，再推进下一步。")
        if unanswered_penalty:
            suggestions.append("对用户追问的问题直接给出结论，避免只重复基础介绍。")
        if failed_rules:
            suggestions.append("围绕失败规则补齐话术：" + "、".join(failed_rules[:4]))
        if knowledge_assessment["missed_knowledge"]:
            titles = [item["title"] for item in knowledge_assessment["missed_knowledge"][:3]]
            suggestions.append("回答用户追问时优先使用已召回知识：" + "、".join(titles))
        if knowledge_assessment["fabricated_knowledge"]:
            suggestions.append("避免补充知识库外承诺或处理方式，先依据召回片段回答。")
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
            "knowledge_assessment": knowledge_assessment,
            "retrieved_knowledge": retrieved_knowledge,
            "active_visible_rules": active_visible_rules,
        }
        result["score"] = self._weighted_score(result)
        return result

    def _call_openai_compatible(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
        retrieved_knowledge: List[Dict[str, Any]],
    ) -> str:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": self._user_prompt(
                        task_payload,
                        case_payload,
                        messages,
                        rule_result,
                        retrieved_knowledge,
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
            "你还必须基于 retrieved_knowledge 判断模型是否使用了相关知识、是否遗漏关键知识、是否编造知识库外内容。"
            "你只能评价 rule_judge_result.active_visible_rules 中列出的当前用例规则；"
            "evidence.issue 不得使用 active_visible_rules 之外的规则名称，也不得自行发明失败规则。"
            "只输出合法 JSON，字段必须严格包含："
            "task_completion, instruction_following, call_flow_coverage, constraint_compliance, "
            "context_consistency, response_quality, overall_reason, evidence, suggestions, knowledge_assessment。"
            "evidence 每项必须包含 turn_index, issue, quote, deduction。"
        )

    def _user_prompt(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
        retrieved_knowledge: List[Dict[str, Any]],
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
                    "retrieved_knowledge": (item.get("detail") or {}).get("retrieved_knowledge", []),
                }
                for item in messages
            ],
            "retrieved_knowledge": retrieved_knowledge,
            "knowledge_judge_requirements": [
                "判断被测模型是否使用了与用户问题相关的 retrieved_knowledge。",
                "判断是否遗漏了召回片段中的关键事实。",
                "判断是否编造了 retrieved_knowledge 外的承诺、路径、价格或处理方式。",
            ],
            "rule_judge_result": {
                "score": rule_result.get("score", 0),
                "matched_rules": rule_result.get("matched_rules", []),
                "failed_rules": rule_result.get("failed_rules", []),
                "active_rules": rule_result.get("active_rules", {}),
                "active_visible_rules": self._active_visible_rules(rule_result),
                "case_focus": rule_result.get("case_focus", ""),
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
            merged[field] = self._clamp(self._numeric_score(merged.get(field, fallback[field]), fallback[field]))
        merged["overall_reason"] = str(merged.get("overall_reason") or fallback.get("overall_reason") or "")
        active_visible_rules = self._string_list(
            fallback.get("active_visible_rules"),
            [],
        )
        merged["evidence"] = self._normalize_evidence(
            merged.get("evidence"),
            fallback.get("evidence", []),
            active_visible_rules,
        )
        merged["failed_rules"] = [
            rule for rule in self._string_list(merged.get("failed_rules"), []) if rule in set(active_visible_rules)
        ]
        merged["suggestions"] = self._normalize_suggestions(merged.get("suggestions"), fallback.get("suggestions", []))
        merged["knowledge_assessment"] = self._normalize_knowledge_assessment(
            merged.get("knowledge_assessment"),
            fallback.get("knowledge_assessment", {}),
        )
        merged["retrieved_knowledge"] = fallback.get("retrieved_knowledge", [])
        merged["provider"] = "openai_compatible"
        merged["provider_requested"] = "openai_compatible"
        merged["model"] = self.model
        merged["fallback_used"] = False
        merged["score"] = self._weighted_score(merged)
        return merged

    def _normalize_evidence(
        self,
        value: Any,
        fallback: List[Dict[str, Any]],
        active_visible_rules: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        allowed = set(active_visible_rules or [])
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
            if allowed and row["issue"] not in allowed and "未发现" not in row["issue"]:
                continue
            if row["quote"] or row["deduction"]:
                normalized.append(row)
        return normalized[:8] or fallback

    def _active_visible_rules(self, rule_result: Dict[str, Any]) -> List[str]:
        values = list(rule_result.get("active_rule_names") or [])
        if not values:
            visible = rule_result.get("visible_business_rules") or {}
            values.extend(visible.get("matched") or [])
            values.extend(visible.get("failed") or [])
        if not values:
            active = rule_result.get("active_rules") or {}
            for key in ["global_rules", "stage_rules", "case_rules", "triggered_rules"]:
                values.extend(active.get(key) or [])
        return self._dedupe([str(item).strip() for item in values if str(item).strip()])

    def _normalize_suggestions(self, value: Any, fallback: List[str]) -> List[str]:
        rows = value if isinstance(value, list) else []
        suggestions = [str(item).strip() for item in rows if str(item).strip()]
        return self._dedupe(suggestions or fallback)

    def _normalize_knowledge_assessment(self, value: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return fallback
        return {
            "retrieved_titles": self._string_list(value.get("retrieved_titles"), fallback.get("retrieved_titles", [])),
            "used_knowledge": self._string_list(value.get("used_knowledge"), fallback.get("used_knowledge", [])),
            "missed_knowledge": value.get("missed_knowledge")
            if isinstance(value.get("missed_knowledge"), list)
            else fallback.get("missed_knowledge", []),
            "fabricated_knowledge": value.get("fabricated_knowledge")
            if isinstance(value.get("fabricated_knowledge"), list)
            else fallback.get("fabricated_knowledge", []),
        }

    def _string_list(self, value: Any, fallback: List[str]) -> List[str]:
        if not isinstance(value, list):
            return fallback
        return self._dedupe([str(item).strip() for item in value if str(item).strip()])

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

    def _knowledge_from_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in messages:
            detail = item.get("detail") or {}
            for chunk in detail.get("retrieved_knowledge") or []:
                title = str(chunk.get("title") or "")
                content = str(chunk.get("content") or "")
                key = (title, content)
                if not title or key in seen:
                    continue
                result.append(dict(chunk))
                seen.add(key)
        return result

    def _knowledge_assessment(
        self,
        messages: List[Dict[str, Any]],
        retrieved_knowledge: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in messages)
        retrieved_titles = self._dedupe([str(item.get("title") or "") for item in retrieved_knowledge])
        used_titles: List[str] = []
        missed: List[Dict[str, str]] = []
        for chunk in retrieved_knowledge:
            title = str(chunk.get("title") or "")
            if not title:
                continue
            if self._chunk_used(title, str(chunk.get("content") or ""), assistant_text):
                used_titles.append(title)
            else:
                missed.append(
                    {
                        "title": title,
                        "source": str(chunk.get("source") or ""),
                        "reason": "召回了相关知识，但被测模型回复中未稳定体现关键事实。",
                    }
                )
        fabricated = self._fabricated_knowledge(assistant_text)
        return {
            "retrieved_titles": retrieved_titles,
            "used_knowledge": self._dedupe(used_titles),
            "missed_knowledge": missed,
            "fabricated_knowledge": fabricated,
        }

    def _chunk_used(self, title: str, content: str, assistant_text: str) -> bool:
        checks = {
            "退出飞毛腿流程": ["App", "Z 点", "取消"],
            "恶劣天气与安全": ["安全", "雨天", "资格", "能跑"],
            "报名排名规则": ["排名", "站长"],
            "合同完成要求": ["X 单", "Y 单", "合同", "派单", "影响"],
            "额外奖励规则": ["奖励", "补贴", "不能承诺"],
            "标准直播与低延迟直播区别": ["5-10 秒", "1-2 秒", "标准", "低延迟"],
            "价格与费用说明": ["费用", "页面", "优惠券", "不能承诺"],
            "发布方式与配置路径": ["Web", "第三方", "直播平台管理", "勾选", "直接选择"],
            "企业微信添加逻辑": ["企业微信", "手机号", "私下", "泄露"],
            "开车场景处理约束": ["稍后再打", "开车", "注意安全", "不继续"],
            "忙碌商家处理约束": ["1 分钟", "简短", "说重点"],
        }
        keywords = checks.get(title)
        if keywords:
            hits = sum(1 for keyword in keywords if keyword in assistant_text)
            return hits >= min(2, len(keywords))
        content_terms = [term for term in re.split(r"[\s,，。；;：:、]+", content) if len(term) >= 2]
        return bool(content_terms) and sum(1 for term in content_terms[:6] if term in assistant_text) >= 2

    def _fabricated_knowledge(self, assistant_text: str) -> List[Dict[str, str]]:
        risky_terms = [
            "站长手动取消",
            "我帮你取消",
            "保证报上",
            "一定获得资格",
            "送优惠券",
            "承诺优惠",
            "私人微信",
            "私人手机号",
            "必须冒雨",
            "强制配送",
        ]
        return [
            {"term": term, "reason": "疑似补充召回知识外的承诺或处理方式。"}
            for term in risky_terms
            if term in assistant_text
        ]

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
        return round(sum(self._numeric_score(metrics.get(field, 0), 0) * SCORE_WEIGHTS[field] for field in METRIC_FIELDS), 2)

    def _numeric_score(self, value: Any, fallback: Any = 0) -> float:
        if isinstance(value, dict):
            for key in ["score", "value", "points", "分数"]:
                if key in value:
                    return self._numeric_score(value.get(key), fallback)
            return self._numeric_score(fallback, 0)
        if isinstance(value, (list, tuple)):
            return self._numeric_score(value[0], fallback) if value else self._numeric_score(fallback, 0)
        try:
            return float(value)
        except (TypeError, ValueError):
            try:
                return float(fallback)
            except (TypeError, ValueError):
                return 0.0

    def _clamp(self, value: float) -> float:
        return round(max(0, min(100, value)), 2)

    def _dedupe(self, values: List[str]) -> List[str]:
        return list(dict.fromkeys([item for item in values if item]))
