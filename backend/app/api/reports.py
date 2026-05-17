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
        "active_rules": report.active_rules or explainability.get("active_rules", {}),
        "pending_rules": report.pending_rules or explainability.get("pending_rules", []),
        "current_stage": report.current_stage or explainability.get("current_stage", ""),
        "active_rules_explanation": report.active_rules_explanation
        or explainability.get(
            "active_rules_explanation",
            "本轮仅对当前流程阶段和用户已触发的问题进行评分，后续流程规则暂不扣分。未进入的后续流程不参与当前轮扣分。",
        ),
        "llm_judge_result": report.llm_judge_result or explainability.get("llm_judge_result", {}),
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
                "deduction_reason": detail.get("deduction_reason", "暂无扣分原因"),
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
        "weights": weights,
        "components": {
            key: {
                "score": value,
                "weight": weights[key],
                "weighted_score": round(value * weights[key], 2),
            }
            for key, value in metrics.items()
        },
        "total_score": report.total_score,
    }
