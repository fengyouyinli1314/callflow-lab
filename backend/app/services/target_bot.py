from typing import Any, Dict, List

from app.services.llm_client import LLMClient


class TargetBot:
    def __init__(self) -> None:
        self.llm_client = LLMClient()

    def reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
    ) -> str:
        return self.llm_client.generate_assistant_reply(task_payload, case_payload, user_message, history)
