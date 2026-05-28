from datetime import datetime
from typing import List
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.task import EvaluationTask
from app.schemas.task import TaskCreate, TaskListRead, TaskRead, TaskUpdate


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead)
def create_task(payload: TaskCreate, session: Session = Depends(get_session)) -> EvaluationTask:
    data = _task_model_data(payload.model_dump())
    task = EvaluationTask(**data)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.get("", response_model=List[TaskListRead])
def list_tasks(session: Session = Depends(get_session)) -> List[EvaluationTask]:
    excel_tasks = list(
        session.exec(
            select(EvaluationTask)
            .where(EvaluationTask.data_source == "excel_desensitized")
            .order_by(EvaluationTask.id)
        ).all()
    )
    if excel_tasks:
        return excel_tasks
    return list(session.exec(select(EvaluationTask).order_by(EvaluationTask.id)).all())


@router.get("/{task_key}", response_model=TaskRead)
def get_task(task_key: str, session: Session = Depends(get_session)) -> EvaluationTask:
    task = _resolve_task(session, task_key)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.put("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    session: Session = Depends(get_session),
) -> EvaluationTask:
    task = session.get(EvaluationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    for key, value in _task_model_data(payload.model_dump(exclude_unset=True)).items():
        setattr(task, key, value)
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@router.delete("/{task_id}")
def delete_task(task_id: int, session: Session = Depends(get_session)) -> dict:
    task = session.get(EvaluationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    session.delete(task)
    session.commit()
    return {"message": "task deleted"}


def _task_model_data(data: dict) -> dict:
    data = dict(data)
    conversation_flow = data.pop("conversation_flow", None)
    if conversation_flow is not None and not data.get("call_flow"):
        data["call_flow"] = conversation_flow
    return data


def _resolve_task(session: Session, task_key: str) -> EvaluationTask | None:
    key = unquote(str(task_key or "")).strip()
    if key.isdigit():
        task = session.get(EvaluationTask, int(key))
        if task:
            return task
    task = session.exec(select(EvaluationTask).where(EvaluationTask.name == key)).first()
    if task:
        return task

    candidates = [key]
    if key.lower().endswith("id"):
        candidates.append(key[:-2].strip())
    for candidate in candidates:
        if not candidate:
            continue
        task = session.exec(select(EvaluationTask).where(EvaluationTask.name == candidate)).first()
        if task:
            return task

    tasks = list(session.exec(select(EvaluationTask)).all())
    for task in tasks:
        name = task.name or ""
        if name and (key.startswith(name) or name in key):
            return task
    inferred_type = _infer_task_type_from_key(key)
    if inferred_type:
        return session.exec(
            select(EvaluationTask)
            .where(EvaluationTask.task_type == inferred_type)
            .order_by(EvaluationTask.data_source, EvaluationTask.id)
        ).first()
    return None


def _infer_task_type_from_key(key: str) -> str:
    if any(keyword in key for keyword in ["飞毛腿", "骑手", "配送", "派单"]):
        return "rider_outbound"
    if any(keyword in key for keyword in ["课程", "直播", "低延迟", "机构", "负责人"]):
        return "course_platform_outbound"
    return ""
