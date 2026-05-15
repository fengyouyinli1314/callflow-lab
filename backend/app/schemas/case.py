from datetime import datetime
from typing import List, Optional

from sqlmodel import SQLModel


class CaseBase(SQLModel):
    task_id: int
    name: str
    user_profile: str
    initial_message: str
    max_turns: int = 4
    expected_goals: List[str] = []
    required_rules: List[str] = []
    forbidden_rules: List[str] = []
    difficulty: str = "中等"


class CaseCreate(CaseBase):
    """Payload for creating an evaluation case."""


class CaseUpdate(SQLModel):
    task_id: Optional[int] = None
    name: Optional[str] = None
    user_profile: Optional[str] = None
    initial_message: Optional[str] = None
    max_turns: Optional[int] = None
    expected_goals: Optional[List[str]] = None
    required_rules: Optional[List[str]] = None
    forbidden_rules: Optional[List[str]] = None
    difficulty: Optional[str] = None


class CaseRead(CaseBase):
    id: int
    created_at: datetime
