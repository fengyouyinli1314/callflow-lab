from datetime import datetime
from typing import Any, Dict, List

from sqlmodel import SQLModel


class RunStartRequest(SQLModel):
    task_id: int
    case_id: int
    model_provider: str | None = None
    model_name: str | None = None


class RunStartResponse(SQLModel):
    run_id: int
    report_id: int
    total_score: float
    model_provider: str = "mock_fallback"
    model_name: str = "mock_fallback"
    task_type: str = "generic_outbound"
    message: str = "evaluation finished"


class RunRead(SQLModel):
    id: int
    task_id: int
    case_id: int
    status: str
    total_score: float
    model_provider: str = "mock_fallback"
    model_name: str = "mock_fallback"
    created_at: datetime
    finished_at: datetime | None = None


class MessageRead(SQLModel):
    id: int
    run_id: int
    turn_index: int
    user_message: str
    assistant_message: str
    latency_ms: float
    rule_score: float
    matched_rules: List[str]
    missed_rules: List[str]
    violated_rules: List[str]
    detail: Dict[str, Any]
    created_at: datetime
