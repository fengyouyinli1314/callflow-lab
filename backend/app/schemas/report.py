from datetime import datetime
from typing import Any, Dict, List

from sqlmodel import SQLModel


class ReportRead(SQLModel):
    report_id: int
    run_id: int
    task_id: int
    case_id: int
    total_score: float
    task_completion: float
    instruction_following: float
    call_flow_coverage: float
    constraint_compliance: float
    context_consistency: float
    safety_compliance: float
    response_quality: float
    avg_latency_ms: float
    failed_rule_count: int
    total_turns: int
    matched_rules: List[str]
    failed_rules: List[str]
    active_rules: Dict[str, Any]
    pending_rules: List[str]
    untriggered_rules: List[str]
    visible_business_rules: Dict[str, Any]
    hidden_guardrail_rules: Dict[str, Any]
    full_flow_expected_steps: Dict[str, Any]
    late_satisfied_rules: List[str]
    rule_lifecycle: Dict[str, Any]
    case_focus: str
    active_rule_names: List[str]
    current_stage: str
    memory_state: Dict[str, Any]
    deduction_reason: str
    active_rules_explanation: str
    rule_trace: Dict[str, Any]
    judge_source: Dict[str, Any]
    llm_judge_result: Dict[str, Any]
    suggestions: List[str]
    metric_details: Dict[str, Any]
    metric_explanations: List[Dict[str, Any]]
    failure_cases: List[Dict[str, Any]]
    explainability: Dict[str, Any]
    evidence_messages: List[Dict[str, Any]]
    score_formula: Dict[str, Any]
    messages: List[Dict[str, Any]]
    created_at: datetime


class ReportSummary(SQLModel):
    report_id: int
    total_score: float
    failed_rules: List[str]
    suggestions: List[str]
    key_findings: List[str]
