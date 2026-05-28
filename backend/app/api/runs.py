from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.run import EvaluationRun, RunMessage
from app.schemas.run import MessageRead, RunRead, RunStartRequest, RunStartResponse
from app.services.evaluation_service import EvaluationService
from app.services.memory_service import load_memory


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("/start", response_model=RunStartResponse)
def start_run(payload: RunStartRequest, session: Session = Depends(get_session)) -> dict:
    return EvaluationService(session).start_evaluation(
        payload.task_id,
        payload.case_id,
        payload.model_provider,
        payload.model_name,
    )


@router.post("/stream")
def stream_run(payload: RunStartRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    events = EvaluationService(session).stream_evaluation_events(
        payload.task_id,
        payload.case_id,
        payload.model_provider,
        payload.model_name,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: int, session: Session = Depends(get_session)) -> EvaluationRun:
    run = session.get(EvaluationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if not run.memory_state:
        run.memory_state = load_memory(run)
    return run


@router.get("/{run_id}/messages", response_model=List[MessageRead])
def get_run_messages(run_id: int, session: Session = Depends(get_session)) -> List[RunMessage]:
    if not session.get(EvaluationRun, run_id):
        raise HTTPException(status_code=404, detail="run not found")
    statement = select(RunMessage).where(RunMessage.run_id == run_id).order_by(RunMessage.turn_index)
    return list(session.exec(statement).all())
