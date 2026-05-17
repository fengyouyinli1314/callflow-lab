from __future__ import annotations

from typing import Any, Dict, List

import httpx

from app.core.config import settings


class LLMClient:
    """Unified model gateway with a deterministic local fallback."""

    def __init__(self) -> None:
        self.provider = settings.llm_provider.lower().strip()
        self.api_key = settings.llm_api_key.strip()
        self.base_url = settings.llm_base_url.strip().rstrip("/")
        self.model = settings.llm_model.strip() or "mock-conversation-evaluator"

    @property
    def use_mock(self) -> bool:
        return self.provider == "mock" or not self.api_key or not self.base_url

    def chat(self, messages: List[Dict[str, str]], fallback: str) -> str:
        if self.use_mock:
            return fallback

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                    "stream": False,
                },
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return fallback

    def generate_user_message(
        self,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_index: int,
    ) -> str:
        fallback = self._mock_user_message(case_payload, history, turn_index)
        prompt = (
            "你是多轮对话评测中的用户模拟器。请根据用户画像、初始问题、"
            "期望目标和历史对话生成下一轮自然的用户发言。"
        )
        return self.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": str({"case": case_payload, "history": history})},
            ],
            fallback,
        )

    def generate_assistant_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
    ) -> str:
        fallback = self._mock_assistant_reply(task_payload, case_payload, user_message, history)
        prompt = (
            "你是被测客服模型。请遵循系统指令和业务规则，用专业、克制、可执行的方式回复用户。"
        )
        return self.chat(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": str(
                        {
                            "task": task_payload,
                            "case": case_payload,
                            "user_message": user_message,
                            "history": history,
                        }
                    ),
                },
            ],
            fallback,
        )

    def judge_conversation(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        rule_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        fallback = {
            "score": rule_result["score"],
            "task_completion": rule_result["metrics"]["task_completion"],
            "instruction_following": rule_result["metrics"]["instruction_following"],
            "context_consistency": rule_result["metrics"]["context_consistency"],
            "safety_compliance": rule_result["metrics"]["safety_compliance"],
            "response_quality": rule_result["metrics"]["response_quality"],
            "reason": rule_result["explainability"]["overall_reason"],
            "suggestions": rule_result["suggestions"],
        }
        prompt = (
            "你是对话质量评审员。请严格输出 JSON，字段包括 score、task_completion、"
            "instruction_following、context_consistency、safety_compliance、response_quality、"
            "reason、suggestions。"
        )
        content = self.chat(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": str(
                        {
                            "task": task_payload,
                            "case": case_payload,
                            "messages": messages,
                            "rule_result": rule_result,
                        }
                    ),
                },
            ],
            str(fallback),
        )
        if self.use_mock:
            return fallback
        return self._safe_json_like(content, fallback)

    def _mock_user_message(
        self,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_index: int,
    ) -> str:
        profile = case_payload.get("user_profile", "")
        scenario = case_payload.get("name", "") + " " + case_payload.get("initial_message", "")
        if turn_index <= 1:
            return case_payload.get("initial_message", "你好，我需要处理这个问题。")

        if any(keyword in scenario for keyword in ["飞毛腿", "骑手", "配送", "派单"]):
            templates = [
                "你再确认一下，单日和多日分别要完成多少？",
                "如果今天跑不了，会不会影响合同和派单？",
                "那我先看路况，安全第一。",
            ]
            return templates[(turn_index - 2) % len(templates)]

        if any(keyword in scenario for keyword in ["课程", "直播", "低延迟", "负责人"]):
            templates = [
                "你用一句话说清楚直播发布页升级了什么。",
                "如果我不是负责人，你希望我怎么转达？",
                "费用和发布方式有什么差异？",
            ]
            return templates[(turn_index - 2) % len(templates)]

        if "情绪激动" in profile:
            templates = [
                "我现在比较着急，你先说清楚下一步。",
                "我希望你给我一个明确答复。",
                "如果现在不能确认，请告诉我后续怎么联系。",
            ]
        elif "反复追问" in profile:
            templates = [
                "你再确认一下，需要我配合哪些信息？",
                "所以现在到底能不能继续推进？",
                "还有没有其他限制条件需要提前告诉我？",
            ]
        elif "信息缺失" in profile:
            templates = [
                "我现在信息不太全，你告诉我还需要什么。",
                "我找到一点信息了，你看够不够。",
                "这些信息够了吗？还需要补充什么？",
            ]
        elif "需求变更" in profile:
            templates = [
                "我刚刚想法变了，想换一种处理方式。",
                "如果原方案不行，有没有替代方案？",
                "请你把可选方案和风险说清楚。",
            ]
        else:
            templates = [
                "好的，你继续说。",
                "请问接下来我需要怎么配合？",
                "麻烦你把结论和注意事项再说明一下。",
            ]
        return templates[(turn_index - 2) % len(templates)]

    def _mock_assistant_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
    ) -> str:
        scenario = " ".join(
            [
                task_payload.get("task_type", ""),
                task_payload.get("target_scenario", ""),
                task_payload.get("instruction_text", ""),
                case_payload.get("name", ""),
                user_message,
            ]
        )
        if any(keyword in scenario for keyword in ["飞毛腿", "骑手", "配送", "派单"]):
            if any(keyword in scenario for keyword in ["下雨", "雨天", "天气"]):
                return "安全第一，雨天单多，能跑有助保资格。"
            if any(keyword in scenario for keyword in ["没完成", "X 单", "X单", "影响"]):
                return "单日需完成 X 单，否则合同和派单可能受影响。"
            return "飞毛腿合同已生效，现在可以开始配送吗？"

        if any(keyword in scenario for keyword in ["课程", "直播", "低延迟", "负责人"]):
            if any(keyword in scenario for keyword in ["不是负责人", "前台", "转达"]):
                return "麻烦您帮忙转达负责人，直播发布页升级了。"
            return "请问您是负责人吗？直播发布页升级了。"

        return "您好，我按当前外呼任务继续沟通。"

    def _safe_json_like(self, content: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import json

            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
        except Exception:
            return fallback
        return fallback
