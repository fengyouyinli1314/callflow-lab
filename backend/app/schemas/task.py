from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel


class TaskBase(SQLModel):
    name: str
    description: str
    target_scenario: str
    system_instruction: str
    evaluation_goal: str
    instruction_text: Optional[str] = ""
    role_text: Optional[str] = ""
    task_text: Optional[str] = ""
    opening_line: Optional[str] = ""
    call_flow: Optional[str] = ""
    conversation_flow: Optional[str] = ""
    knowledge_points: Optional[str] = ""
    constraints: Optional[str] = ""
    steps: Optional[str] = ""
    executable_policy: Optional[str] = ""
    task_type: Optional[str] = "generic_outbound"
    data_source: Optional[str] = "mock_sample"


class TaskCreate(TaskBase):
    """Payload for creating an evaluation task."""


class TaskUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_scenario: Optional[str] = None
    system_instruction: Optional[str] = None
    evaluation_goal: Optional[str] = None
    instruction_text: Optional[str] = None
    role_text: Optional[str] = None
    task_text: Optional[str] = None
    opening_line: Optional[str] = None
    call_flow: Optional[str] = None
    conversation_flow: Optional[str] = None
    knowledge_points: Optional[str] = None
    constraints: Optional[str] = None
    steps: Optional[str] = None
    executable_policy: Optional[str] = None
    task_type: Optional[str] = None
    data_source: Optional[str] = None


class TaskListRead(SQLModel):
    id: int
    name: str
    description: str
    target_scenario: str
    evaluation_goal: str
    task_type: Optional[str] = "generic_outbound"
    data_source: Optional[str] = "mock_sample"
    created_at: datetime
    updated_at: datetime


class TaskRead(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
