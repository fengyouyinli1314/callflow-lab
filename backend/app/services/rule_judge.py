from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from app.services.course_flow import course_full_flow_expected_steps, course_full_flow_step_done
from app.services.rider_flow import rider_full_flow_expected_steps, rider_rank_qualification_done

from app.services.dialogue_state import is_similar_text


SCORE_WEIGHTS = {
    "task_completion": 0.25,
    "instruction_following": 0.20,
    "call_flow_coverage": 0.20,
    "constraint_compliance": 0.15,
    "context_consistency": 0.10,
    "response_quality": 0.10,
}

METRIC_NAMES = {
    "task_completion": "任务完成度",
    "instruction_following": "指令遵循率",
    "call_flow_coverage": "外呼流程覆盖率",
    "constraint_compliance": "约束遵守率",
    "context_consistency": "上下文一致性",
    "response_quality": "回复质量",
}



RIDER_HIDDEN_GUARDRAIL_RULES = [
    "禁止串用课程直播场景",
]

COURSE_HIDDEN_GUARDRAIL_RULES = [
    "禁止串用飞毛腿场景",
]

RIDER_CASE_FOCUS_RULES = {
    "normal_delivery": {
        "required": ["是否确认骑手身份", "是否告知飞毛腿合同已生效", "是否询问是否可以开始配送", "是否说明单日/多日合同完成要求", "是否根据骑手态度鼓励挽留或安抚", "是否回复自然简短"],
        "forbidden": [],
    },
    "unwilling_delivery": {
        "required": [
            "是否安抚不想配送或情绪不满的骑手",
            "是否说明许多骑手正在申请且名额可能被占用",
            "是否说明单日/多日合同完成要求",
            "是否说明不完成可能影响合同或派单",
            "是否说明连续完成多日合同可能有额外奖励",
            "是否根据骑手态度鼓励挽留或安抚",
            "是否避免强迫冒险配送",
            "是否回复自然简短",
        ],
        "forbidden": [],
    },
    "contract_impact": {
        "required": ["是否说明单日/多日合同完成要求", "是否说明不完成可能影响合同或派单", "是否避免夸大处罚", "是否回复自然简短"],
        "forbidden": [],
    },
    "exit_flying_leg": {
        "required": ["是否说明前一天 Z 点前取消", "是否说明在 App 的“飞毛腿报名”中取消", "是否说明次日生效", "是否避免编造其他退出方式", "是否回复自然简短"],
        "forbidden": [],
    },
    "bad_weather": {
        "required": ["是否先安抚", "是否提醒安全", "是否说明雨天订单更多或完成有助于资格", "是否避免强迫冒险配送", "是否回复自然简短"],
        "forbidden": [],
    },
    "ranking_question": {
        "required": ["是否说明报名按排名进行", "是否说明不是站长干预", "是否提醒减少拒单取消超时有助于保住资格", "是否避免承诺一定获得资格", "是否回复自然简短"],
        "forbidden": [],
    },
    "reward_question": {
        "required": ["是否说明连续完成多日合同可能有额外奖励", "是否避免编造具体金额", "是否回复自然简短"],
        "forbidden": [],
    },
}

COURSE_CASE_FOCUS_RULES = {
    "responsible_person": {
        "required": ["是否识别负责人", "是否进入产品升级说明", "是否回复简短自然", "是否给商家发言机会"],
        "forbidden": [],
    },
    "non_responsible_person": {
        "required": ["是否请对方转达", "是否简短说明升级内容", "是否避免强行推销", "是否回复简短自然"],
        "forbidden": [],
    },
    "busy_merchant": {
        "required": ["是否说“就1分钟，保证简短”", "是否继续简短说明重点", "是否给商家发言机会"],
        "forbidden": [],
    },
    "driving_merchant": {
        "required": ["是否说“那我稍后再打”", "是否立即结束", "是否不继续推销"],
        "forbidden": [],
    },
    "live_type_difference": {
        "required": ["是否说明标准直播延迟 5-10 秒、费用较低", "是否说明低延迟直播延迟 1-2 秒、互动更流畅", "是否回复简短自然", "是否给商家发言机会"],
        "forbidden": [],
    },
    "third_party_config_missing": {
        "required": ["是否识别第三方系统场景", "是否按第三方系统配置路径引导", "若仍看不到，是否说明后台可能未配置并请明天查看"],
        "forbidden": [],
    },
    "fee_or_coupon": {
        "required": ["是否说明低延迟可能费用更高", "是否禁止承诺优惠券或折扣", "是否避免编造价格"],
        "forbidden": [],
    },
}


class RuleJudge:
    def score_turn(
        self,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        latency_ms: float,
        task_payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        result = self._evaluate_rules(task_payload or {}, case_payload, history)
        result = self._apply_turn_rule_lifecycle(task_payload or {}, case_payload, history, result)
        required_count = max(len(result.get("required_rules", [])), 1)
        hidden_violated = result.get("hidden_guardrail_rules", {}).get("violated", [])
        score = (
            100 * len(result["matched_rules"]) / required_count
            - len(result["violated_rules"]) * 22
            - len(hidden_violated) * 18
        )
        score = self._clamp(score - self._repetition_penalty(history) * 0.5)
        return {
            "score": round(score, 2),
            "reason": (
                f"已命中 {len(result['matched_rules'])} 条业务规则，"
                f"遗漏 {len(result['missed_rules'])} 条，业务违规 {len(result['violated_rules'])} 条，"
                f"防串场违规 {len(hidden_violated)} 条。"
            ),
            "matched_rules": result["matched_rules"],
            "missed_rules": result["missed_rules"],
            "violated_rules": result["violated_rules"],
            "failed_rules": result["failed_rules"],
            "visible_business_rules": result["visible_business_rules"],
            "hidden_guardrail_rules": result["hidden_guardrail_rules"],
            "case_focus": result["case_focus"],
            "active_rule_names": result["active_rule_names"],
            "active_rules": result["active_rules"],
            "pending_rules": result["pending_rules"],
            "untriggered_rules": result["untriggered_rules"],
            "not_applicable_rules": result["not_applicable_rules"],
            "late_satisfied_rules": result.get("late_satisfied_rules", []),
            "rule_lifecycle": result.get("rule_lifecycle", {}),
            "current_stage": result["current_stage"],
            "deduction_reason": result["deduction_reason"],
            "active_rules_explanation": self._active_rules_explanation(),
            "avg_latency_ms": latency_ms,
        }

    def evaluate_conversation(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        rule_result = self._evaluate_rules(task_payload, case_payload, messages)
        rule_result = self._apply_full_flow_expected_steps(task_payload, case_payload, messages, rule_result)
        late_satisfied_rules = self._late_satisfied_rules(task_payload, case_payload, messages, rule_result)
        if late_satisfied_rules:
            rule_result["late_satisfied_rules"] = late_satisfied_rules
            rule_result.setdefault("visible_business_rules", {})["late_satisfied"] = late_satisfied_rules
            rule_result.setdefault("rule_lifecycle", {})["late_satisfied"] = late_satisfied_rules
        matched_rules = rule_result["matched_rules"]
        missed_rules = rule_result["missed_rules"]
        violated_rules = rule_result["violated_rules"]
        hidden_violated_rules = rule_result.get("hidden_guardrail_rules", {}).get("violated", [])
        total_violation_count = len(violated_rules) + len(hidden_violated_rules)
        required_count = max(len(rule_result.get("required_rules", [])), 1)
        call_flow_count = max(len(rule_result.get("call_flow_rules", [])), 1)
        matched_call_flow = [
            rule for rule in matched_rules if rule in set(rule_result.get("call_flow_rules", []))
        ]
        coverage = len(matched_rules) / required_count
        call_flow_ratio = len(matched_call_flow) / call_flow_count
        avg_latency_ms = round(
            sum(float(item.get("latency_ms", 0)) for item in messages) / max(len(messages), 1),
            2,
        )

        repetition_penalty = self._repetition_penalty(messages)
        unanswered_penalty = self._unanswered_penalty(messages)
        brevity_penalty = self._brevity_penalty(messages, self._task_type(task_payload, case_payload))
        late_penalty = min(6, len(late_satisfied_rules) * 2)
        next_step_penalty = 0 if self._has_any(self._assistant_text(messages), ["下一步", "建议", "提交", "反馈", "处理结果", "稍后再打", "提醒到这里"]) else 8

        task_completion = self._clamp(45 + coverage * 55 - next_step_penalty)
        instruction_following = self._clamp(100 - len(missed_rules) * 8 - total_violation_count * 18 - late_penalty)
        call_flow_coverage = self._clamp(45 + call_flow_ratio * 55 - max(0, len(rule_result.get("call_flow_rules", [])) - len(matched_call_flow)) * 3 - late_penalty * 0.5)
        constraint_compliance = self._clamp(100 - total_violation_count * 22 - self._risk_phrase_penalty(messages) - brevity_penalty)
        context_consistency = self._clamp(96 - repetition_penalty - unanswered_penalty)
        response_quality = self._clamp(
            90
            + min(6, len(matched_rules) * 1.5)
            - repetition_penalty
            - next_step_penalty
            - brevity_penalty * 0.6
            - late_penalty * 0.5
        )
        metrics = {
            "task_completion": task_completion,
            "instruction_following": instruction_following,
            "call_flow_coverage": call_flow_coverage,
            "constraint_compliance": constraint_compliance,
            "context_consistency": context_consistency,
            "response_quality": response_quality,
            "avg_latency_ms": avg_latency_ms,
            "failed_rule_count": len(missed_rules) + len(violated_rules),
            "safety_compliance": constraint_compliance,
        }
        score = self._weighted_score(metrics)

        failed_rules = missed_rules + violated_rules
        failure_cases = self._build_failure_cases(rule_result, messages)
        metric_details = self._build_metric_details(
            metrics,
            rule_result,
            messages,
            {
                "repetition_penalty": repetition_penalty,
                "unanswered_penalty": unanswered_penalty,
                "next_step_penalty": next_step_penalty,
                "brevity_penalty": brevity_penalty,
            },
        )
        metric_explanations = self._metric_explanations(metric_details)
        evidence_messages = self._build_evidence_messages(rule_result, messages)
        score_formula = self._build_score_formula(metrics, score)
        suggestions = self._build_suggestions(missed_rules, violated_rules, repetition_penalty, unanswered_penalty)
        explainability = {
            "overall_reason": (
                f"本次评测完成 {len(messages)} 轮对话，命中 {len(matched_rules)} 条关键规则，"
                f"遗漏 {len(missed_rules)} 条，触发业务违规 {len(violated_rules)} 条，"
                f"防串场违规 {len(hidden_violated_rules)} 条；"
                f"综合得分 {score}。"
            ),
            "active_rules_explanation": self._active_rules_explanation(),
            "visible_business_rules": rule_result["visible_business_rules"],
            "hidden_guardrail_rules": rule_result["hidden_guardrail_rules"],
            "case_focus": rule_result["case_focus"],
            "full_flow_expected_steps": rule_result.get("full_flow_expected_steps", {}),
            "active_rule_names": rule_result["active_rule_names"],
            "deduction_reason": rule_result["deduction_reason"],
            "score_breakdown": {
                "task_completion": task_completion,
                "instruction_following": instruction_following,
                "call_flow_coverage": call_flow_coverage,
                "constraint_compliance": constraint_compliance,
                "context_consistency": context_consistency,
                "response_quality": response_quality,
                "failed_rule_count": len(failed_rules),
            },
            "key_findings": self._build_key_findings(matched_rules, missed_rules, violated_rules, repetition_penalty),
            "improvement_suggestions": suggestions,
            "score_formula": score_formula,
            "evidence_summary": evidence_messages,
            "active_rules": rule_result["active_rules"],
            "active_rule_names": rule_result["active_rule_names"],
            "pending_rules": rule_result["pending_rules"],
            "untriggered_rules": rule_result["untriggered_rules"],
            "current_stage": rule_result["current_stage"],
            "case_focus": rule_result["case_focus"],
            "full_flow_expected_steps": rule_result.get("full_flow_expected_steps", {}),
            "late_satisfied_rules": late_satisfied_rules,
            "rule_lifecycle": rule_result.get("rule_lifecycle", {}),
        }

        return {
            "score": score,
            "metrics": metrics,
            "matched_rules": matched_rules,
            "missed_rules": missed_rules,
            "violated_rules": violated_rules,
            "failed_rules": failed_rules,
            "visible_business_rules": rule_result["visible_business_rules"],
            "hidden_guardrail_rules": rule_result["hidden_guardrail_rules"],
            "case_focus": rule_result["case_focus"],
            "full_flow_expected_steps": rule_result.get("full_flow_expected_steps", {}),
            "active_rule_names": rule_result["active_rule_names"],
            "active_rules": rule_result["active_rules"],
            "pending_rules": rule_result["pending_rules"],
            "untriggered_rules": rule_result["untriggered_rules"],
            "not_applicable_rules": rule_result["not_applicable_rules"],
            "late_satisfied_rules": late_satisfied_rules,
            "rule_lifecycle": rule_result.get("rule_lifecycle", {}),
            "current_stage": rule_result["current_stage"],
            "deduction_reason": rule_result["deduction_reason"],
            "active_rules_explanation": self._active_rules_explanation(),
            "suggestions": suggestions,
            "failure_cases": failure_cases,
            "metric_details": metric_details,
            "metric_explanations": metric_explanations,
            "explainability": explainability,
            "evidence_messages": evidence_messages,
            "score_formula": score_formula,
        }

    def _evaluate_rules(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        matched_rules: List[str] = []
        missed_rules: List[str] = []
        violated_rules: List[str] = []
        matched_evidence: Dict[str, Dict[str, Any]] = {}
        missed_evidence: Dict[str, Dict[str, Any]] = {}
        violated_evidence: Dict[str, Dict[str, Any]] = {}
        hidden_violated_rules: List[str] = []
        hidden_passed_rules: List[str] = []
        hidden_violated_evidence: Dict[str, Dict[str, Any]] = {}
        active = self._active_rule_sets(task_payload, case_payload, messages)
        required_rules = active["required_rules"]
        forbidden_rules = active["forbidden_rules"]
        hidden_guardrail_rules = active.get("hidden_guardrail_rules", [])

        for rule in required_rules:
            evidence = self._find_required_evidence(rule, messages, task_payload, case_payload)
            if evidence:
                matched_rules.append(rule)
                matched_evidence[rule] = evidence
            else:
                missed_rules.append(rule)
                missed_evidence[rule] = self._fallback_evidence(messages)

        for rule in forbidden_rules:
            evidence = self._find_forbidden_evidence(rule, messages, task_payload, case_payload)
            if evidence:
                violated_rules.append(rule)
                violated_evidence[rule] = evidence

        for rule in hidden_guardrail_rules:
            evidence = self._find_forbidden_evidence(rule, messages, task_payload, case_payload)
            if evidence:
                hidden_violated_rules.append(rule)
                hidden_violated_evidence[rule] = evidence
            else:
                hidden_passed_rules.append(rule)

        failed_rules = missed_rules + violated_rules
        deduction_reason = self._deduction_reason(missed_rules, violated_rules, hidden_violated_rules)
        visible_business_rules = {
            "matched": matched_rules,
            "failed": failed_rules,
            "pending": active["pending_rules"],
            "untriggered": active.get("visible_untriggered_rules", []),
        }
        hidden_guardrail_result = {
            "violated": hidden_violated_rules,
            "passed": hidden_passed_rules,
            "evidence": hidden_violated_evidence,
        }

        return {
            "required_rules": required_rules,
            "forbidden_rules": forbidden_rules,
            "hidden_guardrail_rule_names": hidden_guardrail_rules,
            "call_flow_rules": active["call_flow_rules"],
            "active_rules": active["active_rules"],
            "active_rule_names": active["active_rule_names"],
            "pending_rules": active["pending_rules"],
            "not_applicable_rules": active["not_applicable_rules"],
            "current_stage": active["current_stage"],
            "case_focus": active["case_focus"],
            "matched_rules": matched_rules,
            "missed_rules": missed_rules,
            "violated_rules": violated_rules,
            "failed_rules": failed_rules,
            "visible_business_rules": visible_business_rules,
            "hidden_guardrail_rules": hidden_guardrail_result,
            "rule_lifecycle": {
                "satisfied": matched_rules,
                "pending": active["pending_rules"],
                "late_satisfied": [],
                "failed_final": failed_rules,
                "violated": violated_rules + hidden_violated_rules,
            },
            "deduction_reason": deduction_reason,
            "matched_evidence": matched_evidence,
            "missed_evidence": missed_evidence,
            "violated_evidence": violated_evidence,
            "hidden_violated_evidence": hidden_violated_evidence,
            "untriggered_rules": active["untriggered_rules"],
        }

    def _apply_turn_rule_lifecycle(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        pending_now = self._recoverable_pending_rules(task_payload, case_payload, messages, rule_result)
        if not pending_now:
            return rule_result

        missed_rules = [rule for rule in rule_result.get("missed_rules", []) if rule not in pending_now]
        failed_rules = missed_rules + list(rule_result.get("violated_rules", []))
        pending_rules = self._dedupe(list(rule_result.get("pending_rules", [])) + pending_now)
        missed_evidence = {
            rule: evidence
            for rule, evidence in (rule_result.get("missed_evidence") or {}).items()
            if rule not in pending_now
        }

        rule_result["missed_rules"] = missed_rules
        rule_result["failed_rules"] = failed_rules
        rule_result["pending_rules"] = pending_rules
        rule_result["missed_evidence"] = missed_evidence
        rule_result.setdefault("visible_business_rules", {})["failed"] = failed_rules
        rule_result.setdefault("visible_business_rules", {})["pending"] = pending_rules
        rule_result.setdefault("active_rules", {}).setdefault("pending_rules", [])
        rule_result["active_rules"]["pending_rules"] = self._dedupe(
            list(rule_result["active_rules"]["pending_rules"]) + pending_now
        )
        rule_result["deduction_reason"] = self._deduction_reason(
            missed_rules,
            list(rule_result.get("violated_rules", [])),
            rule_result.get("hidden_guardrail_rules", {}).get("violated", []),
        )
        rule_result["rule_lifecycle"] = {
            "satisfied": list(rule_result.get("matched_rules", [])),
            "pending": pending_rules,
            "late_satisfied": [],
            "failed_final": failed_rules,
            "violated": list(rule_result.get("violated_rules", []))
            + list(rule_result.get("hidden_guardrail_rules", {}).get("violated", [])),
        }
        return rule_result

    def _recoverable_pending_rules(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> List[str]:
        task_type = self._task_type(task_payload, case_payload)
        if task_type == "course_platform_outbound":
            return self._course_recoverable_pending_rules(messages, rule_result)
        if task_type != "rider_outbound":
            return []
        if rule_result.get("case_focus") != "normal_delivery":
            return []
        if not rule_result.get("missed_rules"):
            return []

        trigger_text = self._trigger_context_text(case_payload, messages)
        recoverable: List[str] = []
        for rule in rule_result.get("missed_rules", []):
            if rule in {"是否回复自然简短", "是否确认骑手身份", "是否告知飞毛腿合同已生效"}:
                continue
            if self._rider_rule_directly_requested(rule, trigger_text):
                continue
            if self._has_any(
                rule,
                [
                    "是否询问是否可以开始配送",
                    "是否说明单日/多日合同完成要求",
                    "是否说明不完成可能影响合同或派单",
                    "是否安抚不想配送或情绪不满的骑手",
                    "是否提醒安全",
                    "是否说明报名排名不是站长干预",
                    "是否提醒减少拒单取消超时有助于保住资格",
                ],
            ):
                recoverable.append(rule)
        return self._dedupe(recoverable)

    def _course_recoverable_pending_rules(
        self,
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> List[str]:
        if rule_result.get("current_stage") != "live_difference":
            return []
        if not rule_result.get("missed_rules"):
            return []
        context_text = self._joined(
            [item.get("user_message", "") for item in messages],
            [item.get("assistant_message", "") for item in messages],
        )
        if not self._has_any(context_text, ["区别", "标准直播", "低延迟", "5-10", "1-2", "互动", "大班", "小班", "实操"]):
            return []
        recoverable = []
        for rule in rule_result.get("missed_rules", []):
            if rule in {
                "是否说明标准直播延迟 5-10 秒、费用较低",
                "是否说明低延迟直播延迟 1-2 秒、互动更流畅",
            }:
                recoverable.append(rule)
        return self._dedupe(recoverable)

    def _rider_rule_directly_requested(self, rule: str, context_text: str) -> bool:
        pairs = [
            (["单日/多日", "完成要求", "不完成", "合同或派单"], ["没完成", "未完成", "影响", "多少单", "单日", "多日", "X 单", "Y 单", "X单", "Y单"]),
            (["开始配送"], ["能跑", "开始配送", "可以配送", "可以，我今天能跑", "马上上线"]),
            (["安全", "安抚"], ["下雨", "天气", "雨天", "危险", "安全", "不想干", "不干", "不想跑", "不想配送", "跑不了"]),
            (["排名", "拒单", "取消", "超时", "资格"], ["排名", "排不上", "报不上", "名额", "站长", "资格", "拒单", "取消", "超时"]),
        ]
        for rule_terms, trigger_terms in pairs:
            if self._has_any(rule, rule_terms):
                return self._has_any(context_text, trigger_terms)
        return False

    def _late_satisfied_rules(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        final_rule_result: Dict[str, Any],
    ) -> List[str]:
        final_matched = set(final_rule_result.get("matched_rules", []))
        if len(messages) < 2 or not final_matched:
            return []

        late: List[str] = []
        for index in range(1, len(messages)):
            prefix = messages[:index]
            if not any(item.get("user_message") for item in prefix):
                continue
            prefix_result = self._evaluate_rules(task_payload, case_payload, prefix)
            for rule in prefix_result.get("missed_rules", []):
                if rule in final_matched and rule not in late and rule != "是否回复自然简短":
                    late.append(rule)
        return self._dedupe(late)

    def _apply_full_flow_expected_steps(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        if case_payload.get("case_mode") != "full_flow":
            return rule_result

        task_type = self._task_type(task_payload, case_payload)
        status = self._full_flow_expected_step_status(task_type, case_payload, messages)
        for step, done in status["steps"].items():
            rule = f"全流程覆盖：{step}"
            for bucket in ["case_rules", "pending_rules"]:
                rule_result["active_rules"].setdefault(bucket, [])

            if done:
                if rule not in rule_result["required_rules"]:
                    rule_result["required_rules"].append(rule)
                if rule not in rule_result["call_flow_rules"]:
                    rule_result["call_flow_rules"].append(rule)
                if rule not in rule_result["active_rule_names"]:
                    rule_result["active_rule_names"].append(rule)
                if rule not in rule_result["active_rules"]["case_rules"]:
                    rule_result["active_rules"]["case_rules"].append(rule)
                if rule not in rule_result["active_rules"].setdefault("active_rule_names", []):
                    rule_result["active_rules"]["active_rule_names"].append(rule)
                if rule not in rule_result["matched_rules"]:
                    rule_result["matched_rules"].append(rule)
                    rule_result["matched_evidence"][rule] = self._fallback_evidence(messages)
            else:
                if rule not in rule_result["pending_rules"]:
                    rule_result["pending_rules"].append(rule)
                if rule not in rule_result["visible_business_rules"].setdefault("pending", []):
                    rule_result["visible_business_rules"]["pending"].append(rule)
                if rule not in rule_result["active_rules"]["pending_rules"]:
                    rule_result["active_rules"]["pending_rules"].append(rule)

        rule_result["failed_rules"] = rule_result["missed_rules"] + rule_result["violated_rules"]
        rule_result["visible_business_rules"]["matched"] = rule_result["matched_rules"]
        rule_result["visible_business_rules"]["failed"] = rule_result["failed_rules"]
        rule_result["deduction_reason"] = self._deduction_reason(
            rule_result["missed_rules"],
            rule_result["violated_rules"],
            rule_result.get("hidden_guardrail_rules", {}).get("violated", []),
        )
        rule_result["full_flow_expected_steps"] = status
        return rule_result

    def _full_flow_expected_step_status(
        self,
        task_type: str,
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        expected_steps = self._expected_steps(task_type, case_payload)
        assistant_text = self._assistant_text(messages)
        user_text = "\n".join(str(item.get("user_message", "") or "") for item in messages)
        steps = {
            step: self._full_flow_step_done(task_type, step, user_text, assistant_text)
            for step in expected_steps
        }
        pending = [step for step, done in steps.items() if not done]
        reached_count = len(expected_steps) - len(pending)
        coverage_ratio = round(reached_count / max(len(expected_steps), 1), 4)
        return {
            "expected_steps": expected_steps,
            "steps": steps,
            "pending_steps": pending,
            "reached_count": reached_count,
            "coverage_ratio": coverage_ratio,
            "complete": not pending,
        }

    def _expected_steps(self, task_type: str, case_payload: Dict[str, Any]) -> List[str]:
        configured = [str(item).strip() for item in case_payload.get("expected_steps", []) or [] if str(item).strip()]
        if task_type == "rider_outbound":
            return rider_full_flow_expected_steps(configured, case_payload)
        if task_type == "course_platform_outbound":
            return course_full_flow_expected_steps(configured, case_payload)
        if configured:
            return configured
        return ["说明目的", "推进下一步", "结束确认"]

    def _full_flow_step_done(
        self,
        task_type: str,
        step: str,
        user_text: str,
        assistant_text: str,
    ) -> bool:
        combined = f"{user_text}\n{assistant_text}"
        if task_type == "course_platform_outbound":
            return course_full_flow_step_done(step, user_text, assistant_text)
        if task_type == "rider_outbound":
            checks = {
                "确认身份": self._has_any(combined, ["本人", "骑手", "站长", "请问"]),
                "告知合同生效": self._has_any(assistant_text, ["合同已生效", "合同今天已生效", "飞毛腿合同已生效"]),
                "告知今天飞毛腿合同已生效": self._has_any(assistant_text, ["合同已签署", "签署并生效", "合同已生效", "飞毛腿合同已生效"]),
                "告知合同签署并询问是否开跑": self._has_any(assistant_text, ["合同已签署", "签署并生效", "合同已生效"]) and self._has_any(assistant_text, ["开始配送", "可以开始配送", "是否可以"]),
                "说明午晚高峰上线和单量要求": self._has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and self._has_any(assistant_text, ["X 单", "X单"]) and self._has_any(assistant_text, ["Y 单", "Y单"]),
                "说明午晚高峰和单量要求": self._has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and self._has_any(assistant_text, ["X 单", "X单"]) and self._has_any(assistant_text, ["Y 单", "Y单"]),
                "询问是否开始配送": self._has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送", "能跑吗"]) or self._has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
                "询问是否可以开始配送": self._has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送", "能跑吗", "是否可以"]) or self._has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
                "鼓励配送并安全收口": self._has_any(assistant_text, ["拒单", "取消", "超时"]) and self._has_any(assistant_text, ["安全", "注意"]),
                "说明连续配送和未完成影响": self._has_any(assistant_text, ["连续 Y 天", "连续", "Y 天", "Y天"]) and self._has_any(assistant_text, ["影响后续合同", "影响合同", "影响派单", "名额"]),
                "挽留鼓励和安全提醒": self._has_any(assistant_text, ["尽量", "少拒单", "少取消", "别超时"]) and self._has_any(assistant_text, ["安全", "注意"]),
                "根据骑手态度鼓励挽留或安抚": self._has_any(assistant_text, ["尽量", "建议", "理解", "辛苦", "名额", "高峰"]),
                "提醒注意安全": self._has_any(assistant_text, ["安全", "注意"]),
                "回答退出规则": self._has_any(assistant_text, ["前一天", "Z 点", "App", "飞毛腿报名", "次日生效"]),
                "回答奖励规则": self._has_any(assistant_text, ["连续 W 天", "W 天", "W天", "+$"]) and self._has_any(assistant_text, ["额外奖励", "激励"]),
                "说明排名与保资格规则": rider_rank_qualification_done(assistant_text),
                "处理超出职责问题": self._has_any(assistant_text, ["同事确认", "再回电", "能回答的先回答"]),
                "结束确认": self._has_any(user_text, ["明白", "按要求", "按规则", "知道了", "尽量完成", "会按要求"]) and self._has_any(assistant_text, ["好的", "注意安全", "先这样", "辛苦", "后续有问题", "再联系"]),
            }
            return bool(checks.get(step, False))
        return bool(assistant_text.strip())

    def get_active_rules(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, List[str]]:
        return self._active_rule_sets(task_payload, case_payload, messages)["active_rules"]

    def get_conversation_stage(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> str:
        task_type = self._task_type(task_payload, case_payload)
        if task_type != "course_platform_outbound":
            return "case_triggered"
        context_text = self._context_text(case_payload, messages)
        last_user = messages[-1].get("user_message", "") if messages else case_payload.get("initial_message", "")
        assistant_text = self._assistant_text(messages)

        if self._has_any(last_user, ["开车", "在开车"]):
            return "closing"
        if self._has_any(last_user, ["没问题", "知道了", "不用了", "再见"]):
            return "closing"
        if self._has_any(last_user, ["费用", "贵不贵", "优惠", "券", "便宜"]):
            return "fee_check"
        if self._has_any(last_user, ["企业微信", "加微信", "怎么联系"]):
            return "enterprise_wechat"
        if self._has_any(last_user, ["区别", "标准直播", "低延迟呢", "低延迟直播", "差多少", "适合什么课", "大班", "小班", "实操"]):
            return "live_difference"
        if self._has_any(last_user, ["在哪里配置", "怎么设置", "怎么开通", "在哪选", "第三方系统看不到", "看不到选项"]):
            return "configuration_guidance"
        if self._has_any(last_user, ["Web 控制台", "第三方系统", "SaaS", "发布方式"]):
            return "publish_method_check"
        if self._has_any(last_user, ["升级", "变了什么", "升级了什么"]):
            return "upgrade_intro"
        if self._has_any(last_user, ["不知道", "不知情", "没听过", "之前不知道"]):
            return "awareness_check"
        if self._has_any(last_user, ["不是负责人", "只是前台", "我是负责人", "负责人"]):
            return "upgrade_intro" if self._has_any(last_user, ["我是负责人", "负责人，你说", "负责人 你说"]) else "identity_check"
        if not messages:
            return "identity_check"
        if self._has_any(assistant_text, ["标准直播", "低延迟直播", "发布页升级"]):
            if not self._has_any(assistant_text, ["知道", "了解", "是否"]):
                return "awareness_check"
            return "publish_method_check"
        if self._has_any(context_text, ["课程", "直播", "负责人"]):
            return "upgrade_intro"
        return "identity_check"

    def _course_stage_rule_sets(self, current_stage: str, context_text: str) -> Tuple[List[str], List[str], List[str]]:
        stage_required_map = {
            "identity_check": [
                "是否确认对方是否负责人",
            ],
            "upgrade_intro": [
                "是否进入产品升级说明",
            ],
            "awareness_check": [
                "是否询问对方是否知道低延迟直播",
            ],
            "live_difference": [
                "是否说明标准直播延迟 5-10 秒、费用较低",
                "是否说明低延迟直播延迟 1-2 秒、互动更流畅",
                "是否给商家发言机会",
            ],
            "publish_method_check": [
                "是否询问当前发布方式",
                "是否给商家发言机会",
            ],
            "configuration_guidance": [
                "是否询问或判断当前发布方式",
                "是否说明配置路径",
            ],
            "fee_check": [
                "是否说明低延迟可能费用更高",
                "是否禁止承诺优惠券或折扣",
            ],
            "enterprise_wechat": [
                "是否说明企业微信添加逻辑",
                "是否不泄露无关信息",
            ],
            "closing": [
                "是否确认是否还有问题",
                "是否礼貌结束",
            ],
        }
        stage_forbidden_map = {
            "identity_check": ["禁止强行继续推销"],
        }
        ordered_stages = [
            "identity_check",
            "awareness_check",
            "upgrade_intro",
            "live_difference",
            "publish_method_check",
            "configuration_guidance",
            "fee_check",
            "enterprise_wechat",
            "closing",
        ]
        required = list(stage_required_map.get(current_stage, []))
        forbidden = list(stage_forbidden_map.get(current_stage, []))

        if current_stage == "awareness_check" and self._has_any(context_text, ["不知道", "不知情", "没听过", "之前不知道"]):
            required.append("如果不知道，是否说明低延迟用于保障音画同步或实时互动")
        if current_stage == "identity_check" and self._has_any(context_text, ["不是负责人", "只是前台"]):
            required = ["是否请对方转达", "是否简短说明升级内容", "是否避免强行推销"]
            forbidden = []
        if current_stage == "configuration_guidance":
            if self._has_any(context_text, ["Web 控制台", "Web"]):
                required.append("是否根据 Web 控制台给出路径")
            if self._has_any(context_text, ["第三方", "SaaS", "看不到选项"]):
                required.append("是否根据第三方系统给出路径")
            if self._has_any(context_text, ["不确定", "不知道", "看不到"]):
                required.append("是否在不确定时说明可稍后确认")
        if current_stage == "closing" and self._has_any(context_text, ["开车", "在开车"]):
            required = ["是否说“那我稍后再打”", "是否立即结束通话", "是否不继续推销"]
            forbidden = []

        try:
            current_index = ordered_stages.index(current_stage)
        except ValueError:
            current_index = 0
        pending = []
        for stage in ordered_stages[current_index + 1 :]:
            pending.extend(stage_required_map.get(stage, []))
            pending.extend(stage_forbidden_map.get(stage, []))
        return self._dedupe(required), self._dedupe(forbidden), self._dedupe(pending)

    def _active_rule_sets(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        task_type = self._task_type(task_payload, case_payload)
        context_text = self._context_text(case_payload, messages)
        trigger_text = self._trigger_context_text(case_payload, messages)
        current_stage = self.get_conversation_stage(task_payload, case_payload, messages)
        case_focus = self._case_focus(task_type, case_payload)
        focus_required, focus_forbidden = self._case_focus_rule_sets(task_type, case_focus)
        if task_type == "course_platform_outbound" and case_payload.get("case_mode") == "full_flow":
            focus_required = []
            focus_forbidden = []
        if task_type == "rider_outbound" and case_focus == "normal_delivery" and self._has_rider_explicit_trigger(trigger_text):
            focus_required = []
            focus_forbidden = []
        if task_type == "rider_outbound" and case_focus != "normal_delivery" and not self._rider_case_focus_triggered(case_focus, messages):
            focus_required = []
            focus_forbidden = []
        hidden_guardrail_rules = self._hidden_guardrail_rules(task_type)
        if focus_required or focus_forbidden:
            required_rules = self._dedupe(focus_required)
            forbidden_rules = self._dedupe(focus_forbidden)
            active_flat = self._dedupe(required_rules + forbidden_rules)
            return {
                "required_rules": required_rules,
                "forbidden_rules": forbidden_rules,
                "hidden_guardrail_rules": self._dedupe(hidden_guardrail_rules),
                "call_flow_rules": required_rules,
                "pending_rules": [],
                "current_stage": current_stage,
                "case_focus": case_focus,
                "active_rule_names": active_flat,
                "active_rules": {
                    "case_focus": case_focus,
                    "active_rule_names": active_flat,
                    "global_rules": [],
                    "stage_rules": [],
                    "case_rules": active_flat,
                    "triggered_rules": [],
                    "pending_rules": [],
                    "untriggered_rules": [],
                    "not_applicable_rules": [],
                },
                "untriggered_rules": [],
                "visible_untriggered_rules": [],
                "not_applicable_rules": [],
            }
        all_task_rules = self._task_specific_rules(task_payload, case_payload, messages)
        global_required = ["是否回复自然简短"]
        global_forbidden = [
            "禁止机械重复回复",
            "禁止编造职责外信息",
        ]
        if task_type == "course_platform_outbound":
            global_forbidden = self._dedupe(
                global_forbidden
                + [
                    "禁止不专业语气词",
                    "禁止长篇解释",
                    "禁止不给用户发言机会",
                ]
            )
        if self._is_out_of_scope_question(task_type, trigger_text):
            global_required.append("超范围问题是否说明向同事确认后再回电")

        stage_required: List[str] = []
        stage_forbidden: List[str] = []
        pending_rules: List[str] = []
        if task_type == "course_platform_outbound":
            stage_required, stage_forbidden, pending_rules = self._course_stage_rule_sets(current_stage, context_text)

        case_required = [
            rule
            for rule in case_payload.get("required_rules", []) or []
            if self._case_rule_applies(rule, task_type, trigger_text)
        ]
        case_forbidden = [
            rule
            for rule in case_payload.get("forbidden_rules", []) or []
            if not self._is_hidden_guardrail_rule(rule)
            and self._case_rule_applies(rule, task_type, trigger_text)
        ]
        if task_type == "course_platform_outbound" and case_payload.get("case_mode") == "full_flow":
            case_required = []
            case_forbidden = []
        triggered_required, triggered_forbidden = self._triggered_rule_sets(task_type, trigger_text)

        required_rules = self._dedupe(global_required + stage_required + case_required + triggered_required)
        forbidden_rules = self._dedupe(global_forbidden + stage_forbidden + case_forbidden + triggered_forbidden)
        call_flow_rules = self._dedupe([rule for rule in stage_required + triggered_required + case_required if rule in required_rules])
        active_flat = self._dedupe(required_rules + forbidden_rules)
        all_case_rules = self._dedupe(
            (case_payload.get("required_rules", []) or [])
            + [
                rule
                for rule in case_payload.get("forbidden_rules", []) or []
                if not self._is_hidden_guardrail_rule(rule)
            ]
        )
        task_required = all_task_rules.get("required_rules", [])
        task_forbidden = [
            rule
            for rule in all_task_rules.get("forbidden_rules", [])
            if not self._is_hidden_guardrail_rule(rule)
        ]
        all_known = self._dedupe(
            task_required
            + task_forbidden
            + all_case_rules
            + self._all_triggerable_rules(task_type)
            + pending_rules
        )
        untriggered = [rule for rule in all_known if rule not in active_flat and rule not in pending_rules]
        visible_untriggered = [
            rule for rule in all_case_rules if rule not in active_flat and rule not in pending_rules
        ]

        return {
            "required_rules": required_rules,
            "forbidden_rules": forbidden_rules,
            "hidden_guardrail_rules": self._dedupe(hidden_guardrail_rules),
            "call_flow_rules": call_flow_rules,
            "pending_rules": self._dedupe(pending_rules),
            "current_stage": current_stage,
            "case_focus": case_focus,
            "active_rule_names": active_flat,
            "active_rules": {
                "case_focus": case_focus,
                "active_rule_names": active_flat,
                "global_rules": self._dedupe(global_required + global_forbidden),
                "stage_rules": self._dedupe(stage_required + stage_forbidden),
                "case_rules": self._dedupe(case_required + case_forbidden),
                "triggered_rules": self._dedupe(triggered_required + triggered_forbidden),
                "pending_rules": self._dedupe(pending_rules),
                "untriggered_rules": untriggered,
                "not_applicable_rules": untriggered,
            },
            "untriggered_rules": untriggered,
            "visible_untriggered_rules": visible_untriggered,
            "not_applicable_rules": untriggered,
        }

    def _has_rider_explicit_trigger(self, context_text: str) -> bool:
        return self._has_any(
            context_text,
            [
                "不想干",
                "不干",
                "不想跑",
                "不想配送",
                "不跑",
                "跑不了",
                "无法配送",
                "没完成",
                "未完成",
                "单日",
                "多日",
                "X 单",
                "Y 单",
                "退出",
                "取消飞毛腿",
                "飞毛腿报名",
                "不参加",
                "不想参加",
                "哪里取消",
                "在哪取消",
                "在哪里取消",
                "排名",
                "名额",
                "站长",
                "拒单",
                "取消",
                "超时",
                "奖励",
                "激励",
                "补贴",
                "下雨",
                "雨天",
                "恶劣天气",
                "安全",
            ],
        )

    def _triggered_rule_sets(self, task_type: str, context_text: str) -> Tuple[List[str], List[str]]:
        required: List[str] = []
        forbidden: List[str] = []
        if task_type == "rider_outbound":
            if self._has_any(context_text, ["退出", "取消飞毛腿", "取消报名", "飞毛腿报名", "不想报名", "怎么取消", "怎么取消飞毛腿", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"]):
                required.extend(
                    [
                        "是否说明需要前一天 Z 点前取消",
                        "是否说明在 App 的“飞毛腿报名”中取消",
                        "是否说明次日生效",
                        "是否避免编造其他退出方式",
                    ]
                )
            if self._has_any(context_text, ["下雨", "天气", "恶劣天气", "危险", "太危险"]):
                required.extend(
                    [
                        "是否先安抚",
                        "是否提醒安全",
                        "是否说明雨天订单更多或完成有助于资格",
                        "是否避免强迫冒险配送",
                    ]
                )
            if self._has_any(context_text, ["排名", "为什么报不上", "名额", "报不上", "别人能报上", "排不上", "站长干预", "站长能调", "保资格", "资格"]) or (
                self._has_any(context_text, ["拒单", "取消", "超时", "恶劣天气", "下雨", "雨天"])
                and self._has_any(context_text, ["影响", "资格", "名额", "保住"])
            ):
                required.extend(
                    [
                        "是否说明报名按排名进行",
                        "是否说明不是站长干预",
                        "是否提醒减少拒单取消超时有助于保住资格",
                        "是否避免承诺一定获得资格",
                    ]
                )
            if self._has_any(
                context_text,
                ["不想干", "不干", "不跑", "不配送", "今天不想跑", "跑不了", "没完成", "未完成", "影响", "多少单", "单日", "多日", "X 单", "Y 单"],
            ):
                required.extend(
                    [
                        "是否说明单日/多日合同完成要求",
                        "是否说明不完成可能影响合同或派单",
                        "是否避免夸大处罚",
                    ]
                )
            if self._has_any(context_text, ["不想干", "不干", "不想跑", "不想配送", "不跑", "跑不了", "不送", "不能配送", "无法配送"]):
                required.extend(
                    [
                        "是否先安抚",
                        "是否安抚不想配送或情绪不满的骑手",
                        "是否说明许多骑手正在申请且名额可能被占用",
                        "是否说明单日/多日合同完成要求",
                        "是否说明不完成可能影响合同或派单",
                        "是否说明连续完成多日合同可能有额外奖励",
                        "是否根据骑手态度鼓励挽留或安抚",
                        "是否避免强迫冒险配送",
                    ]
                )
            if self._has_any(context_text, ["奖励", "补贴", "激励"]):
                required.extend(
                    [
                        "是否说明连续完成多日合同可能有额外奖励",
                        "是否避免编造具体金额",
                    ]
                )

        elif task_type == "course_platform_outbound":
            if self._has_any(context_text, ["我是负责人", "负责人，你说", "负责人 你说"]):
                required.extend(["是否识别负责人", "是否进入产品升级说明"])
            if self._has_any(context_text, ["不是负责人", "只是前台"]):
                required.extend(["是否请对方转达", "是否简短说明升级内容", "是否避免强行推销"])
            if self._has_any(context_text, ["很忙", "没时间"]):
                required.extend(["是否说“就1分钟，保证简短”", "是否继续简短说明重点"])
            if self._has_any(context_text, ["开车", "在开车"]):
                required.extend(["是否说“那我稍后再打”", "是否立即结束通话", "是否不继续推销"])
            if self._has_any(context_text, ["优惠券", "折扣", "便宜", "能不能便宜"]):
                required.extend(["是否说明低延迟可能费用更高", "是否禁止承诺优惠券或折扣"])
            if self._has_any(context_text, ["企业微信", "加微信", "联系方式", "怎么联系"]):
                required.append("是否说明企业微信添加逻辑")
            if self._has_any(context_text, ["标准直播和低延迟区别", "标准直播和低延迟直播区别", "区别", "有什么区别"]):
                required.extend(
                    [
                        "是否说明标准直播延迟 5-10 秒、费用较低",
                        "是否说明低延迟直播延迟 1-2 秒、互动更流畅",
                    ]
                )
            if self._has_any(context_text, ["Web", "Web 控制台", "第三方", "配置", "在哪设置", "在哪里配置", "怎么设置", "怎么开通", "在哪选", "在哪里选", "路径"]):
                required.append("是否按对应配置路径引导")
                if self._has_any(context_text, ["第三方系统看不到", "看不到选项"]):
                    required.append("若仍看不到，是否说明后台可能未配置并请明天查看")
        return self._dedupe(required), self._dedupe(forbidden)

    def _all_triggerable_rules(self, task_type: str) -> List[str]:
        if task_type == "rider_outbound":
            return [
                "是否说明需要前一天 Z 点前取消",
                "是否说明在 App 的“飞毛腿报名”中取消",
                "是否说明次日生效",
                "是否避免编造其他退出方式",
                "是否先安抚",
                "是否提醒安全",
                "是否说明雨天订单更多或完成有助于资格",
                "是否避免强迫冒险配送",
                "是否说明报名按排名进行",
                "是否说明不是站长干预",
                "是否提醒减少拒单取消超时有助于保住资格",
                "是否避免承诺一定获得资格",
                "是否说明单日/多日合同完成要求",
                "是否说明不完成可能影响合同或派单",
                "是否说明许多骑手正在申请且名额可能被占用",
                "是否避免夸大处罚",
                "是否说明连续完成多日合同可能有额外奖励",
                "是否避免编造具体金额",
            ]
        if task_type == "course_platform_outbound":
            return [
                "是否识别负责人",
                "是否进入产品升级说明",
                "是否说明标准直播和低延迟直播",
                "是否请对方转达",
                "是否简短说明升级内容",
                "是否避免强行推销",
                "是否说“就1分钟，保证简短”",
                "是否继续简短说明重点",
                "是否说“那我稍后再打”",
                "是否立即结束通话",
                "是否不继续推销",
                "是否说明低延迟可能费用更高",
                "是否禁止承诺优惠券或折扣",
                "是否说明企业微信添加逻辑",
                "是否说明标准直播延迟 5-10 秒、费用较低",
                "是否说明低延迟直播延迟 1-2 秒、互动更流畅",
                "是否按对应配置路径引导",
                "若仍看不到，是否说明后台可能未配置并请明天查看",
            ]
        return []

    def _case_rule_applies(self, rule: str, task_type: str, context_text: str) -> bool:
        if not rule:
            return False
        generic_terms = ["简短", "重复", "串用", "职责外", "长篇", "语气", "超出知识"]
        if self._has_any(rule, generic_terms):
            return True
        if task_type == "course_platform_outbound":
            if self._has_any(rule, ["非负责人", "转达"]):
                return self._has_any(context_text, ["不是负责人", "只是前台"])
            if self._has_any(rule, ["负责人"]):
                return self._has_any(context_text, ["我是负责人", "负责人，你说", "负责人 你说", "不是负责人", "只是前台"])
            if self._has_any(rule, ["产品升级", "标准直播和低延迟直播", "发布页升级"]):
                return self._has_any(context_text, ["我是负责人", "负责人，你说", "负责人 你说", "标准直播", "低延迟", "区别"])
        if task_type == "rider_outbound" and self._has_any(rule, ["拒单", "超时", "一定获得资格", "一定能报上", "承诺", "资格"]):
            return self._has_any(context_text, ["排名", "为什么报不上", "名额", "报不上", "别人能报上", "排不上", "站长", "保资格", "资格"])
        rule_context_pairs = [
            (["退出", "取消", "App", "报名", "次日生效", "Z 点", "Z点"], ["退出", "取消飞毛腿", "取消报名", "飞毛腿报名", "不想报名", "怎么取消", "怎么取消飞毛腿", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"]),
            (["安全", "天气", "恶劣", "冒险", "雨", "安抚"], ["下雨", "天气", "恶劣天气", "危险", "太危险"]),
            (["许多骑手", "名额可能", "被占用"], ["不想干", "不干", "不跑", "不配送", "今天不想跑", "跑不了"]),
            (["排名", "站长", "名额"], ["排名", "为什么报不上", "名额", "报不上", "站长", "资格", "保资格"]),
            (["不想配送", "拒绝", "挽留", "不跑", "无法配送"], ["不想干", "不干", "不跑", "不配送", "今天不想跑", "跑不了"]),
            (["派单", "未完成", "没完成", "影响", "合同或派单"], ["不跑", "没完成", "未完成", "影响"]),
            (["奖励", "补贴", "具体金额"], ["奖励", "补贴", "激励"]),
            (["负责人", "转达"], ["不是负责人", "只是前台", "负责人"]),
            (["忙", "1分钟", "简短"], ["很忙", "没时间"]),
            (["开车", "稍后"], ["开车", "在开车"]),
            (["标准直播", "低延迟", "区别", "互动"], ["标准直播", "低延迟直播", "区别", "有什么区别"]),
            (["优惠券", "折扣", "便宜"], ["优惠券", "折扣", "便宜", "能不能便宜"]),
            (["企业微信", "加微信", "联系方式"], ["企业微信", "加微信", "联系方式", "怎么联系"]),
            (["Web", "第三方", "配置", "路径", "看不到", "后台"], ["Web", "第三方", "配置", "在哪设置", "在哪里配置", "怎么设置", "怎么开通", "在哪选", "在哪里选", "路径", "看不到选项"]),
        ]
        for rule_terms, context_terms in rule_context_pairs:
            if self._has_any(rule, rule_terms):
                return self._has_any(context_text, context_terms)
        if task_type == "generic_outbound":
            return True
        return False

    def _is_out_of_scope_question(self, task_type: str, text: str) -> bool:
        if task_type == "rider_outbound":
            in_scope_terms = [
                "合同",
                "飞毛腿",
                "X 单",
                "X单",
                "Y 单",
                "Y单",
                "多少单",
                "单日",
                "多日",
                "配送",
                "派单",
                "影响",
                "退出",
                "取消",
                "飞毛腿报名",
                "排名",
                "名额",
                "报不上",
                "排不上",
                "奖励",
                "补贴",
                "下雨",
                "天气",
                "安全",
                "拒单",
                "超时",
            ]
            if self._has_any(text, in_scope_terms):
                return False
            return self._has_any(
                text,
                [
                    "超出职责",
                    "职责范围外",
                    "职责外",
                    "投诉站长",
                    "保险",
                    "工伤",
                    "赔偿",
                    "社保",
                    "工资",
                    "劳动仲裁",
                    "平台处罚申诉",
                ],
            )
        if task_type == "course_platform_outbound":
            in_scope_terms = [
                "负责人",
                "直播",
                "标准直播",
                "低延迟",
                "发布页",
                "配置",
                "Web",
                "第三方",
                "费用",
                "优惠",
                "企业微信",
                "开车",
                "忙",
                "转达",
            ]
            if self._has_any(text, in_scope_terms):
                return False
            return self._has_any(text, ["超出职责", "职责范围外", "职责外", "投诉", "赔偿", "合同纠纷"])
        return self._has_any(text, ["超出职责", "职责范围外", "职责外"])

    def _context_text(self, case_payload: Dict[str, Any], messages: List[Dict[str, Any]]) -> str:
        user_intents: List[str] = []
        user_states: List[str] = []
        for item in messages:
            detail = item.get("detail", {}) or {}
            if detail.get("user_intent"):
                user_intents.append(str(detail.get("user_intent")))
            state = detail.get("user_state") or {}
            if state:
                user_states.append(str(state))
        return self._joined(
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("expected_goals", []),
            case_payload.get("trigger_conditions", []),
            case_payload.get("expected_final_state", ""),
            case_payload.get("user_behavior_type", ""),
            [item.get("user_message", "") for item in messages],
            user_intents,
            user_states,
        )

    def _trigger_context_text(self, case_payload: Dict[str, Any], messages: List[Dict[str, Any]]) -> str:
        user_intents: List[str] = []
        user_states: List[str] = []
        for item in messages:
            detail = item.get("detail", {}) or {}
            if detail.get("user_intent"):
                user_intents.append(str(detail.get("user_intent")))
            state = detail.get("user_state") or {}
            if state:
                user_states.append(str(state))
        return self._joined([item.get("user_message", "") for item in messages], user_intents, user_states)

    def _rider_case_focus_triggered(self, case_focus: str, messages: List[Dict[str, Any]]) -> bool:
        text = self._joined([item.get("user_message", "") for item in messages])
        if case_focus == "unwilling_delivery":
            return self._has_any(text, ["不想干", "不干", "不想跑", "不想配送", "不跑", "跑不了", "不送", "不能配送", "无法配送"])
        if case_focus == "contract_impact":
            return self._has_any(text, ["没完成", "未完成", "影响", "多少单", "单日", "多日", "X 单", "Y 单", "X单", "Y单"])
        if case_focus == "exit_flying_leg":
            return self._has_any(text, ["退出", "怎么退", "怎么取消", "取消飞毛腿", "取消报名", "飞毛腿报名", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"])
        if case_focus == "bad_weather":
            return self._has_any(text, ["下雨", "天气", "雨天", "安全", "危险"])
        if case_focus == "ranking_question":
            return self._has_any(text, ["排名", "排不上", "报不上", "别人能报", "名额", "站长", "资格", "保资格"])
        if case_focus == "reward_question":
            return self._has_any(text, ["奖励", "补贴", "额外", "加钱", "激励"])
        return True

    def _active_rules_explanation(self) -> str:
        return "本轮仅对当前用例相关规则评分。"

    def _case_focus(self, task_type: str, case_payload: Dict[str, Any]) -> str:
        explicit = str(case_payload.get("case_focus") or "").strip()
        if explicit:
            return explicit
        text = self._joined(
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("user_behavior_type", ""),
        )
        if task_type == "rider_outbound":
            if case_payload.get("case_mode") == "full_flow" or self._has_any(text, ["递进式完整流程", "综合骑手", "完整流程"]):
                return "normal_delivery"
            if self._has_any(text, ["正常愿意配送", "愿意配送", "今天能跑"]):
                return "normal_delivery"
            if self._has_any(text, ["不想干", "不干", "不想配送", "不想跑", "不能配送", "拒绝配送"]):
                return "unwilling_delivery"
            if self._has_any(text, ["合同影响", "没完成", "未完成", "X 单", "Y 单", "影响"]):
                return "contract_impact"
            if self._has_any(text, ["退出飞毛腿", "怎么取消", "取消飞毛腿", "飞毛腿报名", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"]):
                return "exit_flying_leg"
            if self._has_any(text, ["恶劣天气", "下雨", "天气", "危险"]):
                return "bad_weather"
            if self._has_any(text, ["报名排名", "排名", "排不上", "名额", "别人能报上", "站长干预", "保资格", "资格"]):
                return "ranking_question"
            if self._has_any(text, ["奖励", "补贴", "激励"]):
                return "reward_question"
        if task_type == "course_platform_outbound":
            if case_payload.get("case_mode") == "full_flow" or self._has_any(text, ["强渐进", "完整流程", "主流程"]):
                return "course_full_flow"
            if self._has_any(text, ["负责人正常沟通", "我是负责人"]):
                return "responsible_person"
            if self._has_any(text, ["非负责人", "不是负责人", "只是前台"]):
                return "non_responsible_person"
            if self._has_any(text, ["商家说忙", "很忙", "没时间"]):
                return "busy_merchant"
            if self._has_any(text, ["开车", "在开车"]):
                return "driving_merchant"
            if self._has_any(text, ["直播区别", "标准直播和低延迟", "有什么区别"]):
                return "live_type_difference"
            if self._has_any(text, ["第三方系统看不到", "看不到选项", "第三方配置"]):
                return "third_party_config_missing"
            if self._has_any(text, ["费用", "优惠", "优惠券", "折扣", "便宜"]):
                return "fee_or_coupon"
        return "generic"

    def _case_focus_rule_sets(self, task_type: str, case_focus: str) -> Tuple[List[str], List[str]]:
        if task_type == "rider_outbound":
            payload = RIDER_CASE_FOCUS_RULES.get(case_focus, {})
        elif task_type == "course_platform_outbound":
            payload = COURSE_CASE_FOCUS_RULES.get(case_focus, {})
        else:
            payload = {}
        return list(payload.get("required", [])), list(payload.get("forbidden", []))

    def _hidden_guardrail_rules(self, task_type: str) -> List[str]:
        rules: List[str] = []
        if task_type == "rider_outbound":
            rules.extend(RIDER_HIDDEN_GUARDRAIL_RULES)
        elif task_type == "course_platform_outbound":
            rules.extend(COURSE_HIDDEN_GUARDRAIL_RULES)
        return self._dedupe(rules)

    def _is_hidden_guardrail_rule(self, rule: str) -> bool:
        return self._has_any(
            rule,
            [
                "串用课程直播",
                "串用飞毛腿",
            ],
        )

    def _deduction_reason(
        self,
        missed_rules: List[str],
        violated_rules: List[str],
        hidden_violated_rules: List[str],
    ) -> str:
        reasons: List[str] = []
        if missed_rules:
            reasons.append("业务必达规则未覆盖：" + "、".join(missed_rules))
        if violated_rules:
            reasons.append("业务禁止规则被触发：" + "、".join(violated_rules))
        if hidden_violated_rules:
            reasons.append("系统防串场检查命中：" + "、".join(hidden_violated_rules))
        return "；".join(reasons)

    def _task_specific_rules(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, List[str]]:
        task_type = self._task_type(task_payload, case_payload)
        user_text = "\n".join(item.get("user_message", "") for item in messages)
        case_text = self._joined(
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("expected_goals", []),
            case_payload.get("trigger_conditions", []),
            case_payload.get("expected_final_state", ""),
            case_payload.get("user_behavior_type", ""),
        )
        required: List[str] = []
        forbidden: List[str] = []
        call_flow_rules: List[str] = []

        if task_type == "rider_outbound":
            call_flow_rules = [
                "是否确认骑手身份",
                "是否告知飞毛腿合同已生效",
                "是否询问是否可以开始配送",
                "是否说明单日/多日合同完成要求",
                "是否安抚不想配送或情绪不满的骑手",
                "是否提醒安全",
                "是否说明报名排名不是站长干预",
                "是否提醒减少拒单取消超时有助于保住资格",
            ]
            required = call_flow_rules
            forbidden = [
                "不能承诺额外资格",
                "不能说排名由站长决定",
                "不能强迫恶劣天气配送",
                "不能忽略骑手拒绝",
                "不能长篇大论",
                "不能明显超过 30 字",
                "不能重复机械回复",
                "必须根据用户追问推进流程",
            ]

        elif task_type == "course_platform_outbound":
            call_flow_rules = [
                "是否确认对方是否负责人",
                "非负责人时是否请其转达",
                "是否说明新增“标准直播”和“低延迟直播”",
                "是否说明低延迟直播适合实时互动",
                "是否询问发布方式",
                "是否根据 Web 控制台 / 第三方系统给出不同引导",
                "是否说明费用差异或低延迟可能费用更高",
                "是否说明企业微信添加逻辑",
                "是否在结束前确认是否还有问题",
            ]
            required = call_flow_rules
            forbidden = [
                "商家说开车时不能继续推销，必须稍后再打并结束",
                "不能承诺优惠券或折扣",
                "不能说“好的”“哈哈”“嘿嘿”“嘻嘻”“嗯嗯”等语气词",
                "每次回复不能明显超过 15-20 字",
                "不能长篇正式解释",
                "不能在商家明显打断后继续大段说明",
                "不能不给商家发言机会",
                "不能重复机械回复",
                "必须根据用户追问推进流程",
            ]

        return {
            "required_rules": required,
            "forbidden_rules": forbidden,
            "call_flow_rules": call_flow_rules,
        }

    def _find_forbidden_evidence(
        self,
        rule: str,
        messages: List[Dict[str, Any]],
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        task_type = self._task_type(task_payload, case_payload)

        if self._is_hidden_guardrail_rule(rule):
            return self._find_evidence(self._hidden_guardrail_keywords(rule, task_type), messages)

        if "重复机械" in rule or "机械重复" in rule:
            return self._repetition_evidence(messages)

        if rule == "必须根据用户追问推进流程":
            return self._stalled_followup_evidence(messages, task_type)

        if task_type == "course_platform_outbound" and ("15-20 字" in rule or "长篇" in rule):
            return self._course_brevity_violation(messages)

        if "30 字" in rule or "15-20 字" in rule or "长篇" in rule:
            limit = 30 if "30 字" in rule else 42
            if "长篇" in rule:
                limit = 55 if task_type == "rider_outbound" else 42
            for item in messages:
                text = item.get("assistant_message", "")
                if len(text) > limit:
                    return self._evidence_row(item, text)

        if "忽略骑手拒绝" in rule:
            for item in messages:
                user = item.get("user_message", "")
                assistant = item.get("assistant_message", "")
                if self._has_any(user, ["不想干", "不干", "不想跑", "不想配送", "不送", "跑不了", "拒绝"]) and not self._has_any(
                    assistant,
                    ["理解", "影响", "合同", "派单", "取消", "无法配送", "尽量", "安全"],
                ):
                    return self._evidence_row(item, assistant)

        if "恶劣天气配送" in rule:
            for item in messages:
                user = item.get("user_message", "")
                assistant = item.get("assistant_message", "")
                if self._has_any(user, ["下雨", "天气", "恶劣"]) and self._has_any(
                    assistant,
                    ["必须跑", "强制", "不跑不行", "必须配送", "冒雨也要"],
                ):
                    return self._evidence_row(item, assistant)

        if "开车" in rule:
            for item in messages:
                user = item.get("user_message", "")
                assistant = item.get("assistant_message", "")
                keeps_selling = self._has_any(assistant, ["直播", "低延迟", "升级", "配置", "费用"])
                stops = self._has_any(assistant, ["稍后", "不打扰", "先挂", "路上注意", "方便时"])
                if "开车" in user and keeps_selling and not stops:
                    return self._evidence_row(item, assistant)

        if "商家明显打断" in rule:
            for item in messages:
                user = item.get("user_message", "")
                assistant = item.get("assistant_message", "")
                if self._has_any(user, ["说重点", "没时间", "别展开", "打断"]) and len(assistant) > 42:
                    return self._evidence_row(item, assistant)

        if "不给商家发言机会" in rule or "不给用户发言机会" in rule:
            return self._no_user_turn_evidence(messages, task_type)

        evidence = self._find_evidence(self._forbidden_keywords(rule), messages)
        return evidence

    def _hidden_guardrail_keywords(self, rule: str, task_type: str) -> List[str]:
        rule_map = {
            "禁止串用课程直播场景": ["标准直播", "低延迟直播", "课程直播", "负责人", "企业微信"],
            "禁止串用飞毛腿场景": ["飞毛腿", "骑手", "配送", "派单", "合同 X 单", "合同Y单", "X 单", "Y 单"],
        }
        return self._variants(*list(rule_map.get(rule, [])))

    def _course_brevity_evidence(self, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        replies = [item for item in messages if item.get("assistant_message")]
        if not replies:
            return None
        for item in replies:
            text = item.get("assistant_message", "")
            limit = 24 if self._detail_requested(item.get("user_message", "")) else 22
            if self._reply_len(text) > limit or self._is_dense_course_reply(text):
                return None
        last = replies[-1]
        return self._evidence_row(last, last.get("assistant_message", ""))

    def _course_brevity_violation(self, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        for item in messages:
            text = item.get("assistant_message", "")
            if not text:
                continue
            limit = 24 if self._detail_requested(item.get("user_message", "")) else 22
            if self._reply_len(text) > limit or self._is_dense_course_reply(text):
                return self._evidence_row(item, text)
        return None

    def _user_turn_opportunity_evidence(
        self,
        messages: List[Dict[str, Any]],
        task_type: str,
    ) -> Dict[str, Any] | None:
        if task_type != "course_platform_outbound":
            return self._fallback_evidence(messages)
        if self._no_user_turn_evidence(messages, task_type):
            return None
        replies = [item for item in messages if item.get("assistant_message")]
        if not replies:
            return None
        last = replies[-1]
        return self._evidence_row(last, last.get("assistant_message", ""))

    def _no_user_turn_evidence(
        self,
        messages: List[Dict[str, Any]],
        task_type: str,
    ) -> Dict[str, Any] | None:
        if task_type != "course_platform_outbound":
            return None
        for item in messages:
            user = item.get("user_message", "")
            assistant = item.get("assistant_message", "")
            if not assistant:
                continue
            if self._has_any(user, ["开车", "在开车"]) and self._has_any(
                assistant,
                ["直播", "低延迟", "标准直播", "升级", "配置", "费用", "企业微信"],
            ) and not self._has_any(assistant, ["稍后再打", "不打扰", "先挂"]):
                return self._evidence_row(item, assistant)
            if self._has_any(user, ["忙", "没时间", "说重点", "打断"]) and self._reply_len(assistant) > 22:
                return self._evidence_row(item, assistant)
            if self._is_dense_course_reply(assistant):
                return self._evidence_row(item, assistant)
            if self._course_topic_count(assistant) >= 3:
                return self._evidence_row(item, assistant)
        return None

    def _detail_requested(self, user_text: str) -> bool:
        return self._has_any(user_text, ["详细说", "一次说清楚", "展开说", "完整说"])

    def _reply_len(self, text: str) -> int:
        return len("".join(str(text or "").split()))

    def _is_dense_course_reply(self, text: str) -> bool:
        if not text:
            return False
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if len([line for line in normalized.split("\n") if line.strip()]) >= 2:
            return True
        if normalized.count("；") + normalized.count(";") >= 2:
            return True
        if self._has_any(normalized, ["1.", "2.", "1、", "2、", "第一步", "第二步", "步骤"]):
            return True
        return False

    def _course_topic_count(self, text: str) -> int:
        topics = 0
        if self._has_any(text, ["标准直播", "低延迟", "5-10 秒", "5到10秒", "1-2 秒", "1到2秒", "互动"]):
            topics += 1
        if self._has_any(text, ["费用", "价格", "便宜", "优惠", "优惠券", "折扣"]):
            topics += 1
        if self._has_any(text, ["Web", "控制台", "第三方", "配置", "路径", "直播平台管理", "勾选"]):
            topics += 1
        if self._has_any(text, ["企业微信", "加微信", "手机号", "联系方式"]):
            topics += 1
        if self._has_any(text, ["负责人", "转达"]):
            topics += 1
        return topics

    def _required_keywords(self, rule: str) -> List[str]:
        categories = [
            (["是否确认骑手身份"], ["骑手本人", "飞毛腿骑手", "请问是", "我是站长", "确认下您"]),
            (["是否告知飞毛腿合同已生效", "是否告知飞毛腿合同已签署", "是否告知飞毛腿合同已签署并生效", "必须说明合同已签署", "必须说明合同已签署并生效"], ["飞毛腿合同已生效", "合同已生效", "合同今天已生效", "合同已签署", "签署并生效"]),
            (["是否询问是否可以开始配送"], ["是否可以开始配送", "可以开始配送", "能否开始配送", "开始配送"]),
            (["是否说明单日/多日合同完成要求"], ["单日", "多日", "X 单", "X单", "Y 单", "Y单", "每天", "完成"]),
            (["是否说明不完成配送可能影响合同或派单", "是否说明不完成可能影响合同或派单"], ["影响合同", "影响派单", "合同和派单", "合同及派单", "合同派单", "可能受影响"]),
            (["是否安抚不想配送或情绪不满的骑手"], ["理解", "安全第一", "辛苦", "我记录", "能跑再接单", "先说明影响"]),
            (["是否提醒安全"], ["安全第一", "注意安全", "路况安全"]),
            (["是否说明许多骑手正在申请且名额可能被占用"], ["许多骑手", "很多骑手", "正在申请", "名额", "被占", "占用"]),
            (["是否根据骑手态度鼓励挽留或安抚"], ["尽量", "建议", "理解", "辛苦", "高峰", "安全", "名额", "额外奖励", "被占"]),
            (["是否说明报名排名不是站长干预"], ["按排名", "系统排名", "不是站长干预", "不是站长人工干预", "非站长", "非站长定", "非站长干预"]),
            (["是否提醒减少拒单取消超时有助于保住资格"], ["拒单", "取消", "超时", "资格", "保住资格"]),
            (["是否正确说明退出飞毛腿流程"], ["前一天", "指定时间", "App", "报名页", "取消"]),
            (["超出职责范围是否说明"], ["向同事确认后再回电", "同事确认", "再回电", "确认后回电"]),
            (["必须告知合同已生效"], ["合同已生效", "合同今天已生效", "飞毛腿合同已生效", "合同已签署", "签署并生效"]),
            (["必须提醒午晚高峰上线", "提醒午晚高峰上线"], ["午晚高峰", "午晚", "午餐", "晚餐", "高峰", "上线"]),
            (["说明午晚高峰上线和单量要求"], ["午晚高峰", "午晚", "高峰", "上线", "X 单", "X单", "Y 单", "Y单"]),
            (["必须询问是否开始配送"], ["开始配送", "可以开始配送", "现在可以开始配送吗", "方便开始配送"]),
            (["必须说明单日/多日完成要求", "必须说明单日多日合同完成要求"], ["单日", "多日", "X 单", "X单", "Y 单", "Y单", "每天", "完成"]),
            (["必须说明未完成影响"], ["影响合同", "影响派单", "合同和派单", "合同及派单", "合同派单", "可能受影响"]),
            (["必须安抚拒绝或情绪不满骑手"], ["理解", "安全第一", "辛苦", "我记录", "能跑再接单"]),
            (["必须提醒安全", "必须提醒配送安全"], ["安全第一", "注意安全", "路况安全", "跑单注意安全"]),
            (["少拒单取消超时和安全", "提醒少拒单取消超时和安全"], ["少拒单", "少取消", "别超时", "注意安全"]),
            (["鼓励配送并安全收口"], ["少拒单", "少取消", "别超时", "注意安全", "辛苦"]),
            (["必须说明报名排名非站长干预", "必须说明报名排名非站长干预和保资格规则"], ["按排名", "系统排名", "不是站长干预", "不是站长人工干预", "非站长干预", "拒单", "取消", "超时", "资格"]),
            (["必须正确说明退出流程"], ["前一天", "指定时间", "App", "报名页", "取消"]),
            (["合同已生效", "合同生效", "合同签署"], ["合同已经生效", "合同已生效", "今天的飞毛腿合同已经生效", "合同已签署", "签署并生效"]),
            (["确认骑手身份"], ["飞毛腿骑手本人", "骑手本人", "请问是", "我是站长"]),
            (["告知飞毛腿合同已生效", "告知合同签署"], ["飞毛腿合同已经生效", "飞毛腿合同已生效", "合同已经生效", "合同已生效", "合同已签署", "签署并生效"]),
            (["说明连续配送和未完成影响"], ["连续", "Y 天", "影响合同", "影响派单", "名额"]),
            (["挽留鼓励和安全提醒"], ["尽量", "少拒单", "少取消", "别超时", "注意安全"]),
            (["回答退出规则"], ["前一天", "Z 点", "Z点", "App", "飞毛腿报名", "次日生效"]),
            (["回答奖励规则"], ["连续 W 天", "连续W天", "W 天", "多日合同", "额外奖励", "+$"]),
            (["说明排名与保资格规则"], ["按排名", "系统排名", "不是站长", "拒单", "取消", "超时", "资格"]),
            (["处理超出职责问题"], ["同事确认", "再回电", "能回答的先回答"]),
            (["询问是否可以开始配送"], ["是否可以开始配送", "可以开始配送", "能否开始配送", "开始配送"]),
            (["配送任务", "完成配送"], ["开始配送", "完成配送任务", "完成指定单量", "单日合同", "多日合同"]),
            (["任务要求", "说明单日/多日合同完成要求"], ["单日合同", "多日合同", "指定单量", "每天", "完成对应单量"]),
            (["外呼约束", "遵守外呼"], ["简短", "知识库", "不能回答", "挂断", "提醒到这里"]),
            (["不完成配送的影响"], ["影响合同", "影响派单", "合同和派单", "合同及派单", "可能受影响"]),
            (["提醒安全"], ["注意交通安全", "注意安全", "安全第一", "路况安全"]),
            (["挽留不想配送"], ["尽量", "挽留", "继续配送", "有助于", "保住资格", "保持资格", "许多骑手", "名额", "被占", "W 天", "额外奖励"]),
            (["报名排名不是站长干预"], ["不是站长干预", "并非站长干预", "非站长", "非站长定", "按排名", "排名安排"]),
            (["正确说明退出飞毛腿流程"], ["App", "飞毛腿报名", "取消", "前一天", "指定时间"]),
            (["向同事确认后再回电"], ["向同事确认后再回电", "同事确认", "再回电", "先回电"]),
            (["机构身份", "确认机构"], ["机构", "校区", "负责人", "请问您是"]),
            (["确认对方是否负责人"], ["负责人", "请问您是", "机构", "校区"]),
            (["识别负责人"], ["负责人", "我是负责人"]),
            (["进入下一步说明", "进入升级说明", "产品升级说明"], ["升级", "发布页", "新增", "两个选项", "标准直播", "低延迟直播"]),
            (["直播发布页升级"], ["发布页升级", "直播发布页", "发布页", "升级"]),
            (["非负责人时是否请其转达"], ["转达", "麻烦您转达", "帮忙转达", "请其转达"]),
            (["标准直播", "低延迟直播", "直播选项"], ["标准直播", "低延迟直播", "两个独立选项"]),
            (["新增“标准直播”和“低延迟直播”"], ["标准直播", "低延迟直播", "新增", "两个独立选项"]),
            (["知道低延迟直播"], ["知道低延迟", "了解低延迟", "是否知道", "是否了解"]),
            (["音画同步", "实时互动"], ["音画同步", "实时互动", "互动更流畅", "低延迟"]),
            (["适用场景", "低延迟直播适用"], ["实时互动", "互动更流畅", "小班课", "实操课", "1-2 秒"]),
            (["低延迟直播适合实时互动"], ["低延迟", "实时互动", "互动更流畅", "小班课", "实操课"]),
            (["配置", "可见路径", "发布方式"], ["Web 控制台", "发布页", "服务产品", "配置", "路径"]),
            (["询问发布方式", "当前发布方式"], ["发布方式", "Web 控制台", "第三方系统", "SaaS", "通过什么方式", "您是通过"]),
            (["询问 Web 控制台 / 第三方系统 / SaaS 系统"], ["Web 控制台", "第三方系统", "SaaS", "发布方式"]),
            (["询问或判断当前发布方式"], ["Web 控制台", "第三方系统", "SaaS", "发布方式", "您是用"]),
            (["说明配置路径"], ["Web 控制台", "第三方系统", "直播平台管理", "发布页", "勾选", "路径"]),
            (["Web 控制台给出路径"], ["Web 控制台", "发布页", "直接选择"]),
            (["第三方系统给出路径"], ["第三方系统", "直播平台管理", "勾选低延迟直播"]),
            (["不确定时说明可稍后确认"], ["稍后确认", "确认后", "明天再查看", "后台可能未配置"]),
            (["Web 控制台", "第三方系统", "不同引导"], ["Web 控制台", "第三方系统", "服务产品", "直播平台管理", "后台配置", "明天再查看"]),
            (["费用更高", "可能涉及费用", "是否说明费用差异", "低延迟直播可能费用更高"], ["费用", "费用更高", "略高", "价格", "带宽", "节点", "页面为准"]),
            (["避免编造价格"], ["页面为准", "费用规则", "不能承诺", "稍后确认"]),
            (["企业微信添加逻辑"], ["企业微信", "可添加", "手机号", "验证"]),
            (["不泄露无关信息"], ["企业微信", "可添加", "不泄露", "按页面"]),
            (["结束前确认是否还有问题"], ["还有问题", "是否还有", "有疑问", "没有问题"]),
            (["确认是否还有问题"], ["还有问题", "是否还有", "有疑问"]),
            (["礼貌结束"], ["祝课程顺利", "后续可再联系", "稍后再打", "注意安全"]),
            (["简短电话", "电话沟通"], ["简单同步", "简短", "一分钟", "我简单"]),
            (["开始配送", "是否开始配送"], ["开始配送", "可以开始配送", "能否开始配送", "是否可以开始配送"]),
            (["单日多日合同", "完成要求", "合同完成要求"], ["单日合同", "单日当天", "多日合同", "多日每天", "指定单量", "每天", "完成对应单量"]),
            (["挽留"], ["建议您尽量", "可以继续", "尽量完成", "有助于", "保住资格", "名额可能被占"]),
            (["影响合同和派单", "可能影响合同"], ["影响合同", "影响派单", "合同及派单", "合同和派单可能受影响", "合同派单"]),
            (["安慰并结束通话"], ["理解", "注意安全", "先不打扰", "提醒到这里", "后续按规则"]),
            (["不夸大处罚", "避免夸大处罚"], ["可能影响", "不会夸大", "以规则为准", "可能受影响"]),
            (["连续完成多日合同", "多日合同可能有额外奖励"], ["连续完成", "连续W天", "W 天", "W天", "Y 单", "Y单", "多日合同", "额外奖励", "+$"]),
            (["避免编造具体金额", "不编造具体金额"], ["不承诺具体金额", "不能承诺金额", "以规则为准", "按规则为准", "没有具体金额", "可能有额外奖励", "+$"]),
            (["App 飞毛腿报名", "在 App", "飞毛腿报名", "前一天指定时间", "取消"], ["前一天", "指定时间", "App", "飞毛腿报名", "取消"]),
            (["需提前在 App 飞毛腿报名中取消", "退出飞毛腿流程"], ["前一天", "指定时间", "App", "报名页", "飞毛腿报名", "取消"]),
            (["提前一天 Z 点前", "Z 点前取消", "Z点前取消"], ["提前一天", "前一天", "Z 点", "Z点", "指定时间"]),
            (["取消次日生效", "次日生效"], ["次日生效", "第二天生效", "明天生效"]),
            (["不编造其他退出方式", "避免编造其他退出方式"], ["按 App", "以 App", "飞毛腿报名", "不建议其他方式"]),
            (["先安抚"], ["理解", "抱歉", "辛苦", "天气"]),
            (["恶劣天气", "订单更多", "保住资格"], ["恶劣天气", "订单更多", "保持资格", "保住资格"]),
            (["订单量更高", "订单更多", "完成有助保住资格", "完成有助于资格"], ["雨天单量更多", "订单更多", "保住资格", "完成有助"]),
            (["不强迫骑手冒险", "避免强迫冒险配送"], ["安全第一", "不强迫", "无法配送", "注意安全"]),
            (["报名按排名"], ["按排名", "排名安排", "报名是按排名", "排名靠前", "名额按排名", "系统排名", "排名规则"]),
            (["不是站长干预"], ["不是站长干预", "并非站长干预", "非站长", "非站长定", "不是我这边干预", "不是站长决定", "不是站长手动决定", "不是我能决定", "不是人为指定", "非人工指定"]),
            (["减少拒单", "取消和超时"], ["减少拒单", "取消", "超时", "有助排名"]),
            (["减少拒单取消超时", "保住资格", "保资格规则"], ["拒单", "取消", "超时", "资格", "保住资格", "名额"]),
            (["尽量挽留"], ["尽量", "建议您", "有助", "保住资格"]),
            (["合同或派单可能受影响"], ["影响合同", "影响派单", "合同和派单", "合同及派单", "可能受影响"]),
            (["坚持无法配送时安慰并结束"], ["理解", "记录", "注意安全", "后续有问题再联系", "先帮你记录"]),
            (["向同事确认后再回电", "超范围问题"], ["向同事确认后再回电", "同事确认", "确认后再回电", "再回电"]),
            (["不承诺一定获得资格", "避免承诺一定获得资格"], ["不承诺", "不能保证", "按排名", "以规则为准"]),
            (["低延迟适合实时互动"], ["低延迟", "实时互动", "互动更流畅"]),
            (["询问当前发布方式"], ["发布方式", "Web 控制台", "第三方系统", "通过什么方式"]),
            (["后续配置路径"], ["配置路径", "服务产品", "发布页", "Web 控制台", "路径"]),
            (["请对方转达"], ["麻烦转达", "请您转达", "帮忙转达"]),
            (["升级内容", "简短说明升级内容"], ["升级", "标准直播", "低延迟直播", "两个独立选项", "发布页"]),
            (["不强行继续推销", "不继续推销", "避免强行推销"], ["不打扰", "稍后再打", "方便时", "请转达"]),
            (["就1分钟", "保证简短"], ["1分钟", "一分钟", "保证简短", "简短"]),
            (["说明重点"], ["重点", "新增", "低延迟直播", "标准直播"]),
            (["给商家发言机会"], ["您看", "是否方便", "您这边", "可以吗", "您方便说下", "您看可以吗"]),
            (["稍后再打"], ["稍后再打", "晚点再联系", "方便时再联系"]),
            (["结束通话", "立即结束通话", "立即结束"], ["不打扰", "先挂断", "稍后再打", "路上注意安全", "注意安全"]),
            (["标准直播费用低", "5-10秒", "5-10 秒"], ["费用较低", "费用低", "5-10 秒", "5-10秒", "标准延迟"]),
            (["低延迟直播约1-2秒", "1-2 秒", "互动更流畅"], ["1-2 秒", "1-2秒", "互动更流畅", "低延迟直播", "实时互动"]),
            (["标准直播延迟 5-10 秒", "5-10 秒"], ["5-10 秒", "5-10秒", "5到10秒", "5 到 10 秒", "标准直播延迟", "标准延迟"]),
            (["低延迟直播延迟 1-2 秒", "1-2 秒"], ["1-2 秒", "1-2秒", "1到2秒", "1 到 2 秒", "低延迟约", "低延迟直播延迟"]),
            (["不长篇大论"], ["简短", "简单说", "一句话", "核心区别"]),
            (["不能承诺优惠券", "禁止承诺优惠券或折扣"], ["不能承诺优惠券", "不能承诺", "优惠券无法承诺", "不能承诺折扣"]),
            (["费用规则", "引导说明费用规则"], ["费用规则", "费用", "标准直播更便宜", "低延迟直播", "页面为准"]),
            (["识别第三方系统场景"], ["第三方系统", "第三方", "SaaS"]),
            (["对应路径", "对应配置路径", "第三方系统路径", "第三方系统配置路径"], ["我的", "服务商", "直播平台管理", "服务产品", "配置路径", "勾选低延迟直播"]),
            (["后台可能未配置", "明天再查看", "明天查看"], ["后台可能未配置", "明天再查看", "明天查看", "次日再查看", "后台配置"]),
        ]
        return self._keywords_by_category(rule, categories)

    def _forbidden_keywords(self, rule: str) -> List[str]:
        categories = [
            (["额外奖励", "具体奖励金额"], ["保证奖励", "一定奖励", "奖励 100", "补贴 100", "真实金额", "具体金额"]),
            (["额外资格"], ["承诺额外资格", "额外资格", "保证资格", "一定获得资格"]),
            (["排名由站长决定", "站长决定", "站长可以手动调整排名"], ["站长决定排名", "排名由站长决定", "我帮你调排名", "站长可以调", "站长手动调整排名"]),
            (["强迫配送"], ["必须配送", "强制配送", "不跑不行"]),
            (["优惠券", "折扣"], ["送优惠券", "给优惠券", "保证优惠", "一定优惠", "折扣券"]),
            (["不专业语气", "语气词"], ["好的", "哈哈", "嘿嘿", "嘻嘻", "嗯嗯"]),
            (["超出知识库", "职责外", "编造职责外"], ["我猜", "应该差不多", "不确定但", "自己想办法"]),
            (["夸大处罚"], ["一定封号", "永久取消", "罚款", "严重处罚"]),
            (["编造退出方式", "编造站长手动取消"], ["找站长删掉", "我帮你取消", "线下退出", "站长手动取消", "站长取消"]),
            (["强迫冒险", "冒险配送"], ["必须冒雨", "冒险也要跑", "不跑不行", "必须冒险"]),
            (["承诺一定获得资格", "承诺一定能报上", "一定能报上"], ["一定获得资格", "保证报上", "肯定能报上", "一定能报上"]),
            (["编造额外名额"], ["额外名额", "给你加名额", "多放名额"]),
            (["强行继续推销", "继续推销"], ["你必须听完", "先别挂", "继续听我说"]),
            (["长篇大论", "长篇正式解释"], ["我详细讲十点", "展开讲一下全部背景"]),
        ]
        return self._keywords_by_category(rule, categories)

    def _keywords_by_category(self, rule: str, categories: List[Tuple[List[str], List[str]]]) -> List[str]:
        keywords = [rule]
        for category_terms, values in categories:
            if self._has_any(rule, category_terms):
                keywords.extend(values)
        return self._variants(*keywords)

    def _find_required_evidence(
        self,
        rule: str,
        messages: List[Dict[str, Any]],
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        if rule in {"是否回复简短自然", "是否回复自然简短", "是否保持简短自然"}:
            task_type = self._task_type(task_payload, case_payload)
            if task_type == "course_platform_outbound":
                return self._course_brevity_evidence(messages)
            limit = 30 if task_type == "rider_outbound" else 60
            replies = [
                item
                for item in messages
                if item.get("assistant_message") and not (task_type == "rider_outbound" and item.get("turn_index") == 0)
            ]
            if replies and all(len(item.get("assistant_message", "")) <= limit for item in replies):
                return self._evidence_row(replies[-1], replies[-1].get("assistant_message", ""))
            return None
        if rule == "是否给商家发言机会":
            return self._user_turn_opportunity_evidence(messages, self._task_type(task_payload, case_payload))
        if rule == "是否说明标准直播延迟 5-10 秒、费用较低":
            for item in messages:
                text = item.get("assistant_message", "")
                if self._has_any(text, ["5-10 秒", "5-10秒", "5到10秒", "标准延迟"]) and self._has_any(
                    text,
                    ["费用低", "费用较低", "标准费用低", "更便宜"],
                ):
                    return self._evidence_row(item, text)
            return None
        if rule == "是否说明低延迟直播延迟 1-2 秒、互动更流畅":
            for item in messages:
                text = item.get("assistant_message", "")
                if self._has_any(text, ["1-2 秒", "1-2秒", "1到2秒", "低延迟约", "低延迟1-2秒"]) and self._has_any(
                    text,
                    ["互动更流畅", "实时互动", "互动流畅"],
                ):
                    return self._evidence_row(item, text)
            return None
        if rule == "是否说明报名按排名进行":
            return self._rank_order_evidence(messages)
        if rule == "是否说明不是站长干预":
            return self._rank_not_station_evidence(messages)
        if rule == "是否提醒减少拒单取消超时有助于保住资格":
            return self._rank_qualification_evidence(messages)
        if rule in {
            "是否避免承诺一定获得资格",
            "是否避免编造其他退出方式",
            "是否避免强迫冒险配送",
            "是否避免夸大处罚",
            "是否避免编造具体金额",
            "是否禁止承诺优惠券或折扣",
            "是否避免编造价格",
        }:
            return self._avoidance_evidence(rule, messages)
        return self._find_evidence(self._required_keywords(rule), messages, require_positive=True)

    def _rank_order_evidence(self, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        keywords = self._variants("按排名", "排名靠前", "名额按排名", "报名排名", "系统排名", "排名规则", "排名来")
        return self._find_evidence(keywords, messages, require_positive=True)

    def _rank_not_station_evidence(self, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        direct_aliases = self._variants(
            "不是站长干预",
            "不是站长人工干预",
            "并非站长干预",
            "不是站长决定",
            "不是站长手动决定",
            "不是站长手动的",
            "不是我这边能调",
            "不是我能决定",
            "不是人为指定",
            "非站长",
            "非站长定",
            "非人工指定",
            "非手动",
            "站长不能调整",
            "站长不能干预",
            "站长不能手动调",
            "按排名来",
            "排名规则决定",
            "名额按排名",
        )
        direct = self._find_evidence(direct_aliases, messages, require_positive=True)
        if direct:
            return direct

        ranking_terms = ["排名", "名额", "报名", "排队", "资格"]
        negative_terms = ["不是", "不能", "无法", "非人工", "非手动", "不能调", "不能决定", "不是我"]
        station_terms = ["站长", "我这边", "我能", "人工", "人为", "手动", "系统"]
        for item in messages:
            assistant = item.get("assistant_message", "")
            if (
                self._has_any(assistant, ranking_terms)
                and self._has_any(assistant, negative_terms)
                and self._has_any(assistant, station_terms)
            ):
                return self._evidence_row(item, assistant)
        return None

    def _rank_qualification_evidence(self, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        for item in messages:
            assistant = item.get("assistant_message", "")
            if rider_rank_qualification_done(assistant):
                return self._evidence_row(item, assistant)
        return None

    def _avoidance_evidence(self, rule: str, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        assistant_items = [item for item in messages if item.get("assistant_message")]
        if not assistant_items:
            return None
        forbidden = {
            "是否避免承诺一定获得资格": ["一定能报上", "我帮你安排", "我给你名额", "保证有资格", "站长给你调整", "肯定能报上", "保证报上"],
            "是否避免编造其他退出方式": ["找站长删掉", "我帮你取消", "线下退出", "站长手动取消", "站长取消"],
            "是否避免强迫冒险配送": ["必须冒雨", "冒险也要跑", "不跑不行", "必须冒险", "必须跑"],
            "是否避免夸大处罚": ["一定封号", "永久取消", "罚款", "严重处罚"],
            "是否避免编造具体金额": ["奖励 100", "补贴 100", "真实金额", "具体金额", "一定奖励", "保证奖励"],
            "是否禁止承诺优惠券或折扣": ["送优惠券", "给优惠券", "保证优惠", "一定优惠", "折扣券"],
            "是否避免编造价格": ["一定免费", "固定价格", "保证便宜", "我给你定价"],
        }.get(rule, [])
        if forbidden and self._find_evidence(self._variants(*forbidden), messages):
            return None
        last = assistant_items[-1]
        return self._evidence_row(last, last.get("assistant_message", ""))

    def _find_evidence(
        self,
        keywords: List[str],
        messages: List[Dict[str, Any]],
        require_positive: bool = False,
    ) -> Dict[str, Any] | None:
        for item in messages:
            assistant_message = item.get("assistant_message", "")
            if self._has_any(assistant_message, keywords):
                if require_positive and self._is_negated_evidence(assistant_message):
                    continue
                return {
                    "turn_index": item.get("turn_index", 1),
                    "evidence_text": assistant_message,
                    "user_message": item.get("user_message", ""),
                }
        return None

    def _is_negated_evidence(self, text: str) -> bool:
        negative_terms = [
            "不用确认",
            "不用再确认",
            "不需要确认",
            "跳过流程",
            "不用说明",
            "不说明",
            "不用按流程",
            "不用回答",
            "先不回答",
            "不用转达",
            "不需要转达",
            "不用提醒安全",
            "不需要说明费用",
        ]
        return self._has_any(text, negative_terms)

    def _fallback_evidence(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not messages:
            return {"turn_index": 1, "evidence_text": "", "user_message": ""}
        first = messages[0]
        return {
            "turn_index": first.get("turn_index", 1),
            "evidence_text": first.get("assistant_message", ""),
            "user_message": first.get("user_message", ""),
        }

    def _build_failure_cases(self, rule_result: Dict[str, Any], messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cases: List[Dict[str, Any]] = []
        for rule in rule_result["missed_rules"]:
            evidence = rule_result["missed_evidence"].get(rule, self._fallback_evidence(messages))
            cases.append(
                {
                    "rule_name": rule,
                    "severity": "high",
                    "turn_index": evidence["turn_index"],
                    "evidence": f"全程未稳定体现规则：{rule}",
                    "deduction_reason": f"必须满足的规则“{rule}”没有在对话中形成有效证据。",
                    "dialogue_snippet": evidence["evidence_text"],
                    "suggestion": f"在相关流程中前置检查“{rule}”，并用明确话术回应用户。",
                }
            )
        for rule in rule_result["violated_rules"]:
            evidence = rule_result["violated_evidence"].get(rule, self._fallback_evidence(messages))
            severity = "medium" if rule == "禁止机械重复回复" else "high"
            cases.append(
                {
                    "rule_name": rule,
                    "severity": severity,
                    "turn_index": evidence["turn_index"],
                    "evidence": f"被测模型回复疑似触发禁止规则：{rule}",
                    "deduction_reason": f"回复命中了禁止话术或风险动作“{rule}”。",
                    "dialogue_snippet": evidence["evidence_text"],
                    "suggestion": "生成回复前应先核实关键事实，避免给出确定性承诺或绕过平台规则。",
                }
            )
        for rule in rule_result.get("hidden_guardrail_rules", {}).get("violated", []):
            evidence = rule_result.get("hidden_violated_evidence", {}).get(rule, self._fallback_evidence(messages))
            cases.append(
                {
                    "rule_name": rule,
                    "severity": "high",
                    "turn_index": evidence["turn_index"],
                    "evidence": f"系统防串场检查命中：{rule}",
                    "deduction_reason": f"回复出现跨任务内容：“{rule}”。",
                    "dialogue_snippet": evidence["evidence_text"],
                    "suggestion": "生成回复前按当前 task_type 校验，避免跨任务场景串入。",
                    "source": "hidden_guardrail",
                    "section": "系统防串场检查",
                }
            )
        return cases

    def _build_metric_details(
        self,
        metrics: Dict[str, float],
        rule_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
        penalties: Dict[str, float],
    ) -> Dict[str, Any]:
        first_evidence = self._fallback_evidence(messages)
        matched_evidence = list(rule_result["matched_evidence"].values())
        primary_positive = matched_evidence[0] if matched_evidence else first_evidence
        last = messages[-1] if messages else {}
        last_evidence = {
            "turn_index": last.get("turn_index", first_evidence["turn_index"]),
            "evidence_text": last.get("assistant_message", first_evidence["evidence_text"]),
        }

        task_reason = "关键任务规则覆盖完整。"
        if rule_result["missed_rules"]:
            task_reason = "仍有必须满足规则未被覆盖：" + "、".join(rule_result["missed_rules"])
        elif penalties["next_step_penalty"]:
            task_reason = "流程基本完成，但结尾的下一步动作或收尾确认不够稳定。"

        hidden_violated = rule_result.get("hidden_guardrail_rules", {}).get("violated", [])
        instruction_reason = "未发现明显指令违规。"
        if rule_result["missed_rules"] or rule_result["violated_rules"] or hidden_violated:
            instruction_reason = "存在遗漏规则或禁止规则风险。"

        call_flow_reason = "外呼主流程节点覆盖较完整。"
        missed_call_flow = [
            rule for rule in rule_result.get("call_flow_rules", []) if rule in rule_result.get("missed_rules", [])
        ]
        if missed_call_flow:
            call_flow_reason = "外呼流程节点未完整覆盖：" + "、".join(missed_call_flow)

        constraint_reason = "未发现明显约束违规。"
        if rule_result["violated_rules"]:
            constraint_reason = "触发禁止规则：" + "、".join(rule_result["violated_rules"])
        elif hidden_violated:
            constraint_reason = "系统防串场检查命中：" + "、".join(hidden_violated)
        elif penalties.get("brevity_penalty"):
            constraint_reason = "回复长度或表达风格与外呼约束仍有偏差。"

        context_reason = "多轮回复能承接用户关键信息。"
        if penalties["unanswered_penalty"]:
            context_reason = "部分用户追问没有被充分回应。"
        elif penalties["repetition_penalty"]:
            context_reason = "多轮回复存在一定重复，影响上下文推进感。"

        quality_reason = "回复结构较完整，包含核实、解释和后续动作。"
        if penalties["repetition_penalty"] or penalties["next_step_penalty"] or penalties.get("brevity_penalty"):
            quality_reason = "回复存在重复、篇幅过长或下一步动作不够明确。"

        return {
            "task_completion": self._metric_detail(
                metrics["task_completion"],
                task_reason,
                primary_positive,
                "围绕未覆盖规则补齐明确话术，并在结尾说明处理时效和下一步动作。",
            ),
            "instruction_following": self._metric_detail(
                metrics["instruction_following"],
                instruction_reason,
                primary_positive,
                "将必须动作和禁止话术作为生成前检查清单，降低越权承诺风险。",
            ),
            "call_flow_coverage": self._metric_detail(
                metrics["call_flow_coverage"],
                call_flow_reason,
                primary_positive,
                "按任务指令中的外呼流程逐步推进，避免跳过身份确认、核心说明、分支引导和收尾确认。",
            ),
            "constraint_compliance": self._metric_detail(
                metrics["constraint_compliance"],
                constraint_reason,
                first_evidence,
                "对开车、打断、优惠、排名、恶劣天气等高风险分支设置硬约束，先规避风险再继续沟通。",
            ),
            "context_consistency": self._metric_detail(
                metrics["context_consistency"],
                context_reason,
                last_evidence,
                "每轮回复先承接外呼对象新增信息，再推进下一步流程。",
            ),
            "response_quality": self._metric_detail(
                metrics["response_quality"],
                quality_reason,
                last_evidence,
                "保持简短、自然、可执行的外呼话术，避免模板化重复和过长解释。",
            ),
        }

    def _metric_detail(
        self,
        score: float,
        reason: str,
        evidence: Dict[str, Any],
        suggestion: str,
    ) -> Dict[str, Any]:
        evidence_text = evidence.get("evidence_text", "")
        return {
            "score": round(score, 2),
            "deduction_reason": reason,
            "evidence_turns": [evidence.get("turn_index", 1)],
            "evidence_text": evidence_text,
            "evidence_snippets": [evidence_text] if evidence_text else [],
            "suggestion": suggestion,
        }

    def _metric_explanations(self, metric_details: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for key in SCORE_WEIGHTS:
            detail = metric_details.get(key, {})
            rows.append(
                {
                    "metric_name": METRIC_NAMES.get(key, key),
                    "metric_key": key,
                    "score": detail.get("score", 0),
                    "deduction_reason": detail.get("deduction_reason", "暂无扣分原因"),
                    "evidence_turns": detail.get("evidence_turns", []),
                    "evidence_text": detail.get("evidence_text")
                    or " / ".join(detail.get("evidence_snippets", [])),
                    "suggestion": detail.get("suggestion", "暂无优化建议"),
                }
            )
        return rows

    def _build_evidence_messages(
        self,
        rule_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        evidence_by_turn: Dict[int, Dict[str, Any]] = {}
        evidence_sources = []
        evidence_sources.extend(rule_result.get("matched_evidence", {}).items())
        evidence_sources.extend(rule_result.get("missed_evidence", {}).items())
        evidence_sources.extend(rule_result.get("violated_evidence", {}).items())
        evidence_sources.extend(rule_result.get("hidden_violated_evidence", {}).items())

        for rule, evidence in evidence_sources:
            turn_index = int(evidence.get("turn_index", 1))
            row = evidence_by_turn.setdefault(
                turn_index,
                {
                    "turn_index": turn_index,
                    "user_message": evidence.get("user_message", ""),
                    "assistant_message": evidence.get("evidence_text", ""),
                    "related_rules": [],
                },
            )
            row["related_rules"].append(rule)

        if not evidence_by_turn:
            for item in messages:
                evidence_by_turn[int(item.get("turn_index", 1))] = {
                    "turn_index": item.get("turn_index", 1),
                    "user_message": item.get("user_message", ""),
                    "assistant_message": item.get("assistant_message", ""),
                    "related_rules": [],
                }

        return sorted(evidence_by_turn.values(), key=lambda item: item["turn_index"])

    def _build_score_formula(self, metrics: Dict[str, float], score: float) -> Dict[str, Any]:
        components = {
            key: {
                "metric_name": METRIC_NAMES[key],
                "score": metrics.get(key, 0),
                "weight": weight,
                "weighted_score": round(metrics.get(key, 0) * weight, 2),
            }
            for key, weight in SCORE_WEIGHTS.items()
        }
        return {
            "formula_text": (
                "总分 = 任务完成度 * 0.25 + 指令遵循率 * 0.20 + 外呼流程覆盖率 * 0.20 "
                "+ 约束遵守率 * 0.15 + 上下文一致性 * 0.10 + 回复质量 * 0.10"
            ),
            "weights": SCORE_WEIGHTS,
            "components": components,
            "total_score": score,
        }

    def _build_suggestions(
        self,
        missed_rules: List[str],
        violated_rules: List[str],
        repetition_penalty: float,
        unanswered_penalty: float,
    ) -> List[str]:
        suggestions = [
            "把每个业务场景的必问项配置为逐轮检查清单，避免多轮中漏问。",
            "在回复结尾固定输出处理时效、下一步动作和用户需补充的信息。",
        ]
        if missed_rules:
            suggestions.append("针对遗漏规则补充话术：" + "、".join(missed_rules))
        if violated_rules:
            suggestions.append("对禁止规则增加拦截：" + "、".join(violated_rules))
        if repetition_penalty:
            suggestions.append("减少模板化重复，优先引用用户本轮新增信息。")
        if unanswered_penalty:
            suggestions.append("对用户追问的进度、时效、责任边界给出明确回应。")
        return suggestions

    def _build_key_findings(
        self,
        matched_rules: List[str],
        missed_rules: List[str],
        violated_rules: List[str],
        repetition_penalty: float,
    ) -> List[str]:
        findings = [f"已命中规则：{len(matched_rules)} 条"]
        if missed_rules:
            findings.append("遗漏规则：" + "、".join(missed_rules))
        if violated_rules:
            findings.append("违规风险：" + "、".join(violated_rules))
        if repetition_penalty:
            findings.append("多轮回复存在重复表达，建议增强上下文承接。")
        if not missed_rules and not violated_rules:
            findings.append("被测对话模型能够稳定覆盖关键外呼任务流程。")
        return findings

    def _assistant_text(self, messages: List[Dict[str, Any]]) -> str:
        return "\n".join(item.get("assistant_message", "") for item in messages)

    def _task_type(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
        task_type = task_payload.get("task_type") or ""
        if task_type:
            return task_type
        text = self._joined(
            task_payload.get("instruction_text", ""),
            task_payload.get("name", ""),
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("required_rules", []),
        )
        if self._has_any(text, ["飞毛腿", "骑手", "配送", "站长"]):
            return "rider_outbound"
        if self._has_any(text, ["课程", "直播", "低延迟", "机构", "商家", "负责人"]):
            return "course_platform_outbound"
        return "generic_outbound"

    def _joined(self, *values: Any) -> str:
        parts: List[str] = []
        for value in values:
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            elif isinstance(value, dict):
                parts.append(str(value))
            elif value is not None:
                parts.append(str(value))
        return " ".join(parts)

    def _dedupe(self, values: List[str]) -> List[str]:
        return list(dict.fromkeys([item for item in values if item]))

    def _evidence_row(self, message: Dict[str, Any], evidence_text: str) -> Dict[str, Any]:
        return {
            "turn_index": message.get("turn_index", 1),
            "evidence_text": evidence_text,
            "user_message": message.get("user_message", ""),
        }

    def _has_any(self, text: str, keywords: List[str]) -> bool:
        return any(keyword and keyword in text for keyword in self._variants(*keywords))

    def _variants(self, *terms: str) -> List[str]:
        variants: List[str] = []
        for term in terms:
            if not term:
                continue
            variants.append(term)
            try:
                variants.append(term.encode("utf-8").decode("gbk", errors="ignore"))
            except Exception:
                continue
        return list(dict.fromkeys(variants))

    def _repetition_penalty(self, messages: List[Dict[str, Any]]) -> float:
        replies = [item.get("assistant_message", "") for item in messages if item.get("assistant_message")]
        penalty = 0.0
        for previous, current in zip(replies, replies[1:]):
            if previous == current:
                penalty += 14
            elif SequenceMatcher(None, previous, current).ratio() > 0.88:
                penalty += 6
        return penalty

    def _repetition_evidence(self, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        previous = None
        for item in messages:
            current = item.get("assistant_message", "")
            if previous and current:
                previous_text, previous_item = previous
                if is_similar_text(current, previous_text) or SequenceMatcher(None, current, previous_text).ratio() > 0.88:
                    return self._evidence_row(item, current)
            previous = (current, item)
        return None

    def _stalled_followup_evidence(
        self,
        messages: List[Dict[str, Any]],
        task_type: str,
    ) -> Dict[str, Any] | None:
        for index in range(1, len(messages)):
            previous = messages[index - 1]
            current = messages[index]
            user = current.get("user_message", "")
            assistant = current.get("assistant_message", "")
            previous_assistant = previous.get("assistant_message", "")
            if not user or not assistant or not self._is_concrete_followup(user, task_type):
                continue
            if previous_assistant and is_similar_text(assistant, previous_assistant):
                return self._evidence_row(current, assistant)
            if task_type == "course_platform_outbound" and self._has_any(
                user,
                ["哪里", "路径", "怎么配置", "第三方", "Web", "看不到", "在哪里选"],
            ):
                gives_path = self._has_any(assistant, ["Web 控制台", "第三方系统", "直播平台管理", "勾选", "直接选择"])
                repeats_difference = self._has_any(assistant, ["标准延迟", "低延迟约", "5-10 秒", "1-2 秒", "发布选项"])
                if repeats_difference and not gives_path:
                    return self._evidence_row(current, assistant)
            if task_type == "rider_outbound" and self._has_any(user, ["记录", "不完成", "没完成", "会怎么样", "影响"]):
                answers_impact = self._has_any(assistant, ["X 单", "Y 单", "合同", "派单", "影响", "记录"])
                repeats_safety = self._has_any(assistant, ["安全第一", "能跑再接单"]) and self._has_any(
                    previous_assistant,
                    ["安全第一", "能跑再接单"],
                )
                if repeats_safety or not answers_impact:
                    return self._evidence_row(current, assistant)
        return None

    def _is_concrete_followup(self, user_message: str, task_type: str) -> bool:
        if task_type == "rider_outbound":
            return self._has_any(
                user_message,
                ["怎么", "多少", "会不会", "会怎么样", "影响", "记录", "退出", "排名", "安全", "天气", "X 单", "Y 单"],
            )
        if task_type == "course_platform_outbound":
            return self._has_any(
                user_message,
                ["哪里", "路径", "怎么配置", "第三方", "Web", "费用", "优惠券", "区别", "差多少", "选"],
            )
        return self._has_any(user_message, ["怎么", "哪里", "下一步", "为什么"])

    def _unanswered_penalty(self, messages: List[Dict[str, Any]]) -> float:
        penalty = 0.0
        for item in messages:
            user_message = item.get("user_message", "")
            assistant_message = item.get("assistant_message", "")
            if self._has_any(user_message, ["多久", "时效", "进度", "结果", "会怎样"]) and not self._has_any(
                assistant_message,
                ["规则", "影响", "合同", "派单", "稍后", "明天", "费用"],
            ):
                penalty += 5
            if self._has_any(user_message, ["能不能", "取消", "退出", "看不到", "区别", "费用"]) and not self._has_any(
                assistant_message,
                ["规则", "确认", "App", "配置", "标准直播", "低延迟", "费用", "发布方式"],
            ):
                penalty += 4
        return min(penalty, 14)

    def _risk_phrase_penalty(self, messages: List[Dict[str, Any]]) -> float:
        text = self._assistant_text(messages)
        risk_terms = [
            "一定获得资格",
            "保证报上",
            "保证资格",
            "强制配送",
            "必须冒雨",
            "不跑不行",
            "送优惠券",
            "保证优惠",
            "承诺折扣",
            "你必须听完",
        ]
        return 12 if self._has_any(text, risk_terms) else 0

    def _brevity_penalty(self, messages: List[Dict[str, Any]], task_type: str = "generic_outbound") -> float:
        replies = [item.get("assistant_message", "") for item in messages if item.get("assistant_message")]
        if not replies:
            return 12
        avg_len = sum(len(reply) for reply in replies) / len(replies)
        if task_type == "course_platform_outbound":
            penalty = 0
            for item in messages:
                reply = item.get("assistant_message", "")
                if not reply:
                    continue
                length = self._reply_len(reply)
                limit = 24 if self._detail_requested(item.get("user_message", "")) else 22
                if length > limit or self._is_dense_course_reply(reply):
                    penalty += 12
                elif length > 20:
                    penalty += 4
            return min(penalty, 18)
        if task_type == "rider_outbound":
            business_replies = [
                item.get("assistant_message", "")
                for item in messages
                if item.get("assistant_message") and item.get("turn_index") != 0
            ]
            over_limit = [reply for reply in business_replies if len(reply) > 30]
            if over_limit:
                return 16
            if avg_len > 45:
                return 8
            return 0
        if avg_len > 140:
            return 10
        return 0

    def _weighted_score(self, metrics: Dict[str, float]) -> float:
        return round(sum(float(metrics.get(key, 0)) * weight for key, weight in SCORE_WEIGHTS.items()), 2)

    def _clamp(self, value: float, minimum: float = 0, maximum: float = 100) -> float:
        return round(max(minimum, min(maximum, value)), 2)
