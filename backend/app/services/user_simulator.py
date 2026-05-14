from typing import Any, Dict, List

from app.services.llm_client import LLMClient


class UserSimulator:
    def __init__(self) -> None:
        self.llm_client = LLMClient()

    def generate_next_message(
        self,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_index: int,
    ) -> str:
        return self.llm_client.generate_user_message(case_payload, history, turn_index)
