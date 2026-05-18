from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.services.target_model_client import (
    LEGACY_PROVIDER_ALIASES,
    SUPPORTED_TARGET_PROVIDERS,
    TargetModelClient,
    TargetModelError,
    normalize_target_provider,
)


router = APIRouter(prefix="/api/model-providers", tags=["model-providers"])


class ModelProviderTestRequest(BaseModel):
    provider: str
    base_url: str | None = None
    model_name: str | None = None
    endpoint: str | None = None


PROVIDER_DESCRIPTIONS = {
    "mock_fallback": "本地兜底模型（fallback, non-real AI），仅用于演示环境或 API 不可用时保证流程跑通，非真实 AI 能力。",
    "openai_compatible": "真实大模型 API 接入，兼容 Qwen、DeepSeek、GPT、智谱、Moonshot 等 OpenAI 格式接口。",
    "custom_endpoint": "自定义被测模型接口，用于接入外部服务、企业内部模型或其他团队接口。",
}


@router.get("")
def list_model_providers() -> List[Dict[str, Any]]:
    active_provider = normalize_target_provider(settings.target_model_provider)
    providers = [
        _provider_row(
            name="mock_fallback",
            provider_type="fallback",
            active_provider=active_provider,
            enabled=True,
            model_name="mock_fallback",
        ),
        _provider_row(
            name="openai_compatible",
            provider_type="openai_compatible",
            active_provider=active_provider,
            enabled=bool(settings.target_model_base_url and settings.target_model_api_key),
            base_url=settings.target_model_base_url,
            model_name=settings.target_model_name or "未配置",
            api_key_configured=bool(settings.target_model_api_key),
        ),
        _provider_row(
            name="custom_endpoint",
            provider_type="custom_endpoint",
            active_provider=active_provider,
            enabled=bool(settings.target_model_endpoint),
            endpoint=settings.target_model_endpoint,
            model_name=settings.target_model_name or "未配置",
            api_key_configured=bool(settings.target_model_api_key),
        ),
    ]
    return providers


@router.post("/test")
def test_model_provider(payload: ModelProviderTestRequest) -> Dict[str, Any]:
    raw_provider = (payload.provider or "").strip()
    provider = normalize_target_provider(raw_provider)
    if raw_provider and raw_provider not in SUPPORTED_TARGET_PROVIDERS and raw_provider not in LEGACY_PROVIDER_ALIASES:
        return {
            "provider": provider,
            "success": False,
            "ok": False,
            "message": "未知 provider，评测时会回退到 mock_fallback。",
        }
    legacy_note = "旧 provider 已映射为 mock_fallback。" if raw_provider in LEGACY_PROVIDER_ALIASES else ""
    if provider == "mock_fallback":
        return {
            "provider": provider,
            "success": True,
            "ok": True,
            "message": f"{legacy_note}mock_fallback 可用：本地兜底，仅保证流程跑通，非真实 AI 能力。",
        }
    if provider == "openai_compatible":
        base_url = (payload.base_url or settings.target_model_base_url or "").strip()
        model_name = (payload.model_name or settings.target_model_name or "").strip()
        api_key_configured = bool(settings.target_model_api_key)
        if not (base_url and model_name and api_key_configured):
            return {
                "provider": provider,
                "success": False,
                "ok": False,
                "error_message": "需要在后端 .env 配置 Base URL、Model Name 和 API Key。",
                "message": "需要在后端 .env 配置 Base URL、Model Name 和 API Key。",
            }
        client = TargetModelClient("openai_compatible")
        client.base_url = base_url.rstrip("/")
        client.model_name = model_name
        try:
            result = client.test_openai_compatible_connection()
        except TargetModelError as exc:
            return {
                "provider": provider,
                "success": False,
                "ok": False,
                "error_code": exc.code,
                "error_message": exc.message,
                "message": exc.message,
            }
        return {
            **result,
            "message": "真实大模型 API 调用成功。",
        }
    if provider == "custom_endpoint":
        endpoint = (payload.endpoint or settings.target_model_endpoint or "").strip()
        ok = bool(endpoint)
        return {
            "provider": provider,
            "success": ok,
            "ok": ok,
            "message": "外部被测模型 endpoint 已配置。" if ok else "需要在后端 .env 配置 TARGET_MODEL_ENDPOINT；评测时会回退到 mock_fallback。",
        }
    return {"provider": provider, "success": False, "ok": False, "message": "未知 provider，已回退为 mock_fallback。"}


def _provider_row(
    name: str,
    provider_type: str,
    active_provider: str,
    enabled: bool,
    base_url: str = "",
    model_name: str = "",
    endpoint: str = "",
    api_key_configured: bool = False,
) -> Dict[str, Any]:
    return {
        "name": name,
        "type": provider_type,
        "enabled": enabled,
        "active": active_provider == name,
        "base_url": base_url or "",
        "model_name": model_name or name,
        "endpoint": endpoint or "",
        "api_key_configured": api_key_configured,
        "description": PROVIDER_DESCRIPTIONS[name],
    }
