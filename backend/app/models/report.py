from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class EvaluationReport(SQLModel, table=True):
    __tablename__ = "evaluation_reports"

    report_id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True, foreign_key="evaluation_runs.id")
    task_id: int = Field(index=True, foreign_key="evaluation_tasks.id")
    case_id: int = Field(index=True, foreign_key="evaluation_cases.id")
    total_score: float = Field(default=0)
    task_completion: float = Field(default=0)
    instruction_following: float = Field(default=0)
    call_flow_coverage: float = Field(default=0)
    constraint_compliance: float = Field(default=0)
    context_consistency: float = Field(default=0)
    safety_compliance: float = Field(default=0)
    response_quality: float = Field(default=0)
    avg_latency_ms: float = Field(default=0)
    failed_rule_count: int = Field(default=0)
    total_turns: int = Field(default=0)
    matched_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    failed_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    active_rules: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    pending_rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    current_stage: str = Field(default="")
    active_rules_explanation: str = Field(default="")
    llm_judge_result: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    suggestions: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    metric_details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    metric_explanations: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    failure_cases: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    explainability: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    evidence_messages: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    score_formula: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    messages: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
