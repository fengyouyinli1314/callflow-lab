from typing import Any, Dict, List

from app.services.llm_client import LLMClient


class LLMJudge:
    def __init__(self) -> None:
        self.llm_client = LLMClient()

    def evaluate(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.llm_client.judge_conversation(task_payload, case_payload, messages, rule_result)
