import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from main import app


@pytest.fixture(autouse=True)
def force_mock_providers():
    original = {
        "target_model_provider": settings.target_model_provider,
        "target_model_base_url": settings.target_model_base_url,
        "target_model_api_key": settings.target_model_api_key,
        "target_model_name": settings.target_model_name,
        "target_model_endpoint": settings.target_model_endpoint,
        "target_model_allow_fallback": settings.target_model_allow_fallback,
        "evaluator_provider": settings.evaluator_provider,
        "case_generator_provider": settings.case_generator_provider,
    }
    settings.target_model_provider = "mock_fallback"
    settings.target_model_base_url = ""
    settings.target_model_api_key = ""
    settings.target_model_name = ""
    settings.target_model_endpoint = ""
    settings.target_model_allow_fallback = False
    settings.evaluator_provider = "mock"
    settings.case_generator_provider = "mock"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client
