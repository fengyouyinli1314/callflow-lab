from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class EvaluationBatchRun(SQLModel, table=True):
    __tablename__ = "evaluation_batch_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = Field(default="running", max_length=40)
    task_ids: List[int] = Field(default_factory=list, sa_column=Column(JSON))
    case_ids: List[int] = Field(default_factory=list, sa_column=Column(JSON))
    model_providers: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    repeat_times: int = Field(default=1)
    total_runs: int = Field(default=0)
    finished_runs: int = Field(default=0)
    failed_runs: int = Field(default=0)
    average_score: float = Field(default=0)
    average_latency_ms: float = Field(default=0)
    pass_rate: float = Field(default=0)
    summary: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


class EvaluationBatchRunItem(SQLModel, table=True):
    __tablename__ = "evaluation_batch_run_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(index=True, foreign_key="evaluation_batch_runs.id")
    task_id: int = Field(index=True, foreign_key="evaluation_tasks.id")
    case_id: int = Field(index=True, foreign_key="evaluation_cases.id")
    model_provider: str = Field(default="mock_fallback", max_length=80)
    repeat_index: int = Field(default=1)
    status: str = Field(default="pending", max_length=40)
    run_id: Optional[int] = Field(default=None, index=True, foreign_key="evaluation_runs.id")
    report_id: Optional[int] = Field(default=None, index=True, foreign_key="evaluation_reports.report_id")
    total_score: float = Field(default=0)
    avg_latency_ms: float = Field(default=0)
    error_message: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
