from collections import Counter

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.core.database import get_session
from app.models.batch_run import EvaluationBatchRun
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
    total_batches = session.exec(select(func.count()).select_from(EvaluationBatchRun)).one()
    avg_score = session.exec(select(func.avg(EvaluationReport.total_score))).one() or 0
    avg_latency = session.exec(select(func.avg(EvaluationReport.avg_latency_ms))).one() or 0
    avg_pass_rate = session.exec(select(func.avg(EvaluationBatchRun.pass_rate))).one() or 0
    reports = list(session.exec(select(EvaluationReport).order_by(EvaluationReport.report_id.desc())).all())
    recent_batches = list(
        session.exec(select(EvaluationBatchRun).order_by(EvaluationBatchRun.id.desc()).limit(5)).all()
    )

    failure_counter: Counter[str] = Counter()
    for report in reports:
        failure_counter.update(report.failed_rules)

    recent = list(reversed(reports[:7]))
    return {
        "total_tasks": total_tasks,
        "total_cases": total_cases,
        "total_runs": total_runs,
        "total_batches": total_batches,
        "avg_score": round(float(avg_score), 2),
        "avg_latency_ms": round(float(avg_latency), 2),
        "avg_pass_rate": round(float(avg_pass_rate), 2),
        "failed_rules_top5": [
            {"rule_name": rule, "count": count} for rule, count in failure_counter.most_common(5)
        ],
        "recent_batches": [
            {
                "batch_id": batch.id,
                "status": batch.status,
                "total_runs": batch.total_runs,
                "finished_runs": batch.finished_runs,
                "average_score": batch.average_score,
                "pass_rate": batch.pass_rate,
                "created_at": batch.created_at,
            }
            for batch in recent_batches
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
