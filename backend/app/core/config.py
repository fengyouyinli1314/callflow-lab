from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "callflow-lab"
    database_url: str = "sqlite:///./callflow_lab.db"
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    target_model_provider: str = "mock_fallback"
    target_model_api_key: str = ""
    target_model_base_url: str = ""
    target_model_name: str = ""
    target_model_endpoint: str = ""
    target_model_allow_fallback: bool = False
    evaluator_provider: str = "mock"
    evaluator_api_key: str = ""
    evaluator_base_url: str = ""
    evaluator_model: str = ""
    case_generator_provider: str = "mock"
    case_generator_api_key: str = ""
    case_generator_base_url: str = ""
    case_generator_model: str = ""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
