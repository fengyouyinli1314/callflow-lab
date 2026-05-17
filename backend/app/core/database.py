from collections.abc import Generator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.models import batch_run, case, report, run, task  # noqa: F401


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_task_columns()
    _ensure_case_columns()
    _ensure_run_columns()
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


def _ensure_case_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "evaluation_cases" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("evaluation_cases")}
    required_columns = {
        "trigger_conditions": "JSON DEFAULT '[]'",
        "expected_final_state": "TEXT DEFAULT ''",
        "data_source": "VARCHAR(80) DEFAULT 'manual'",
    }
    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE evaluation_cases ADD COLUMN {column_name} {column_type}"))
        connection.execute(text("UPDATE evaluation_cases SET trigger_conditions = '[]' WHERE trigger_conditions IS NULL"))
        connection.execute(text("UPDATE evaluation_cases SET expected_final_state = '' WHERE expected_final_state IS NULL"))
        connection.execute(text("UPDATE evaluation_cases SET data_source = 'manual' WHERE data_source IS NULL OR data_source = ''"))


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
        "matched_rules": "JSON",
        "llm_judge_result": "JSON",
        "active_rules": "JSON",
        "pending_rules": "JSON",
        "current_stage": "VARCHAR(80) DEFAULT ''",
        "active_rules_explanation": "TEXT DEFAULT ''",
    }
    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE evaluation_reports ADD COLUMN {column_name} {column_type}"))


def _ensure_run_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "evaluation_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("evaluation_runs")}
    required_columns = {
        "model_provider": "VARCHAR(80) DEFAULT 'mock_fallback'",
        "model_name": "VARCHAR(120) DEFAULT 'mock_fallback'",
    }
    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE evaluation_runs ADD COLUMN {column_name} {column_type}"))


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
