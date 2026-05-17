from __future__ import annotations

from typing import Any, Dict, List

from app.services.target_model_client import TargetModelClient


class TargetBot:
    """Backward-compatible wrapper around the evaluated-model client."""

    def __init__(self) -> None:
        self.client = TargetModelClient()

    def reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
    ) -> str:
        return self.client.generate_reply(task_payload, case_payload, user_message, history).content

    def model_info(self) -> Dict[str, str]:
        return self.client.model_info()
