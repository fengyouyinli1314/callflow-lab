from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.report import EvaluationReport
from app.schemas.report import ReportRead, ReportSummary


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=List[ReportRead])
def list_reports(session: Session = Depends(get_session)) -> List[Dict[str, Any]]:
    reports = list(session.exec(select(EvaluationReport).order_by(EvaluationReport.report_id.desc())).all())
    return [_serialize_report(report) for report in reports]


@router.get("/{report_id}", response_model=ReportRead)
def get_report(report_id: int, session: Session = Depends(get_session)) -> Dict[str, Any]:
    report = session.get(EvaluationReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return _serialize_report(report)


@router.get("/{report_id}/summary", response_model=ReportSummary)
def get_report_summary(report_id: int, session: Session = Depends(get_session)) -> dict:
    report = session.get(EvaluationReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return {
        "report_id": report.report_id,
        "total_score": report.total_score,
        "failed_rules": report.failed_rules or [],
        "suggestions": report.suggestions or [],
        "key_findings": (report.explainability or {}).get("key_findings", []),
    }


def _serialize_report(report: EvaluationReport) -> Dict[str, Any]:
    metric_details = report.metric_details or {}
    metric_explanations = report.metric_explanations or _metric_explanations_from_details(metric_details)
    explainability = report.explainability or {}
    score_formula = report.score_formula or explainability.get("score_formula") or _fallback_score_formula(report)
    active_rules = report.active_rules or explainability.get("active_rules", {})
    llm_judge_result = report.llm_judge_result or explainability.get("llm_judge_result", {})
    judge_source = (
        llm_judge_result.get("judge_source")
        or explainability.get("judge_source")
        or _fallback_judge_source(llm_judge_result)
    )
    judge_source = _normalize_judge_source(judge_source, llm_judge_result)
    untriggered_rules = (
        active_rules.get("untriggered_rules")
        or active_rules.get("not_applicable_rules")
        or explainability.get("untriggered_rules")
        or []
    )
    return {
        "report_id": report.report_id,
        "run_id": report.run_id,
        "task_id": report.task_id,
        "case_id": report.case_id,
        "total_score": report.total_score,
        "task_completion": report.task_completion,
        "instruction_following": report.instruction_following,
        "call_flow_coverage": report.call_flow_coverage,
        "constraint_compliance": report.constraint_compliance or report.safety_compliance,
        "context_consistency": report.context_consistency,
        "safety_compliance": report.safety_compliance or report.constraint_compliance,
        "response_quality": report.response_quality,
        "avg_latency_ms": report.avg_latency_ms,
        "failed_rule_count": report.failed_rule_count or len(report.failed_rules or []),
        "total_turns": report.total_turns,
        "matched_rules": report.matched_rules or [],
        "failed_rules": report.failed_rules or [],
        "active_rules": active_rules,
        "pending_rules": report.pending_rules or explainability.get("pending_rules", []),
        "untriggered_rules": untriggered_rules,
        "visible_business_rules": explainability.get("visible_business_rules", {}),
        "hidden_guardrail_rules": explainability.get("hidden_guardrail_rules", {}),
        "full_flow_expected_steps": explainability.get("full_flow_expected_steps", {}),
        "late_satisfied_rules": explainability.get("late_satisfied_rules", []),
        "rule_lifecycle": explainability.get("rule_lifecycle", {}),
        "case_focus": explainability.get("case_focus", active_rules.get("case_focus", "")),
        "active_rule_names": explainability.get("active_rule_names", active_rules.get("active_rule_names", [])),
        "current_stage": report.current_stage or explainability.get("current_stage", ""),
        "memory_state": explainability.get("memory_state", {}),
        "deduction_reason": explainability.get("deduction_reason", ""),
        "active_rules_explanation": report.active_rules_explanation
        or explainability.get(
            "active_rules_explanation",
            "本轮仅对当前用例、当前阶段和用户已触发规则评分。",
        ),
        "rule_trace": explainability.get("rule_trace", {}),
        "judge_source": judge_source,
        "llm_judge_result": {**llm_judge_result, "judge_source": judge_source},
        "suggestions": report.suggestions or explainability.get("improvement_suggestions", []),
        "metric_details": metric_details,
        "metric_explanations": metric_explanations,
        "failure_cases": report.failure_cases or [],
        "explainability": explainability,
        "evidence_messages": report.evidence_messages or report.messages or [],
        "score_formula": score_formula,
        "messages": report.messages or [],
        "created_at": report.created_at,
    }


def _metric_explanations_from_details(metric_details: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = {
        "task_completion": "任务完成度",
        "instruction_following": "指令遵循率",
        "call_flow_coverage": "外呼流程覆盖率",
        "constraint_compliance": "约束遵守率",
        "context_consistency": "上下文一致性",
        "response_quality": "回复质量",
    }
    rows: List[Dict[str, Any]] = []
    for key, label in labels.items():
        detail = metric_details.get(key, {})
        rows.append(
            {
                "metric_key": key,
                "metric_name": label,
                "score": detail.get("score", 0),
                "deduction_reason": detail.get("deduction_reason", "暂无明显扣分原因"),
                "evidence_turns": detail.get("evidence_turns", []),
                "evidence_text": detail.get("evidence_text")
                or " / ".join(detail.get("evidence_snippets", [])),
                "suggestion": detail.get("suggestion", "暂无优化建议"),
            }
        )
    return rows


def _fallback_score_formula(report: EvaluationReport) -> Dict[str, Any]:
    weights = {
        "task_completion": 0.25,
        "instruction_following": 0.20,
        "call_flow_coverage": 0.20,
        "constraint_compliance": 0.15,
        "context_consistency": 0.10,
        "response_quality": 0.10,
    }
    metrics = {
        "task_completion": report.task_completion,
        "instruction_following": report.instruction_following,
        "call_flow_coverage": report.call_flow_coverage,
        "constraint_compliance": report.constraint_compliance or report.safety_compliance,
        "context_consistency": report.context_consistency,
        "response_quality": report.response_quality,
    }
    return {
        "formula_text": (
            "总分 = 任务完成度 * 0.25 + 指令遵循率 * 0.20 + 外呼流程覆盖率 * 0.20 "
            "+ 约束遵守率 * 0.15 + 上下文一致性 * 0.10 + 回复质量 * 0.10"
        ),
        "combine_formula_text": "各指标融合分 = rule_score * 0.7 + judge_score * 0.3",
        "weights": weights,
        "components": {
            key: {
                "score": value,
                "rule_score": value,
                "judge_score": value,
                "combined_score": value,
                "combine_formula": "rule_score * 0.7 + judge_score * 0.3",
                "combine_formula_text": f"{value} * 0.7 + {value} * 0.3 = {value}",
                "weight": weights[key],
                "weighted_score": round(value * weights[key], 2),
            }
            for key, value in metrics.items()
        },
        "total_score": report.total_score,
    }


def _fallback_judge_source(llm_judge_result: Dict[str, Any]) -> Dict[str, Any]:
    provider = str(llm_judge_result.get("provider") or "mock")
    requested = str(llm_judge_result.get("provider_requested") or provider)
    fallback_used = bool(llm_judge_result.get("fallback_used", provider == "mock"))
    if provider == "mock" or fallback_used:
        return {
            "source_type": "mock_fallback",
            "label": "规则辅助评审",
            "provider": provider,
            "provider_requested": requested,
            "model": llm_judge_result.get("model", ""),
            "fallback_used": fallback_used,
            "fallback_reason": llm_judge_result.get("fallback_reason", ""),
            "description": "本处为报告端规则辅助评审，基于规则评分结果生成综合说明；被测模型回复仍按所选接入方式生成。",
            "config_hint": "",
        }
    return {
        "source_type": "openai_compatible",
        "label": "大模型辅助评审",
        "provider": provider,
        "provider_requested": requested,
        "model": llm_judge_result.get("model", ""),
        "fallback_used": False,
        "fallback_reason": "",
        "description": "本处使用外部评审器结合规则结果生成综合说明。",
        "config_hint": "",
    }


def _normalize_judge_source(judge_source: Dict[str, Any], llm_judge_result: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(judge_source or {})
    provider = str(source.get("provider") or llm_judge_result.get("provider") or "mock")
    fallback_used = bool(source.get("fallback_used") or llm_judge_result.get("fallback_used") or provider == "mock")
    source_type = str(source.get("source_type") or source.get("sourceType") or ("mock_fallback" if fallback_used else "openai_compatible"))

    if source_type == "mock_fallback" or fallback_used:
        description = "本处为报告端规则辅助评审，基于规则评分结果生成综合说明；被测模型回复仍按所选接入方式生成。"
        fallback_reason = str(source.get("fallback_reason") or llm_judge_result.get("fallback_reason") or "")
        if fallback_reason and fallback_reason != "EVALUATOR_API_KEY or EVALUATOR_BASE_URL is not configured":
            description = f"{description} 评审器外部调用未采用，原因：{_readable_fallback_reason(fallback_reason)}。"
        source.update(
            {
                "source_type": "mock_fallback",
                "label": "规则辅助评审",
                "description": description,
                "config_hint": "",
                "fallback_reason": fallback_reason,
            }
        )
        return source

    source.update(
        {
            "source_type": "openai_compatible",
            "label": "大模型辅助评审" if source.get("label") in {"真实大模型评审", "", None} else source.get("label"),
            "description": "本处使用外部评审器结合规则结果生成综合说明。",
            "config_hint": "",
        }
    )
    return source


def _readable_fallback_reason(reason: str) -> str:
    if reason.startswith("openai_compatible evaluator HTTP error"):
        status = reason.replace("openai_compatible evaluator HTTP error", "").strip()
        return f"外部评审器 HTTP 请求失败{f'（状态码 {status}）' if status else ''}"
    if reason == "openai_compatible evaluator request failed":
        return "外部评审器请求失败"
    if reason == "openai_compatible evaluator returned non-JSON API response":
        return "外部评审器接口响应不是 JSON"
    if reason == "openai_compatible evaluator API error response":
        return "外部评审器接口返回错误"
    if reason == "openai_compatible evaluator returned empty response":
        return "外部评审器返回为空"
    if reason == "openai_compatible evaluator returned invalid JSON response":
        return "外部评审器没有返回有效 JSON 评分结构"
    if reason == "openai_compatible evaluator returned empty or invalid response":
        return "外部评审器返回为空或不是有效结构化结果"
    if reason == "EVALUATOR_API_KEY or EVALUATOR_BASE_URL is not configured":
        return "评审器 API Key 或 Base URL 未配置"
    return reason
