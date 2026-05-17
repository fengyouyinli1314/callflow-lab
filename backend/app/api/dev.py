from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.report import EvaluationReport
from app.models.run import EvaluationRun, RunMessage


router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/reset-runs")
def reset_runs(session: Session = Depends(get_session)) -> dict:
    report_count = len(session.exec(select(EvaluationReport)).all())
    message_count = len(session.exec(select(RunMessage)).all())
    run_count = len(session.exec(select(EvaluationRun)).all())

    session.exec(delete(EvaluationReport))
    session.exec(delete(RunMessage))
    session.exec(delete(EvaluationRun))
    session.commit()
    return {
        "message": "runs, messages and reports cleared",
        "deleted": {
            "runs": run_count,
            "messages": message_count,
            "reports": report_count,
        },
    }
