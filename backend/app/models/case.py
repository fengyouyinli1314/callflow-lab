from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class EvaluationCase(SQLModel, table=True):
    __tablename__ = "evaluation_cases"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(index=True, foreign_key="evaluation_tasks.id")
    name: str = Field(index=True, max_length=120)
    user_profile: str
    initial_message: str
    max_turns: int = Field(default=4, ge=1, le=12)
    expected_goals: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    required_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    forbidden_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    difficulty: str = Field(default="中等", max_length=40)
    created_at: datetime = Field(default_factory=datetime.utcnow)
