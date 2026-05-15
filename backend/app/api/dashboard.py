from collections import Counter

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.core.database import get_session
from app.models.case import EvaluationCase
from app.models.report import EvaluationReport
from app.models.run import EvaluationRun
from app.models.task import EvaluationTask


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(session: Session = Depends(get_session)) -> dict:
    total_tasks = session.exec(select(func.count()).select_from(EvaluationTask)).one()
    total_cases = session.exec(select(func.count()).select_from(EvaluationCase)).one()
    total_runs = session.exec(select(func.count()).select_from(EvaluationRun)).one()
    avg_score = session.exec(select(func.avg(EvaluationReport.total_score))).one() or 0
    avg_latency = session.exec(select(func.avg(EvaluationReport.avg_latency_ms))).one() or 0
    reports = list(session.exec(select(EvaluationReport).order_by(EvaluationReport.report_id.desc())).all())

    failure_counter: Counter[str] = Counter()
    for report in reports:
        failure_counter.update(report.failed_rules)

    recent = list(reversed(reports[:7]))
    return {
        "total_tasks": total_tasks,
        "total_cases": total_cases,
        "total_runs": total_runs,
        "avg_score": round(float(avg_score), 2),
        "avg_latency_ms": round(float(avg_latency), 2),
        "failed_rules_top5": [
            {"rule_name": rule, "count": count} for rule, count in failure_counter.most_common(5)
        ],
        "recent_score_trend": [
            {
                "report_id": report.report_id,
                "run_id": report.run_id,
                "score": report.total_score,
                "created_at": report.created_at,
            }
            for report in recent
        ],
    }
