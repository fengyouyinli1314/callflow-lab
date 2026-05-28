from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.case import EvaluationCase
from app.models.task import EvaluationTask
from app.schemas.case import CaseCreate, CaseDraft, CaseGenerateRequest, CaseRead, CaseUpdate
from app.services.case_mode import normalize_case_mode
from app.services.case_registry import deduplicate_cases, existing_case, get_or_create_case, unique_cases
from app.services.case_generator_service import CaseGeneratorService


router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.post("", response_model=CaseRead)
def create_case(payload: CaseCreate, session: Session = Depends(get_session)) -> EvaluationCase:
    if not session.get(EvaluationTask, payload.task_id):
        raise HTTPException(status_code=404, detail="task not found")
    case, _ = get_or_create_case(session, payload.model_dump())
    session.commit()
    session.refresh(case)
    return case


@router.get("", response_model=List[CaseRead])
def list_cases(
    task_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
) -> List[EvaluationCase]:
    statement = select(EvaluationCase)
    if task_id is not None:
        statement = statement.where(EvaluationCase.task_id == task_id)
    return unique_cases(session.exec(statement.order_by(EvaluationCase.id)).all())


@router.post("/deduplicate")
def deduplicate_case_records(
    task_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    return deduplicate_cases(session, task_id=task_id)


@router.post("/generate", response_model=List[CaseDraft])
def generate_case_drafts(
    payload: CaseGenerateRequest,
    session: Session = Depends(get_session),
) -> List[dict]:
    task = session.get(EvaluationTask, payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return CaseGeneratorService().generate(
        task=task,
        case_count=payload.case_count,
        difficulty_distribution=payload.difficulty_distribution,
        user_behavior_types=payload.user_behavior_types,
    )


@router.get("/{case_id}", response_model=CaseRead)
def get_case(case_id: int, session: Session = Depends(get_session)) -> EvaluationCase:
    case = session.get(EvaluationCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    return case


@router.put("/{case_id}", response_model=CaseRead)
def update_case(
    case_id: int,
    payload: CaseUpdate,
    session: Session = Depends(get_session),
) -> EvaluationCase:
    case = session.get(EvaluationCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    data = payload.model_dump(exclude_unset=True)
    if "task_id" in data and not session.get(EvaluationTask, data["task_id"]):
        raise HTTPException(status_code=404, detail="task not found")
    if "case_mode" in data:
        case_context = {
            "name": data.get("name", case.name),
            "user_profile": data.get("user_profile", case.user_profile),
            "initial_message": data.get("initial_message", case.initial_message),
            "expected_goals": data.get("expected_goals", case.expected_goals),
            "expected_steps": data.get("expected_steps", getattr(case, "expected_steps", [])),
            "required_rules": data.get("required_rules", case.required_rules),
            "trigger_conditions": data.get("trigger_conditions", case.trigger_conditions),
            "user_behavior_type": data.get("user_behavior_type", case.user_behavior_type),
        }
        data["case_mode"] = normalize_case_mode(data.get("case_mode"), case_context)
    next_task_id = data.get("task_id", case.task_id)
    next_name = data.get("name", case.name)
    next_initial_message = data.get("initial_message", case.initial_message)
    duplicate = existing_case(
        session,
        next_task_id,
        next_name,
        next_initial_message,
        exclude_case_id=case_id,
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="duplicate case exists for this task")
    for key, value in data.items():
        setattr(case, key, value)
    session.add(case)
    session.commit()
    session.refresh(case)
    return case


@router.delete("/{case_id}")
def delete_case(case_id: int, session: Session = Depends(get_session)) -> dict:
    case = session.get(EvaluationCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    session.delete(case)
    session.commit()
    return {"message": "case deleted"}
