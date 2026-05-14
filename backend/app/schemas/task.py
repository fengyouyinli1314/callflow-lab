from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel


class TaskBase(SQLModel):
    name: str
    description: str
    target_scenario: str
    system_instruction: str
    evaluation_goal: str


class TaskCreate(TaskBase):
    """Payload for creating an evaluation task."""


class TaskUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_scenario: Optional[str] = None
    system_instruction: Optional[str] = None
    evaluation_goal: Optional[str] = None


class TaskRead(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
