from collections.abc import Generator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.models import case, report, run, task  # noqa: F401


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_task_columns()
    _ensure_report_columns()


def _ensure_task_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "evaluation_tasks" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("evaluation_tasks")}
    required_columns = {
        "instruction_text": "TEXT",
        "role_text": "TEXT",
        "task_text": "TEXT",
        "opening_line": "TEXT",
        "call_flow": "TEXT",
        "knowledge_points": "TEXT",
        "constraints": "TEXT",
        "task_type": "VARCHAR(80)",
        "data_source": "VARCHAR(80)",
    }
    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE evaluation_tasks ADD COLUMN {column_name} {column_type}"))


def _ensure_report_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "evaluation_reports" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("evaluation_reports")}
    required_columns = {
        "call_flow_coverage": "FLOAT DEFAULT 0",
        "constraint_compliance": "FLOAT DEFAULT 0",
        "failed_rule_count": "INTEGER DEFAULT 0",
        "metric_explanations": "JSON",
        "evidence_messages": "JSON",
        "score_formula": "JSON",
    }
    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE evaluation_reports ADD COLUMN {column_name} {column_type}"))


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
