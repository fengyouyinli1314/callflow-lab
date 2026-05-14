from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.report import EvaluationReport
from app.schemas.report import ReportRead, ReportSummary


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=List[ReportRead])
def list_reports(session: Session = Depends(get_session)) -> List[EvaluationReport]:
    return list(session.exec(select(EvaluationReport).order_by(EvaluationReport.report_id.desc())).all())


@router.get("/{report_id}", response_model=ReportRead)
def get_report(report_id: int, session: Session = Depends(get_session)) -> EvaluationReport:
    report = session.get(EvaluationReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@router.get("/{report_id}/summary", response_model=ReportSummary)
def get_report_summary(report_id: int, session: Session = Depends(get_session)) -> dict:
    report = session.get(EvaluationReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return {
        "report_id": report.report_id,
        "total_score": report.total_score,
        "failed_rules": report.failed_rules,
        "suggestions": report.suggestions,
        "key_findings": report.explainability.get("key_findings", []),
    }
