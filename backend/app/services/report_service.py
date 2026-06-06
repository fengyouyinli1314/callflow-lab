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
        llm_result = self._filter_llm_result_to_active_rules(rule_result, llm_result)
        llm_result = dict(llm_result)
        judge_source = self._judge_source_summary(llm_result)
        llm_result["judge_source"] = judge_source
        metrics = self._combine_metrics(rule_result, llm_result)
        score_formula = self._score_formula(metrics, rule_result, llm_result)
        evidence_messages = self._combine_evidence_messages(rule_result, llm_result, messages)
        failure_cases = self._combine_failure_cases(rule_result, llm_result, messages)
        suggestions = self._combine_suggestions(rule_result, llm_result)
        final_memory_state = self._final_memory_state(messages)
        metric_explanations = self._sync_metric_explanation_scores(
            rule_result.get("metric_explanations", []),
            rule_result,
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
                "judge_source": judge_source,
                "score_formula": score_formula,
                "rule_trace": rule_result.get("rule_trace", {}),
                "memory_state": final_memory_state,
            },
            evidence_messages=evidence_messages,
            score_formula=score_formula,
            messages=messages,
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def _final_memory_state(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in reversed(messages):
            detail = item.get("detail") or {}
            memory_state = detail.get("memory_state") or detail.get("memoryState")
            if isinstance(memory_state, dict) and memory_state:
                return memory_state
        return {}

    def _combine_metrics(self, rule_result: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, float]:
        combined = {}
        for field in METRIC_FIELDS:
            rule_value = self._numeric_score(rule_result["metrics"][field])
            llm_value = self._numeric_score(llm_result.get(field, rule_value), rule_value)
            combined[field] = round(rule_value * 0.7 + llm_value * 0.3, 2)
        combined["total_score"] = round(sum(combined[field] * SCORE_WEIGHTS[field] for field in METRIC_FIELDS), 2)
        combined["failed_rule_count"] = self._numeric_score(rule_result["metrics"].get("failed_rule_count", 0))
        combined["safety_compliance"] = combined["constraint_compliance"]
        return combined

    def _score_formula(
        self,
        metrics: Dict[str, float],
        rule_result: Dict[str, Any] | None = None,
        llm_result: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        rule_result = rule_result or {}
        llm_result = llm_result or {}
        components = {
            key: self._score_component(key, metrics, rule_result, llm_result)
            for key in SCORE_WEIGHTS
        }
        return {
            "formula_text": (
                "总分 = 任务完成度 * 0.25 + 指令遵循率 * 0.20 + 外呼流程覆盖率 * 0.20 "
                "+ 约束遵守率 * 0.15 + 上下文一致性 * 0.10 + 回复质量 * 0.10"
            ),
            "combine_formula_text": "各指标融合分 = rule_score * 0.7 + judge_score * 0.3",
            "weights": SCORE_WEIGHTS,
            "components": components,
            "total_score": metrics["total_score"],
        }

    def _score_component(
        self,
        key: str,
        metrics: Dict[str, float],
        rule_result: Dict[str, Any],
        llm_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        rule_score = self._numeric_score((rule_result.get("metrics") or {}).get(key, metrics.get(key, 0)))
        judge_score = self._numeric_score(llm_result.get(key, rule_score), rule_score)
        combined_score = self._numeric_score(metrics.get(key, 0))
        weight = SCORE_WEIGHTS[key]
        return {
            "metric_name": METRIC_NAMES[key],
            "score": combined_score,
            "rule_score": round(rule_score, 2),
            "judge_score": round(judge_score, 2),
            "combined_score": round(combined_score, 2),
            "combine_formula": "rule_score * 0.7 + judge_score * 0.3",
            "combine_formula_text": (
                f"{round(rule_score, 2)} * 0.7 + {round(judge_score, 2)} * 0.3 = "
                f"{round(combined_score, 2)}"
            ),
            "weight": weight,
            "weighted_score": round(combined_score * weight, 2),
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

    def _filter_llm_result_to_active_rules(
        self,
        rule_result: Dict[str, Any],
        llm_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed = set(self._active_visible_rules(rule_result))
        if not allowed:
            return llm_result
        filtered = dict(llm_result)
        filtered["evidence"] = [
            item
            for item in llm_result.get("evidence", []) or []
            if not isinstance(item, dict)
            or str(item.get("issue") or item.get("rule_name") or "") in allowed
            or "未发现" in str(item.get("issue") or "")
        ]
        filtered["failed_rules"] = [
            rule for rule in llm_result.get("failed_rules", []) or [] if str(rule) in allowed
        ]
        filtered["active_visible_rules"] = sorted(allowed)
        return filtered

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
        return list(dict.fromkeys([str(item).strip() for item in values if str(item).strip()]))

    def _judge_source_summary(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        provider = str(llm_result.get("provider") or "mock")
        requested = str(llm_result.get("provider_requested") or provider)
        fallback_used = bool(llm_result.get("fallback_used", False))
        model = str(llm_result.get("model") or "")
        fallback_reason = str(llm_result.get("fallback_reason") or "")
        is_mock = provider == "mock" or fallback_used
        if is_mock:
            description = "本处为报告端规则辅助评审，基于规则评分结果生成综合说明；被测模型回复仍按所选接入方式生成。"
            if fallback_used:
                description = "评审器未完成外部调用，已使用规则辅助评审生成综合说明；被测模型回复不受影响。"
            return {
                "source_type": "mock_fallback",
                "label": "规则辅助评审",
                "provider": provider,
                "provider_requested": requested,
                "model": model,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "description": description,
                "config_hint": "",
            }
        return {
            "source_type": "openai_compatible",
            "label": "大模型辅助评审",
            "provider": provider,
            "provider_requested": requested,
            "model": model,
            "fallback_used": False,
            "fallback_reason": "",
            "description": "本处使用外部评审器结合规则结果生成综合说明。",
            "config_hint": "",
        }

    def _sync_metric_explanation_scores(
        self,
        metric_explanations: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
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
            rule_score = self._numeric_score((rule_result.get("metrics") or {}).get(key, item.get("score", 0)))
            judge_score = self._numeric_score(llm_result.get(key, rule_score), rule_score)
            combined_score = metrics.get(key, item.get("score", 0))
            item["score"] = combined_score
            item["rule_score"] = round(rule_score, 2)
            item["judge_score"] = round(judge_score, 2)
            item["combined_score"] = round(combined_score, 2)
            item["combine_formula"] = "rule_score * 0.7 + judge_score * 0.3"
            item["combine_formula_text"] = (
                f"{round(rule_score, 2)} * 0.7 + {round(judge_score, 2)} * 0.3 = "
                f"{round(combined_score, 2)}"
            )
            item.setdefault("deduction_reason", "暂无明显扣分原因")
            item.setdefault("evidence_turns", [])
            item.setdefault("evidence_text", "")
            item.setdefault("suggestion", "暂无优化建议")
            item["llm_score"] = judge_score
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
                "related_rules": [item.get("issue", "综合评估")],
                "issue": item.get("issue", ""),
                "deduction": item.get("deduction", ""),
                "source": "llm_judge",
            }
            key = (turn_index, row["assistant_message"], row["issue"])
            if key not in seen:
                rows.append(row)
                seen.add(key)
        return sorted(rows, key=lambda item: int(item.get("turn_index", 1)))

    def _combine_failure_cases(
        self,
        rule_result: Dict[str, Any],
        llm_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        cases = [
            self._enrich_failure_case(dict(item), rule_result, messages)
            for item in rule_result.get("failure_cases", [])
        ]
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
                self._enrich_llm_failure_case(
                    {
                    "rule_name": issue or "综合评估扣分点",
                    "severity": "medium",
                    "turn_index": int(item.get("turn_index") or 1),
                    "evidence": quote,
                    "deduction_reason": deduction or llm_result.get("overall_reason", ""),
                    "dialogue_snippet": quote,
                    "suggestion": self._first_suggestion(llm_result),
                    "source": "llm_judge",
                    },
                    llm_result,
                )
            )
        return cases

    def _enrich_failure_case(
        self,
        item: Dict[str, Any],
        rule_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        rule = str(item.get("rule_name") or item.get("ruleName") or "")
        trace = self._trace_row_for_rule(rule_result, rule)
        audit = self._failure_audit(rule, item, trace, rule_result, messages)
        item["source"] = item.get("source") or "rule_judge"
        item["source_label"] = item.get("source_label") or "硬规则评分"
        item["activation_turn"] = audit.get("activation_turn")
        item["activation_reason"] = audit.get("activation_reason")
        item["checked_turns"] = audit.get("checked_turns", [])
        item["missing_facts"] = audit.get("missing_facts", [])
        item["closest_reply"] = audit.get("closest_reply", {})
        item["estimated_deduction_points"] = audit.get("estimated_deduction_points", 0)
        item["deduction_impact"] = audit.get("deduction_impact", "")
        item["audit"] = audit
        return item

    def _enrich_llm_failure_case(self, item: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:
        judge_source = llm_result.get("judge_source") or self._judge_source_summary(llm_result)
        item["source_label"] = "LLM-as-a-Judge"
        item["judge_source"] = judge_source
        item["audit"] = {
            "activation_turn": item.get("turn_index"),
            "activation_reason": f"{judge_source.get('label', 'Judge')} 基于完整对话给出的语义扣分点。",
            "checked_turns": [],
            "checked_assistant_replies": [],
            "missing_facts": [],
            "closest_reply": {
                "turn_index": item.get("turn_index"),
                "text": item.get("dialogue_snippet", ""),
            },
            "estimated_deduction_points": 0,
            "deduction_impact": "Judge 证据已进入 30% 综合评估融合分；不单独按硬规则逐条扣分。",
        }
        return item

    def _failure_audit(
        self,
        rule: str,
        failure_case: Dict[str, Any],
        trace: Dict[str, Any],
        rule_result: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        activation_turn = trace.get("activation_turn") or failure_case.get("turn_index")
        try:
            activation_turn_int = int(activation_turn) if activation_turn is not None else None
        except (TypeError, ValueError):
            activation_turn_int = None
        checked_replies = self._checked_assistant_replies(messages, activation_turn_int)
        required_facts = self._required_facts_for_rule(rule)
        closest_reply = self._closest_reply(required_facts, checked_replies)
        missing_facts = self._missing_facts(required_facts, closest_reply.get("text", ""))
        if not missing_facts and rule in set(rule_result.get("missed_rules") or []):
            missing_facts = ["没有形成该规则要求的明确、稳定表述。"]
        estimated = self._estimated_rule_deduction(rule, rule_result)
        return {
            "activation_turn": activation_turn_int,
            "activation_reason": trace.get("activation_reason") or "该规则被当前用例或对话上下文激活。",
            "checked_turns": [item["turn_index"] for item in checked_replies],
            "checked_assistant_replies": checked_replies,
            "required_facts": [item["label"] for item in required_facts],
            "missing_facts": missing_facts,
            "closest_reply": closest_reply,
            "estimated_deduction_points": estimated,
            "deduction_impact": self._deduction_impact_text(rule, estimated, rule_result),
        }

    def _checked_assistant_replies(
        self,
        messages: List[Dict[str, Any]],
        activation_turn: int | None,
    ) -> List[Dict[str, Any]]:
        replies: List[Dict[str, Any]] = []
        for item in messages:
            text = str(item.get("assistant_message") or "")
            if not text:
                continue
            try:
                turn_index = int(item.get("turn_index") or len(replies) + 1)
            except (TypeError, ValueError):
                turn_index = len(replies) + 1
            if activation_turn is not None and turn_index < activation_turn:
                continue
            replies.append({"turn_index": turn_index, "text": text})
        return replies

    def _trace_row_for_rule(self, rule_result: Dict[str, Any], rule: str) -> Dict[str, Any]:
        rows = (rule_result.get("rule_trace") or {}).get("rows") or []
        for row in rows:
            if row.get("rule_name") == rule:
                return dict(row)
        return {}

    def _required_facts_for_rule(self, rule: str) -> List[Dict[str, Any]]:
        mappings = [
            (["前一天", "Z 点", "取消"], [("前一天 Z 点前", ["前一天", "Z 点", "Z点"]), ("飞毛腿报名入口", ["飞毛腿报名", "App"]), ("次日生效", ["次日生效"])]),
            (["App", "飞毛腿报名"], [("App 飞毛腿报名中取消", ["App", "飞毛腿报名", "取消"])]),
            (["次日生效"], [("次日生效", ["次日生效"])]),
            (["标准直播延迟"], [("标准直播延迟 5-10 秒", ["5-10 秒", "5-10秒", "5到10秒"]), ("费用较低", ["费用较低", "费用低", "更便宜"])]),
            (["低延迟直播延迟"], [("低延迟直播延迟 1-2 秒", ["1-2 秒", "1-2秒", "1到2秒"]), ("互动更流畅", ["互动更流畅", "实时互动", "互动流畅"])]),
            (["配置路径", "对应配置"], [("配置入口或路径", ["Web 控制台", "第三方系统", "直播平台管理", "勾选", "直接选择"])]),
            (["企业微信"], [("企业微信添加逻辑", ["企业微信", "添加", "手机号"])]),
            (["费用", "优惠券", "折扣"], [("费用差异", ["费用", "更高", "页面"]), ("不承诺优惠券或折扣", ["不能承诺", "不承诺", "优惠券", "折扣"])]),
            (["排名"], [("按系统排名", ["排名", "系统排名", "按排名"]), ("非站长人工干预", ["不是站长", "非站长", "不能干预", "非人工"])]),
            (["拒单", "取消", "超时", "资格"], [("减少拒单取消超时", ["拒单", "取消", "超时"]), ("有助于保住资格", ["资格", "保住"])]),
            (["单日/多日", "合同完成"], [("X 单或 Y 单要求", ["X 单", "X单", "Y 单", "Y单"]), ("合同或派单影响", ["合同", "派单", "影响"])]),
            (["安全", "天气", "冒险"], [("先安抚并提醒安全", ["安全", "理解", "注意"]), ("不强迫冒险配送", ["不强迫", "能跑再", "安全第一"])]),
            (["稍后再打", "开车"], [("稍后再打", ["稍后再打", "稍后联系"]), ("立即结束且注意安全", ["注意安全", "先不打扰", "结束"])]),
            (["自然简短", "简短自然"], [("简短自然表达", ["。"])]),
        ]
        facts: List[Dict[str, Any]] = []
        for triggers, values in mappings:
            if any(trigger in rule for trigger in triggers):
                facts.extend({"label": label, "keywords": keywords} for label, keywords in values)
        if facts:
            return facts
        cleaned = rule.replace("是否", "").replace("禁止", "").replace("不能", "").strip("：:，,。 ")
        return [{"label": cleaned or rule, "keywords": [cleaned or rule]}]

    def _closest_reply(
        self,
        required_facts: List[Dict[str, Any]],
        checked_replies: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not checked_replies:
            return {"turn_index": None, "text": "", "matched_facts": [], "missing_facts": [item["label"] for item in required_facts]}
        best = checked_replies[-1]
        best_hits: List[str] = []
        best_score = -1
        for reply in checked_replies:
            hits = [
                fact["label"]
                for fact in required_facts
                if self._has_any(str(reply.get("text") or ""), fact.get("keywords", []))
            ]
            if len(hits) >= best_score:
                best = reply
                best_hits = hits
                best_score = len(hits)
        return {
            "turn_index": best.get("turn_index"),
            "text": best.get("text", ""),
            "matched_facts": best_hits,
            "missing_facts": self._missing_facts(required_facts, best.get("text", "")),
        }

    def _missing_facts(self, required_facts: List[Dict[str, Any]], text: str) -> List[str]:
        return [
            fact["label"]
            for fact in required_facts
            if not self._has_any(str(text or ""), fact.get("keywords", []))
        ]

    def _estimated_rule_deduction(self, rule: str, rule_result: Dict[str, Any]) -> float:
        if rule in set(rule_result.get("missed_rules") or []):
            return 8.0
        if rule in set(rule_result.get("violated_rules") or []):
            return 22.0
        if rule in set((rule_result.get("hidden_guardrail_rules") or {}).get("violated") or []):
            return 18.0
        return 0.0

    def _deduction_impact_text(self, rule: str, estimated: float, rule_result: Dict[str, Any]) -> str:
        if not estimated:
            return "该失败项不单独估算硬规则扣分。"
        if rule in set(rule_result.get("missed_rules") or []):
            return f"规则层估算影响约 {estimated:g} 分，并会影响任务完成度、指令遵循或流程覆盖等分项。"
        if rule in set(rule_result.get("violated_rules") or []):
            return f"规则层估算影响约 {estimated:g} 分，并会压低约束遵守率。"
        return f"规则层估算影响约 {estimated:g} 分，属于后台防串场护栏风险。"

    def _has_any(self, text: str, keywords: List[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)

    def _first_suggestion(self, llm_result: Dict[str, Any]) -> str:
        suggestions = llm_result.get("suggestions") or []
        return suggestions[0] if suggestions else "结合任务指令补齐缺失流程，并引用用户问题直接回应。"

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
