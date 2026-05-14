from __future__ import annotations

import re
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

        order_hint = "订单号是 MT20260514001。"
        if "酒店" in scenario:
            order_hint = "订单号是 HOTEL2026051409，我想改到下周五入住。"
        if "券" in scenario or "团购" in scenario:
            order_hint = "券码是 TG20260514088，门店说扫不了。"

        if "情绪激动" in profile:
            templates = [
                f"我已经等很久了，你们到底能不能马上处理？{order_hint}",
                "我现在很着急，希望你给我一个明确处理时间。",
                "如果今天解决不了，我需要知道下一步找谁处理。",
            ]
        elif "反复追问" in profile:
            templates = [
                f"你再确认一下，需要我提供哪些信息？{order_hint}",
                "所以现在到底能不能继续处理？处理时效是多久？",
                "还有没有其他限制条件需要提前告诉我？",
            ]
        elif "信息缺失" in profile:
            templates = [
                "我不太记得订单号，你能告诉我还可以怎么查吗？",
                f"我找到一点信息了，{order_hint}",
                "这些信息够了吗？还需要补充什么？",
            ]
        elif "需求变更" in profile:
            templates = [
                f"我刚刚想法变了，想换一种处理方式，{order_hint}",
                "如果原方案不行，有没有替代方案？",
                "请你把可选方案和风险说清楚。",
            ]
        else:
            templates = [
                f"好的，{order_hint}",
                "请问接下来多久会有结果？",
                "麻烦你把处理结论和注意事项再说明一下。",
            ]
        return templates[(turn_index - 2) % len(templates)]

    def _mock_assistant_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
    ) -> str:
        scenario = task_payload.get("target_scenario", "") + case_payload.get("name", "")
        order_seen = bool(re.search(r"(订单号|券码|MT\d+|HOTEL\d+|TG\d+)", user_message))

        if "退款" in scenario or "外卖" in scenario:
            if not order_seen and len(history) == 0:
                return (
                    "很抱歉给您带来不好的体验，我先帮您核实订单。请提供订单号或下单手机号后四位，"
                    "我会查看配送超时原因；核实后会提交退款/补偿申请，通常 1-3 个工作日反馈，"
                    "目前不能直接承诺退款一定成功。"
                )
            return (
                "收到，我已记录您的订单信息，会优先核实骑手配送轨迹、商家出餐时间和超时节点。"
                "如果符合平台退款规则，会在 1-3 个工作日内给出处理结果；在此期间我会继续安抚并同步进展，"
                "不会在未核实前直接承诺退款成功。"
            )

        if "酒店" in scenario:
            if not order_seen and len(history) == 0:
                return (
                    "可以帮您核查变更可能性。请先提供订单信息、原入住日期、希望调整的新入住日期和房型，"
                    "我需要确认酒店库存、房型是否支持变更，并提醒您可能产生差价或按酒店规则收取费用。"
                )
            return (
                "已收到订单和新入住日期。我会核对原订单、目标入住日期、房型库存和酒店变更政策；"
                "如可变更，会展示差价和确认时限，您确认后再提交变更。"
            )

        if "券" in scenario or "团购" in scenario:
            if not order_seen and len(history) == 0:
                return (
                    "我先帮您排查团购券无法核销的问题。请提供券码、到店门店名称和提示信息，"
                    "我会核对券状态、门店适用范围、有效期，并给出下一步处理建议。"
                )
            return (
                "我已记录券码，会继续核对券状态是否已使用/冻结、当前门店是否在适用范围内、"
                "有效期是否仍然有效。若门店适用但系统异常，我会建议门店重试并为您提交核销异常工单。"
            )

        return "我会先核实关键信息，再根据规则给出处理方案和预计时效。"

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
