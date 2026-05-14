from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.run import EvaluationRun, RunMessage
from app.schemas.run import MessageRead, RunRead, RunStartRequest, RunStartResponse
from app.services.evaluation_service import EvaluationService


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("/start", response_model=RunStartResponse)
def start_run(payload: RunStartRequest, session: Session = Depends(get_session)) -> dict:
    return EvaluationService(session).start_evaluation(payload.task_id, payload.case_id)


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: int, session: Session = Depends(get_session)) -> EvaluationRun:
    run = session.get(EvaluationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/{run_id}/messages", response_model=List[MessageRead])
def get_run_messages(run_id: int, session: Session = Depends(get_session)) -> List[RunMessage]:
    if not session.get(EvaluationRun, run_id):
        raise HTTPException(status_code=404, detail="run not found")
    statement = select(RunMessage).where(RunMessage.run_id == run_id).order_by(RunMessage.turn_index)
    return list(session.exec(statement).all())
