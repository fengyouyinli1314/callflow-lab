from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class EvaluationRun(SQLModel, table=True):
    __tablename__ = "evaluation_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(index=True, foreign_key="evaluation_tasks.id")
    case_id: int = Field(index=True, foreign_key="evaluation_cases.id")
    status: str = Field(default="running", max_length=40)
    total_score: float = Field(default=0)
    model_provider: str = Field(default="mock_fallback", max_length=80)
    model_name: str = Field(default="mock_fallback", max_length=120)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


class RunMessage(SQLModel, table=True):
    __tablename__ = "run_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True, foreign_key="evaluation_runs.id")
    turn_index: int = Field(index=True)
    user_message: str
    assistant_message: str
    latency_ms: float = Field(default=0)
    rule_score: float = Field(default=0)
    matched_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    missed_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    violated_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    detail: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
