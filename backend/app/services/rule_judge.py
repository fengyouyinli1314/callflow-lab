from __future__ import annotations

from typing import Any, Dict, List, Tuple


class RuleJudge:
    def score_turn(
        self,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        latency_ms: float,
    ) -> Dict[str, Any]:
        assistant_text = "\n".join(item["assistant_message"] for item in history)
        matched, missed = self._match_required(case_payload.get("required_rules", []), assistant_text)
        violated = self._match_forbidden(case_payload.get("forbidden_rules", []), assistant_text)
        required_count = max(len(case_payload.get("required_rules", [])), 1)
        score = max(0, 100 * len(matched) / required_count - len(violated) * 18)
        return {
            "score": round(min(score, 100), 2),
            "reason": f"已命中 {len(matched)} 条规则，遗漏 {len(missed)} 条，违规 {len(violated)} 条。",
            "matched_rules": matched,
            "missed_rules": missed,
            "violated_rules": violated,
            "avg_latency_ms": latency_ms,
        }

    def evaluate_conversation(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        assistant_text = "\n".join(item["assistant_message"] for item in messages)
        matched_rules, missed_rules = self._match_required(case_payload.get("required_rules", []), assistant_text)
        violated_rules = self._match_forbidden(case_payload.get("forbidden_rules", []), assistant_text)
        avg_latency_ms = round(
            sum(item.get("latency_ms", 0) for item in messages) / max(len(messages), 1),
            2,
        )

        required_count = max(len(case_payload.get("required_rules", [])), 1)
        task_completion = round(100 * len(matched_rules) / required_count, 2)
        instruction_following = round(max(0, 100 - len(missed_rules) * 12 - len(violated_rules) * 18), 2)
        context_consistency = self._context_score(messages)
        safety_compliance = round(max(0, 100 - len(violated_rules) * 30), 2)
        response_quality = self._quality_score(messages, matched_rules)
        score = round(
            task_completion * 0.28
            + instruction_following * 0.24
            + context_consistency * 0.18
            + safety_compliance * 0.16
            + response_quality * 0.14,
            2,
        )

        failed_rules = missed_rules + violated_rules
        failure_cases = self._build_failure_cases(missed_rules, violated_rules, messages)
        metric_details = self._build_metric_details(
            {
                "task_completion": task_completion,
                "instruction_following": instruction_following,
                "context_consistency": context_consistency,
                "safety_compliance": safety_compliance,
                "response_quality": response_quality,
            },
            missed_rules,
            violated_rules,
            messages,
        )
        suggestions = self._build_suggestions(missed_rules, violated_rules)
        explainability = {
            "overall_reason": (
                f"本次评测完成 {len(messages)} 轮对话，命中 {len(matched_rules)} 条关键规则，"
                f"遗漏 {len(missed_rules)} 条，触发违规 {len(violated_rules)} 条。"
            ),
            "score_breakdown": {
                "task_completion": task_completion,
                "instruction_following": instruction_following,
                "context_consistency": context_consistency,
                "safety_compliance": safety_compliance,
                "response_quality": response_quality,
            },
            "key_findings": self._build_key_findings(matched_rules, missed_rules, violated_rules),
            "improvement_suggestions": suggestions,
        }

        return {
            "score": score,
            "metrics": {
                "task_completion": task_completion,
                "instruction_following": instruction_following,
                "context_consistency": context_consistency,
                "safety_compliance": safety_compliance,
                "response_quality": response_quality,
                "avg_latency_ms": avg_latency_ms,
            },
            "matched_rules": matched_rules,
            "missed_rules": missed_rules,
            "violated_rules": violated_rules,
            "failed_rules": failed_rules,
            "suggestions": suggestions,
            "failure_cases": failure_cases,
            "metric_details": metric_details,
            "explainability": explainability,
        }

    def _match_required(self, rules: List[str], assistant_text: str) -> Tuple[List[str], List[str]]:
        matched: List[str] = []
        missed: List[str] = []
        for rule in rules:
            keywords = self._required_keywords(rule)
            if any(keyword in assistant_text for keyword in keywords):
                matched.append(rule)
            else:
                missed.append(rule)
        return matched, missed

    def _match_forbidden(self, rules: List[str], assistant_text: str) -> List[str]:
        violated: List[str] = []
        for rule in rules:
            keywords = self._forbidden_keywords(rule)
            if any(keyword in assistant_text for keyword in keywords):
                violated.append(rule)
        return violated

    def _required_keywords(self, rule: str) -> List[str]:
        mapping = {
            "订单号": ["订单号", "订单信息", "订单"],
            "订单信息": ["订单信息", "订单号", "原订单"],
            "时效": ["时效", "工作日", "处理时间", "反馈"],
            "安抚": ["抱歉", "理解", "安抚", "着急", "不好"],
            "入住日期": ["入住日期", "新入住日期", "日期"],
            "房型": ["房型", "库存"],
            "差价": ["差价", "费用"],
            "券状态": ["券状态", "已使用", "冻结"],
            "门店": ["门店", "适用范围"],
            "有效期": ["有效期", "有效"],
            "下一步": ["下一步", "工单", "建议", "处理建议"],
        }
        keywords = [rule]
        for key, values in mapping.items():
            if key in rule:
                keywords.extend(values)
        return list(dict.fromkeys(keywords))

    def _forbidden_keywords(self, rule: str) -> List[str]:
        mapping = {
            "直接承诺退款": ["保证退款成功", "一定退款", "马上退款", "直接退款成功"],
            "跳过核实": ["无需核实", "不用核实", "不需要订单"],
            "承诺免费": ["一定免费", "保证免费"],
            "绕过平台": ["绕过平台", "私下处理"],
            "忽视有效期": ["不用看有效期", "过期也能用"],
        }
        keywords = [rule]
        for key, values in mapping.items():
            if key in rule:
                keywords.extend(values)
        return list(dict.fromkeys(keywords))

    def _context_score(self, messages: List[Dict[str, Any]]) -> float:
        if not messages:
            return 0
        assistant_text = "\n".join(item["assistant_message"] for item in messages)
        penalty = 0
        if "不知道" in assistant_text:
            penalty += 10
        if "无法处理" in assistant_text:
            penalty += 8
        if len({item["assistant_message"] for item in messages}) < max(1, len(messages) // 2):
            penalty += 6
        return round(max(70, 96 - penalty), 2)

    def _quality_score(self, messages: List[Dict[str, Any]], matched_rules: List[str]) -> float:
        assistant_text = "\n".join(item["assistant_message"] for item in messages)
        score = 78 + min(16, len(matched_rules) * 4)
        if "请" in assistant_text or "麻烦" in assistant_text:
            score += 2
        if "下一步" in assistant_text or "处理结果" in assistant_text:
            score += 2
        return round(min(score, 100), 2)

    def _build_failure_cases(
        self,
        missed_rules: List[str],
        violated_rules: List[str],
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        cases: List[Dict[str, Any]] = []
        evidence_message = messages[0] if messages else {}
        for rule in missed_rules:
            cases.append(
                {
                    "rule_name": rule,
                    "severity": "high",
                    "turn_index": evidence_message.get("turn_index", 1),
                    "evidence": f"全程未稳定体现规则：{rule}",
                    "dialogue_snippet": evidence_message.get("assistant_message", ""),
                    "suggestion": f"在相关业务流程中补充“{rule}”的明确话术和校验动作。",
                }
            )
        for rule in violated_rules:
            turn = self._find_violation_turn(rule, messages)
            cases.append(
                {
                    "rule_name": rule,
                    "severity": "high",
                    "turn_index": turn.get("turn_index", 1),
                    "evidence": f"客服回复疑似触发禁止规则：{rule}",
                    "dialogue_snippet": turn.get("assistant_message", ""),
                    "suggestion": f"在生成回复前增加“{rule}”拦截，避免未核实前给出确定性承诺。",
                }
            )
        return cases

    def _build_metric_details(
        self,
        metrics: Dict[str, float],
        missed_rules: List[str],
        violated_rules: List[str],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        first = messages[0] if messages else {"turn_index": 1, "assistant_message": ""}
        last = messages[-1] if messages else first
        return {
            "task_completion": {
                "score": metrics["task_completion"],
                "deduction_reason": "未覆盖全部期望目标。" if missed_rules else "关键任务目标覆盖完整。",
                "evidence_turns": [first.get("turn_index", 1)],
                "evidence_snippets": [first.get("assistant_message", "")],
                "suggestion": "补齐遗漏目标：" + "、".join(missed_rules) if missed_rules else "保持现有任务推进结构。",
            },
            "instruction_following": {
                "score": metrics["instruction_following"],
                "deduction_reason": "存在遗漏规则或禁止规则风险。" if missed_rules or violated_rules else "指令遵循稳定。",
                "evidence_turns": [item.get("turn_index", 1) for item in messages[:2]],
                "evidence_snippets": [item.get("assistant_message", "") for item in messages[:2]],
                "suggestion": "把必须动作前置为流程检查项，并对禁止承诺做生成前校验。",
            },
            "context_consistency": {
                "score": metrics["context_consistency"],
                "deduction_reason": "多轮回复上下文基本连续，若重复表达较多会少量扣分。",
                "evidence_turns": [last.get("turn_index", 1)],
                "evidence_snippets": [last.get("assistant_message", "")],
                "suggestion": "在每轮回复中承接用户新增信息，减少模板化重复。",
            },
            "safety_compliance": {
                "score": metrics["safety_compliance"],
                "deduction_reason": "触发禁止规则。" if violated_rules else "未发现明显安全合规违规。",
                "evidence_turns": [first.get("turn_index", 1)],
                "evidence_snippets": [first.get("assistant_message", "")],
                "suggestion": "对退款、费用、权益类承诺统一增加核实后再确认的限制。",
            },
            "response_quality": {
                "score": metrics["response_quality"],
                "deduction_reason": "回复质量取决于是否说明下一步、时效和所需信息。",
                "evidence_turns": [last.get("turn_index", 1)],
                "evidence_snippets": [last.get("assistant_message", "")],
                "suggestion": "使用“已核实信息-待补充信息-处理时效-下一步动作”的结构化话术。",
            },
        }

    def _build_suggestions(self, missed_rules: List[str], violated_rules: List[str]) -> List[str]:
        suggestions = [
            "将业务必问项配置为逐轮检查清单，避免多轮对话中遗漏。",
            "在回复末尾固定输出处理时效、下一步动作和用户需补充的信息。",
        ]
        if missed_rules:
            suggestions.append("针对遗漏规则补充示例话术：" + "、".join(missed_rules))
        if violated_rules:
            suggestions.append("对禁止规则增加拦截模板：" + "、".join(violated_rules))
        return suggestions

    def _build_key_findings(
        self,
        matched_rules: List[str],
        missed_rules: List[str],
        violated_rules: List[str],
    ) -> List[str]:
        findings = [f"已命中规则：{len(matched_rules)} 条"]
        if missed_rules:
            findings.append("遗漏规则：" + "、".join(missed_rules))
        if violated_rules:
            findings.append("违规风险：" + "、".join(violated_rules))
        if not missed_rules and not violated_rules:
            findings.append("对话模型能够稳定完成关键客服流程。")
        return findings

    def _find_violation_turn(self, rule: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        keywords = self._forbidden_keywords(rule)
        for item in messages:
            if any(keyword in item.get("assistant_message", "") for keyword in keywords):
                return item
        return messages[0] if messages else {}
