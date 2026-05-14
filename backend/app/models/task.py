from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class EvaluationTask(SQLModel, table=True):
    __tablename__ = "evaluation_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    description: str
    target_scenario: str = Field(index=True, max_length=120)
    system_instruction: str
    evaluation_goal: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
