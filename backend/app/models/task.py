from datetime import datetime
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.types import Text
from sqlmodel import Field, SQLModel


class EvaluationTask(SQLModel, table=True):
    __tablename__ = "evaluation_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=120)
    description: str
    target_scenario: str = Field(index=True, max_length=120)
    system_instruction: str
    evaluation_goal: str
    instruction_text: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    role_text: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    task_text: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    opening_line: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    call_flow: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    knowledge_points: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    constraints: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    steps: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    executable_policy: Optional[str] = Field(default="", sa_column=Column(Text, nullable=True))
    task_type: Optional[str] = Field(default="generic_outbound", index=True, max_length=80)
    data_source: Optional[str] = Field(default="mock_sample", index=True, max_length=80)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def conversation_flow(self) -> str:
        return self.call_flow or ""
