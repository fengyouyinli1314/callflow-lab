from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from app.core.config import settings
from app.services.dialogue_state import analyze_dialogue_state, is_similar_text


logger = logging.getLogger(__name__)


LEGACY_PROVIDER_ALIASES = {
    "mock_baseline": "mock_fallback",
    "mock_strong": "mock_fallback",
}
SUPPORTED_TARGET_PROVIDERS = {"mock_fallback", "openai_compatible", "custom_endpoint"}


def normalize_target_provider(provider: str | None) -> str:
    value = (provider or "mock_fallback").strip() or "mock_fallback"
    value = LEGACY_PROVIDER_ALIASES.get(value, value)
    return value if value in SUPPORTED_TARGET_PROVIDERS else "mock_fallback"


@dataclass
class TargetModelResult:
    content: str
    provider: str
    model_name: str
    fallback_used: bool = False
    task_type: str = "generic_outbound"
    should_close: bool = False
    dialogue_state: Dict[str, Any] = field(default_factory=dict)
    call_chain: List[str] = field(default_factory=list)


class TargetModelClient:
    """Unified and task-scoped entry point for the evaluated dialogue model."""

    providers = SUPPORTED_TARGET_PROVIDERS

    rider_forbidden_terms = [
        "退款",
        "订单号",
        "手机号后四位",
        "商家出餐",
        "平台超时",
        "配送状态",
        "超时节点",
        "投诉",
        "处理时间",
        "酒店",
        "团购券",
        "核销",
        "标准直播",
        "低延迟直播",
        "负责人",
    ]
    course_forbidden_terms = [
        "骑手",
        "飞毛腿",
        "配送",
        "派单",
        "合同",
        "X 单",
        "X单",
        "Y 单",
        "Y单",
        "退款",
        "订单号",
        "手机号后四位",
        "商家出餐",
        "平台超时",
        "核销",
        "酒店",
    ]

    def __init__(self, provider: str | None = None, model_name: str | None = None) -> None:
        self.provider = normalize_target_provider(provider or settings.target_model_provider)
        normalized_model_name = LEGACY_PROVIDER_ALIASES.get((model_name or "").strip(), (model_name or "").strip())
        self.model_name = (normalized_model_name or settings.target_model_name or self.provider).strip() or self.provider
        self.api_key = settings.target_model_api_key or ""
        self.base_url = (settings.target_model_base_url or "").rstrip("/")
        self.endpoint = settings.target_model_endpoint or ""

    def generate_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
    ) -> TargetModelResult:
        task_type = self.infer_task_type(task_payload, case_payload)
        messages = history + [{"turn_index": len(history) + 1, "user_message": user_message}]
        dialogue_state = analyze_dialogue_state(task_payload, case_payload, messages)
        call_chain = [
            "POST /api/runs/start",
            "EvaluationService.start_evaluation",
            "TargetModelClient.generate_reply",
        ]
        logger.info(
            "callflow trace: %s provider=%s model=%s task_type=%s",
            " -> ".join(call_chain),
            self.provider,
            self.model_name,
            task_type,
        )

        if task_type == "rider_outbound":
            content, fallback_used, should_close = self.generate_rider_reply(
                task_payload,
                case_payload,
                messages,
                self.provider,
                dialogue_state,
            )
            call_chain.append("TargetModelClient.generate_rider_reply")
        elif task_type == "course_platform_outbound":
            content, fallback_used, should_close = self.generate_course_reply(
                task_payload,
                case_payload,
                messages,
                self.provider,
                dialogue_state,
            )
            call_chain.append("TargetModelClient.generate_course_reply")
        else:
            content, fallback_used, should_close = self.generate_generic_outbound_reply(
                task_payload,
                case_payload,
                messages,
                self.provider,
                dialogue_state,
            )
            call_chain.append("TargetModelClient.generate_generic_outbound_reply")

        validated = self.validate_reply_by_task_type(content, task_type)
        if validated != content:
            fallback_used = True
            call_chain.append("TargetModelClient.validate_reply_by_task_type:fallback")
            logger.warning("target reply replaced by task-type validator task_type=%s", task_type)
        else:
            call_chain.append("TargetModelClient.validate_reply_by_task_type:pass")
        deduped = self.deduplicate_assistant_reply(validated, messages, task_type, dialogue_state)
        if deduped != validated:
            fallback_used = True
            call_chain.append("TargetModelClient.deduplicate_assistant_reply:changed")
            validated = self.validate_reply_by_task_type(deduped, task_type)
        else:
            call_chain.append("TargetModelClient.deduplicate_assistant_reply:pass")
        should_close = should_close or self._reply_should_close(validated, task_type, dialogue_state)
        return self._result(validated, fallback_used, task_type, should_close, dialogue_state, call_chain)

    def generate_rider_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: str,
        dialogue_state: Dict[str, Any],
    ) -> Tuple[str, bool, bool]:
        external = self._provider_reply(task_payload, case_payload, messages, provider)
        if external:
            return external, False, False

        stage = dialogue_state["current_stage"]
        said = set(dialogue_state["assistant_said_topics"])
        fallback_used = self._provider_fallback(provider)
        should_close = False

        if stage == "start_delivery":
            reply = "飞毛腿合同已生效，可以开始配送。"
        elif stage == "contract_impact":
            if "已说明合同和派单影响" in said and "已说明 X 单/Y 单" in said:
                reply = "多日每天完成 Y 单，后续按派单规则看。"
            else:
                reply = "单日需完成 X 单，否则合同和派单可能受影响。"
        elif stage == "reject_delivery":
            if "已说明合同和派单影响" in said:
                reply = "若确实跑不了，我先帮你记录。"
            elif "已安抚无法配送" in said:
                reply = "未完成可能影响合同和派单。"
            else:
                reply = "理解，我先说明影响，你再决定。"
        elif stage == "weather":
            if "已提醒安全" in said:
                reply = "雨天单量更多，完成有助保资格。"
            else:
                reply = "安全第一，能跑再接单。"
        elif stage == "exit":
            reply = "需前一天 Z 点前在 App 报名页取消。"
        elif stage == "rank":
            reply = "报名按排名，不是站长干预。"
        elif stage == "accepted":
            reply = "好，注意安全，后续有问题再联系。"
            should_close = True
        else:
            if "已说明合同已生效" not in said:
                reply = "飞毛腿合同已生效，可以开始配送。"
            elif "已说明 X 单/Y 单" not in said:
                reply = "单日需完成 X 单，多日每天完成 Y 单。"
            elif "已提醒安全" not in said:
                reply = "配送时安全第一，能跑再接单。"
            else:
                reply = "后续按合同要求跑，有问题再联系。"
                should_close = True
        return reply, fallback_used, should_close

    def generate_course_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: str,
        dialogue_state: Dict[str, Any],
    ) -> Tuple[str, bool, bool]:
        external = self._provider_reply(task_payload, case_payload, messages, provider)
        if external:
            return external, False, False

        stage = dialogue_state["current_stage"]
        said = set(dialogue_state["assistant_said_topics"])
        fallback_used = self._provider_fallback(provider)
        should_close = False

        if stage == "non_owner":
            if "已请非负责人转达" in said:
                reply = "主要是直播发布页新增低延迟选项。"
            else:
                reply = "麻烦您帮忙转达负责人。"
        elif stage == "owner":
            reply = "我们直播发布页新增两个选项。"
        elif stage == "live_difference":
            if "已说明标准直播/低延迟直播区别" in said:
                reply = "互动课建议低延迟，大班课可用标准直播。"
            else:
                reply = "标准延迟约 5-10 秒，低延迟约 1-2 秒。"
        elif stage == "config_path":
            if "已询问发布方式" not in said:
                reply = "您是用 Web 控制台还是第三方系统？"
            else:
                reply = "Web 可直接选，第三方进直播平台管理。"
        elif stage == "web_path":
            reply = "Web 控制台显示后可直接选择。"
        elif stage == "third_party_path":
            reply = "进入直播平台管理，勾选低延迟直播。"
        elif stage == "fee":
            reply = "低延迟保障更强，费用会略高。"
        elif stage == "coupon":
            reply = "优惠券我不能承诺，费用以页面为准。"
        elif stage == "busy":
            reply = "就 1 分钟，保证简短。"
        elif stage == "driver":
            reply = "那我稍后再打，您注意安全。"
            should_close = True
        elif stage == "accepted":
            reply = "祝课程顺利，后续可再联系。"
            should_close = True
        else:
            if "已确认负责人" not in said:
                reply = "请问您是负责人吗？"
            elif "已说明发布页升级" not in said:
                reply = "我们直播发布页新增两个选项。"
            elif "已询问发布方式" not in said:
                reply = "您是用 Web 控制台还是第三方系统？"
            else:
                reply = "后续按发布页配置即可。"
        return reply, fallback_used, should_close

    def generate_generic_outbound_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: str,
        dialogue_state: Dict[str, Any],
    ) -> Tuple[str, bool, bool]:
        external = self._provider_reply(task_payload, case_payload, messages, provider)
        if external:
            return external, False, False

        opening = task_payload.get("opening_line") or "您好，我按当前外呼任务继续沟通。"
        text = self._trim(str(opening), 60)
        if not text:
            text = "您好，我按当前外呼任务继续沟通。"
        should_close = dialogue_state.get("current_stage") == "accepted"
        return text, self._provider_fallback(provider), should_close

    def validate_reply_by_task_type(self, content: str, task_type: str) -> str:
        if task_type == "rider_outbound" and self._has_any(content, self.rider_forbidden_terms):
            return "单日需完成 X 单，否则合同和派单可能受影响。"
        if task_type == "course_platform_outbound" and self._has_any(content, self.course_forbidden_terms):
            return "麻烦您帮忙转达负责人，直播发布页升级了。"
        return content

    def deduplicate_assistant_reply(
        self,
        reply: str,
        messages: List[Dict[str, Any]],
        task_type: str,
        dialogue_state: Dict[str, Any],
    ) -> str:
        previous_replies = [
            str(item.get("assistant_message", "") or "")
            for item in messages[:-1]
            if item.get("assistant_message")
        ]
        if not any(is_similar_text(reply, previous) for previous in previous_replies):
            return reply

        alternatives = self._alternative_replies(task_type, dialogue_state)
        for alternative in alternatives:
            if alternative != reply and not any(is_similar_text(alternative, previous) for previous in previous_replies):
                return alternative
        return alternatives[-1] if alternatives else reply

    def model_info(self) -> Dict[str, str]:
        return {"model_provider": self.provider, "model_name": self.model_name}

    def infer_task_type(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any] | None = None) -> str:
        task_type = (task_payload.get("task_type") or "").strip()
        if task_type:
            return task_type
        case_payload = case_payload or {}
        text = " ".join(
            str(value or "")
            for value in [
                task_payload.get("instruction_text", ""),
                task_payload.get("name", ""),
                task_payload.get("target_scenario", ""),
                case_payload.get("name", ""),
                case_payload.get("initial_message", ""),
            ]
        )
        if self._has_any(text, ["飞毛腿", "骑手", "配送", "派单"]):
            return "rider_outbound"
        if self._has_any(text, ["课程", "直播", "低延迟", "机构", "负责人"]):
            return "course_platform_outbound"
        return "generic_outbound"

    def _provider_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: str,
    ) -> str:
        if provider == "openai_compatible" and self.api_key and self.base_url:
            return self._call_openai_compatible(task_payload, case_payload, messages)
        if provider == "custom_endpoint" and self.endpoint:
            return self._call_custom_endpoint(task_payload, case_payload, messages)
        return ""

    def _provider_fallback(self, provider: str) -> bool:
        return provider != "mock_fallback"

    def _result(
        self,
        content: str,
        fallback_used: bool,
        task_type: str,
        should_close: bool,
        dialogue_state: Dict[str, Any],
        call_chain: List[str],
    ) -> TargetModelResult:
        return TargetModelResult(
            content=content,
            provider=self.provider,
            model_name=self.model_name,
            fallback_used=fallback_used,
            task_type=task_type,
            should_close=should_close,
            dialogue_state=dialogue_state,
            call_chain=call_chain,
        )

    def _alternative_replies(self, task_type: str, dialogue_state: Dict[str, Any]) -> List[str]:
        stage = dialogue_state.get("current_stage", "")
        if task_type == "rider_outbound":
            by_stage = {
                "weather": [
                    "雨天单量更多，完成有助保资格。",
                    "若确实跑不了，我先帮你记录。",
                    "路况不好先别冒险，安全第一。",
                ],
                "contract_impact": [
                    "合同和派单都可能受影响，尽量完成 X 单。",
                    "单日看 X 单，多日每天看 Y 单。",
                    "如果今天确实完不成，我先记录情况。",
                ],
                "reject_delivery": [
                    "若确实跑不了，我先帮你记录。",
                    "未完成可能影响合同和派单。",
                    "你先看能否配送，安全也要优先。",
                ],
                "start_delivery": [
                    "今天合同已生效，能配送就开始接单。",
                    "先确认能否开始配送，再看完成要求。",
                ],
            }
            return by_stage.get(stage, ["单日需完成 X 单，多日每天完成 Y 单。"])

        if task_type == "course_platform_outbound":
            by_stage = {
                "live_difference": [
                    "互动课建议低延迟，大班课可用标准直播。",
                    "接下来您看是 Web 控制台还是第三方系统？",
                ],
                "config_path": [
                    "您是用 Web 控制台还是第三方系统？",
                    "Web 可直接选，第三方进直播平台管理。",
                ],
                "third_party_path": [
                    "进入直播平台管理，勾选低延迟直播。",
                    "若仍看不到，明天再进后台查看。",
                ],
                "non_owner": [
                    "主要是直播发布页新增低延迟选项。",
                    "请负责人看发布页的直播选项。",
                ],
            }
            return by_stage.get(stage, ["您是用 Web 控制台还是第三方系统？"])
        return ["我换个说法：按当前外呼流程继续确认下一步。"]

    def _reply_should_close(self, reply: str, task_type: str, dialogue_state: Dict[str, Any]) -> bool:
        if dialogue_state.get("should_close"):
            return True
        if task_type == "course_platform_outbound":
            return self._has_any(reply, ["稍后再打", "祝课程顺利", "后续可再联系"])
        if task_type == "rider_outbound":
            return self._has_any(reply, ["后续有问题再联系"])
        return False

    def _call_openai_compatible(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> str:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": self._messages(task_payload, case_payload, messages),
            "temperature": 0.1,
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        return self._post_json(url, payload, headers)

    def _call_custom_endpoint(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> str:
        payload = {
            "task": task_payload,
            "case": case_payload,
            "messages": messages,
            "model": self.model_name,
            "task_type": self.infer_task_type(task_payload, case_payload),
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return self._post_json(self.endpoint, payload, headers)

    def _messages(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        task_type = self.infer_task_type(task_payload, case_payload)
        guardrails = {
            "rider_outbound": {
                "allowed": "飞毛腿合同、生效、开始配送、X 单、Y 单、合同影响、派单、安全、雨天、资格、报名排名、App 取消、同事确认后回电",
                "forbidden": "、".join(self.rider_forbidden_terms),
            },
            "course_platform_outbound": {
                "allowed": "负责人确认、非负责人转达、标准直播、低延迟直播、互动场景、Web 控制台、第三方系统、发布页、费用差异、企业微信、稍后再打",
                "forbidden": "、".join(self.course_forbidden_terms),
            },
        }.get(
            task_type,
            {
                "allowed": "当前任务指令、外呼目的、流程推进、约束说明",
                "forbidden": "串用其他业务场景",
            },
        )
        system = (
            "你是被测对话模型。只能围绕当前任务类型白名单回复，电话话术要简短。"
            f"task_type={task_type}。允许范围：{guardrails['allowed']}。"
            f"禁止出现：{guardrails['forbidden']}。"
        )
        task_context = {
            "instruction_text": task_payload.get("instruction_text", ""),
            "role_text": task_payload.get("role_text", ""),
            "task_text": task_payload.get("task_text", ""),
            "opening_line": task_payload.get("opening_line", ""),
            "call_flow": task_payload.get("call_flow", ""),
            "knowledge_points": task_payload.get("knowledge_points", ""),
            "constraints": task_payload.get("constraints", ""),
            "task_type": task_type,
            "case": case_payload,
        }
        outbound_messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(task_context, ensure_ascii=False)},
        ]
        for item in messages[-7:-1]:
            outbound_messages.append({"role": "user", "content": item.get("user_message", "")})
            outbound_messages.append({"role": "assistant", "content": item.get("assistant_message", "")})
        outbound_messages.append({"role": "user", "content": messages[-1].get("user_message", "")})
        return outbound_messages

    def _post_json(self, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> str:
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return ""

        if isinstance(data, dict):
            choices = data.get("choices")
            if choices and isinstance(choices, list):
                message = choices[0].get("message", {})
                return str(message.get("content", "")).strip()
            for key in ["content", "reply", "text", "message"]:
                if data.get(key):
                    return str(data[key]).strip()
        return ""

    def _conversation_text(self, messages: List[Dict[str, Any]], case_payload: Dict[str, Any]) -> str:
        parts = [
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            " ".join(str(item) for item in case_payload.get("expected_goals", []) or []),
        ]
        parts.extend(item.get("user_message", "") for item in messages)
        return " ".join(parts)

    def _trim(self, text: str, limit: int) -> str:
        return text if len(text) <= limit else text[:limit].rstrip("，。；、") + "。"

    def _has_any(self, text: str, keywords: List[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)
