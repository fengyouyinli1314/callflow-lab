from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.batch_run import BatchRunRead, BatchRunStartRequest, BatchRunStartResponse
from app.services.batch_evaluation_service import BatchEvaluationService


router = APIRouter(prefix="/api/batch-runs", tags=["batch-runs"])


@router.post("/start", response_model=BatchRunStartResponse)
def start_batch_run(payload: BatchRunStartRequest, session: Session = Depends(get_session)) -> Dict[str, Any]:
    return BatchEvaluationService(session).start_batch(payload)


@router.get("/{batch_id}", response_model=BatchRunRead)
def get_batch_run(batch_id: int, session: Session = Depends(get_session)) -> Dict[str, Any]:
    return BatchEvaluationService(session).get_batch(batch_id)


@router.get("/{batch_id}/summary")
def get_batch_run_summary(batch_id: int, session: Session = Depends(get_session)) -> Dict[str, Any]:
    return BatchEvaluationService(session).build_summary(batch_id, persist=False)
