from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, SQLModel


class CaseBase(SQLModel):
    task_id: int
    name: str
    user_profile: str
    initial_message: str
    max_turns: int = 4
    expected_goals: List[str] = Field(default_factory=list)
    expected_steps: List[str] = Field(default_factory=list)
    required_rules: List[str] = Field(default_factory=list)
    forbidden_rules: List[str] = Field(default_factory=list)
    difficulty: str = "中等"
    trigger_conditions: List[str] = Field(default_factory=list)
    expected_final_state: str = ""
    user_behavior_type: str = "正常配合"
    case_mode: str = "branch"
    data_source: str = "manual"


class CaseCreate(CaseBase):
    """Payload for creating an evaluation case."""


class CaseUpdate(SQLModel):
    task_id: Optional[int] = None
    name: Optional[str] = None
    user_profile: Optional[str] = None
    initial_message: Optional[str] = None
    max_turns: Optional[int] = None
    expected_goals: Optional[List[str]] = None
    expected_steps: Optional[List[str]] = None
    required_rules: Optional[List[str]] = None
    forbidden_rules: Optional[List[str]] = None
    difficulty: Optional[str] = None
    trigger_conditions: Optional[List[str]] = None
    expected_final_state: Optional[str] = None
    user_behavior_type: Optional[str] = None
    case_mode: Optional[str] = None
    data_source: Optional[str] = None


class CaseRead(CaseBase):
    id: int
    created_at: datetime


class CaseGenerateRequest(SQLModel):
    task_id: int
    case_count: int = Field(default=6, ge=1, le=20)
    difficulty_distribution: List[str] = Field(default_factory=lambda: ["简单", "中等", "困难"])
    user_behavior_types: List[str] = Field(
        default_factory=lambda: ["正常配合", "拒绝配合", "情绪不满", "反复追问", "信息缺失", "超范围问题"]
    )


class CaseDraft(SQLModel):
    name: str
    user_profile: str
    initial_message: str
    expected_goals: List[str] = Field(default_factory=list)
    expected_steps: List[str] = Field(default_factory=list)
    required_rules: List[str] = Field(default_factory=list)
    forbidden_rules: List[str] = Field(default_factory=list)
    difficulty: str = "中等"
    max_turns: int = Field(default=4, ge=1, le=30)
    trigger_conditions: List[str] = Field(default_factory=list)
    expected_final_state: str = ""
    user_behavior_type: str = "正常配合"
    case_mode: str = "branch"
    data_source: str = "ai_generated"
