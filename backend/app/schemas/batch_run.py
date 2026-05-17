from datetime import datetime
from typing import Any, Dict, List

from sqlmodel import Field, SQLModel


class BatchRunStartRequest(SQLModel):
    task_ids: List[int] = Field(default_factory=list)
    case_ids: List[int] = Field(default_factory=list)
    model_providers: List[str] = Field(default_factory=lambda: ["mock_fallback"])
    repeat_times: int = 1


class BatchRunItemRead(SQLModel):
    id: int
    batch_id: int
    task_id: int
    case_id: int
    model_provider: str
    repeat_index: int
    status: str
    run_id: int | None = None
    report_id: int | None = None
    total_score: float = 0
    avg_latency_ms: float = 0
    error_message: str = ""
    created_at: datetime
    finished_at: datetime | None = None


class BatchRunRead(SQLModel):
    batch_id: int
    status: str
    task_ids: List[int]
    case_ids: List[int]
    model_providers: List[str]
    repeat_times: int
    total_runs: int
    finished_runs: int
    failed_runs: int
    average_score: float
    average_latency_ms: float
    pass_rate: float
    items: List[BatchRunItemRead]
    summary: Dict[str, Any]
    created_at: datetime
    finished_at: datetime | None = None


class BatchRunStartResponse(SQLModel):
    batch_id: int
    status: str
    total_runs: int
    finished_runs: int
    failed_runs: int
    average_score: float
    average_latency_ms: float
    pass_rate: float
    summary: Dict[str, Any]
