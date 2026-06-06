from datetime import datetime
from typing import Any, Dict, List

from sqlmodel import Field, SQLModel


class RunStartRequest(SQLModel):
    task_id: int
    case_id: int
    model_provider: str | None = None
    model_name: str | None = None


class RunStartResponse(SQLModel):
    success: bool = True
    run_id: int | None = None
    report_id: int | None = None
    total_score: float = 0
    provider_requested: str = "mock_fallback"
    provider_used: str = "mock_fallback"
    fallback_used: bool = False
    model_provider: str = "mock_fallback"
    model_name: str = "mock_fallback"
    task_type: str = "generic_outbound"
    message: str = "evaluation finished"
    error_code: str | None = None
    error_message: str | None = None


class QuickCheckRequest(SQLModel):
    task_id: int
    case_id: int
    user_messages: List[str] = Field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    include_opening: bool = False


class QuickCheckTurn(SQLModel):
    turn_index: int
    user_message: str
    assistant_message: str
    latency_ms: float = 0
    rule_score: float = 0
    matched_rules: List[str] = Field(default_factory=list)
    missed_rules: List[str] = Field(default_factory=list)
    violated_rules: List[str] = Field(default_factory=list)
    active_rules: Dict[str, Any] = Field(default_factory=dict)
    pending_rules: List[str] = Field(default_factory=list)
    untriggered_rules: List[str] = Field(default_factory=list)
    current_stage: str = ""
    reason: str = ""
    retrieved_knowledge: List[Dict[str, Any]] = Field(default_factory=list)
    fallback_used: bool = False


class QuickCheckResponse(SQLModel):
    success: bool = True
    task_id: int
    case_id: int
    task_type: str = "generic_outbound"
    provider_used: str = "mock_fallback"
    model_name: str = "mock_fallback"
    fallback_used: bool = False
    total_score: float = 0
    matched_rules: List[str] = Field(default_factory=list)
    failed_rules: List[str] = Field(default_factory=list)
    pending_rules: List[str] = Field(default_factory=list)
    turns: List[QuickCheckTurn] = Field(default_factory=list)
    message: str = "quick check finished"


class RunRead(SQLModel):
    id: int
    task_id: int
    case_id: int
    status: str
    total_score: float
    model_provider: str = "mock_fallback"
    model_name: str = "mock_fallback"
    memory_state: Dict[str, Any] = Field(default_factory=dict)
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
