from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from openai import OpenAI

from app.core.config import settings
from app.services.conversation_memory import compact_memory_for_prompt
from app.services.dialogue_state import analyze_dialogue_state, is_similar_text
from app.services.knowledge_base import retrieve_knowledge
from app.services.rider_flow import rider_rank_qualification_done


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
    retrieved_knowledge: List[Dict[str, Any]] = field(default_factory=list)


class TargetModelError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


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
        if self.provider == "mock_fallback":
            self.model_name = "mock_fallback"
        elif self.provider == "openai_compatible":
            self.model_name = (settings.target_model_name or "").strip()
        else:
            self.model_name = (normalized_model_name or settings.target_model_name or self.provider).strip() or self.provider
        self.api_key = settings.target_model_api_key or ""
        self.base_url = (settings.target_model_base_url or "").rstrip("/")
        self.endpoint = settings.target_model_endpoint or ""
        self.allow_fallback = bool(settings.target_model_allow_fallback)

    def generate_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> TargetModelResult:
        task_type = self.infer_task_type(task_payload, case_payload)
        messages = history + [{"turn_index": len(history) + 1, "user_message": user_message}]
        dialogue_state = analyze_dialogue_state(task_payload, case_payload, messages)
        retrieved_knowledge = retrieve_knowledge(task_payload, user_message, top_k=6)
        call_chain = [
            "POST /api/runs/start",
            "EvaluationService.start_evaluation",
            "TargetModelClient.generate_reply",
            "KnowledgeBase.retrieve_knowledge",
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
                retrieved_knowledge,
                memory_state,
            )
            call_chain.append("TargetModelClient.generate_rider_reply")
        elif task_type == "course_platform_outbound":
            content, fallback_used, should_close = self.generate_course_reply(
                task_payload,
                case_payload,
                messages,
                self.provider,
                dialogue_state,
                retrieved_knowledge,
                memory_state,
            )
            call_chain.append("TargetModelClient.generate_course_reply")
        else:
            content, fallback_used, should_close = self.generate_generic_outbound_reply(
                task_payload,
                case_payload,
                messages,
                self.provider,
                dialogue_state,
                retrieved_knowledge,
                memory_state,
            )
            call_chain.append("TargetModelClient.generate_generic_outbound_reply")

        violated_task_type = self.reply_violates_task_type(content, task_type)
        validated = self.validate_reply_by_task_type(content, task_type)
        if violated_task_type:
            fallback_used = True
            call_chain.append("TargetModelClient.validate_reply_by_task_type:fallback")
            logger.warning("target reply replaced by task-type validator task_type=%s", task_type)
        else:
            call_chain.append("TargetModelClient.validate_reply_by_task_type:pass")
        deduped = self.deduplicate_assistant_reply(validated, messages, task_type, dialogue_state)
        if deduped != validated:
            call_chain.append("TargetModelClient.deduplicate_assistant_reply:changed")
            validated = self.validate_reply_by_task_type(deduped, task_type)
        else:
            call_chain.append("TargetModelClient.deduplicate_assistant_reply:pass")
        should_close = should_close or self._reply_should_close(validated, task_type, dialogue_state)
        return self._result(validated, fallback_used, task_type, should_close, dialogue_state, call_chain, retrieved_knowledge)

    def generate_opening_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]] | None = None,
        memory_state: Dict[str, Any] | None = None,
    ) -> TargetModelResult:
        task_type = self.infer_task_type(task_payload, case_payload)
        opening_line = self.opening_line_for_task(task_payload, case_payload)
        retrieved_knowledge = retrieve_knowledge(task_payload, opening_line or "开场白")
        call_chain = [
            "POST /api/runs/start",
            "EvaluationService.start_evaluation",
            "TargetModelClient.generate_opening_reply",
            "KnowledgeBase.retrieve_knowledge",
        ]
        content = self._provider_opening_reply(
            task_payload,
            case_payload,
            opening_line,
            retrieved_knowledge,
            memory_state,
        )
        fallback_used = False
        if content:
            call_chain.append("TargetModelClient.provider_opening_reply")
        else:
            content = opening_line
            fallback_used = self._provider_fallback(self.provider)
            call_chain.append("TargetModelClient.local_opening_reply")

        safe_content = self._safe_opening_reply(content, opening_line, task_type)
        if safe_content != content:
            content = safe_content
            fallback_used = True
            call_chain.append("TargetModelClient.sanitize_opening_reply")

        violated_task_type = self.reply_violates_task_type(content, task_type)
        validated = self.validate_reply_by_task_type(content, task_type)
        if violated_task_type:
            fallback_used = True
            call_chain.append("TargetModelClient.validate_reply_by_task_type:fallback")
        else:
            call_chain.append("TargetModelClient.validate_reply_by_task_type:pass")
        dialogue_state = analyze_dialogue_state(
            task_payload,
            case_payload,
            list(history or []) + [{"turn_index": 0, "assistant_message": validated, "user_message": ""}],
        )
        return self._result(validated, fallback_used, task_type, False, dialogue_state, call_chain, retrieved_knowledge)

    def opening_line_for_task(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
        task_type = self.infer_task_type(task_payload, case_payload)
        raw_opening = str(task_payload.get("opening_line") or "").strip()
        if not raw_opening:
            raw_opening = self._extract_opening_line(task_payload.get("instruction_text", ""))
        if task_type == "course_platform_outbound":
            return self._course_opening_line(raw_opening)
        if task_type == "rider_outbound":
            return self._rider_opening_line(raw_opening, case_payload)
        return self._trim(raw_opening, 80) if raw_opening else ""

    def generate_rider_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: str,
        dialogue_state: Dict[str, Any],
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> Tuple[str, bool, bool]:
        external = self._provider_reply(task_payload, case_payload, messages, provider, retrieved_knowledge, memory_state)
        if external:
            repaired, repaired_used = self._repair_rider_external_reply(
                external,
                case_payload,
                messages,
                dialogue_state,
            )
            finalized = self._finalize_rider_reply(repaired, messages, dialogue_state)
            return (
                finalized,
                repaired_used or finalized != repaired,
                self._reply_should_close(finalized, "rider_outbound", dialogue_state),
            )

        stage = dialogue_state["current_stage"]
        said = set(dialogue_state["assistant_said_topics"])
        fallback_used = self._provider_fallback(provider)
        should_close = False

        if stage == "peak_online":
            reply = self._rider_peak_contract_reply()
        elif stage == "start_delivery":
            if "已提醒高峰上线" not in said or "已说明 X 单/Y 单" not in said:
                reply = self._rider_peak_contract_reply()
            else:
                reply = "好的，尽量完成，注意安全。"
        elif stage == "contract_impact":
            last_user = messages[-1].get("user_message", "") if messages else ""
            if self._has_any(last_user, ["连续", "Y 天", "Y天"]):
                reply = "许多骑手申请，跑不了名额可能被占。"
            elif self._has_any(last_user, ["多少单", "单日", "多日", "X 单", "Y 单", "X单", "Y单"]):
                reply = self._rider_contract_requirement_reply()
            elif self._has_any(last_user, ["影响合同", "影响派单", "会影响吗", "会不会影响", "没完成"]):
                reply = self._rider_contract_requirement_reply()
            elif "已说明合同和派单影响" in said and "已说明 X 单/Y 单" in said:
                reply = "后续按要求跑，别影响派单。"
            else:
                reply = self._rider_contract_requirement_reply()
        elif stage == "reject_delivery":
            if "已说明合同和派单影响" in said:
                reply = "确实跑不了我记录，注意安全。"
            elif "已安抚无法配送" in said:
                reply = self._rider_reward_reply()
            else:
                reply = self._rider_unwilling_fallback()
        elif stage == "hesitant_delivery":
            reply = self._rider_unwilling_fallback()
        elif stage == "weather":
            last_user = messages[-1].get("user_message", "") if messages else ""
            if self._has_any(last_user, ["排名", "名额", "资格", "保住", "拒单", "取消", "超时"]):
                reply = "安全第一；名额按系统排名，非站长定，少拒单取消超时保资格。"
            elif self._has_any(last_user, ["注意", "提醒"]):
                reply = "配送路上注意安全，雨天路滑安全第一。"
            elif "已提醒安全" in said:
                reply = "雨天订单更多，能跑有助保资格。"
            else:
                reply = "理解，安全第一；雨天订单更多，有助保资格。"
        elif stage == "exit":
            reply = self._rider_exit_reply()
        elif stage == "rank":
            reply = self._rider_rank_qualification_reply()
        elif stage == "reward":
            reply = self._rider_reward_reply()
        elif stage == "out_of_scope":
            reply = "我同事确认后回电，先答我能答的。"
        elif stage == "accepted":
            if "已提醒安全" not in said:
                reply = "好的，跑单注意安全。"
            elif "已说明排名与保资格规则" not in said:
                reply = self._rider_rank_qualification_reply()
            else:
                reply = "好的，后续有问题再联系。"
                should_close = True
        else:
            if "已说明合同已生效" not in said:
                reply = "飞毛腿合同已生效，可以开始配送吗？"
            elif "已提醒高峰上线" not in said or "已说明 X 单/Y 单" not in said:
                reply = self._rider_peak_contract_reply()
            elif "已询问是否开始配送" not in said:
                reply = "今天可以开始配送吗？"
            elif "已提醒安全" not in said:
                reply = "好的，尽量完成，注意安全。"
            elif "已说明排名与保资格规则" not in said:
                reply = self._rider_rank_qualification_reply()
            else:
                reply = "好的，后续有问题再联系。"
                should_close = True
        finalized = self._finalize_rider_reply(reply, messages, dialogue_state)
        if finalized != reply:
            reply = finalized
        return reply, fallback_used, should_close

    def generate_course_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: str,
        dialogue_state: Dict[str, Any],
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> Tuple[str, bool, bool]:
        stage = dialogue_state["current_stage"]
        said = set(dialogue_state["assistant_said_topics"])
        last_user = messages[-1].get("user_message", "") if messages else ""
        assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in messages)
        last_assistant = next(
            (str(item.get("assistant_message", "") or "") for item in reversed(messages) if item.get("assistant_message")),
            "",
        )
        user_text = "\n".join(str(item.get("user_message", "") or "") for item in messages)
        urgent_reply = self._course_urgent_reply(last_user, memory_state)
        if urgent_reply:
            reply, should_close = urgent_reply
            return reply, self._provider_fallback(provider), should_close
        external = self._provider_reply(task_payload, case_payload, messages, provider, retrieved_knowledge, memory_state)
        if external:
            repaired, should_close, changed = self._repair_course_reply(external, stage, said, last_user, assistant_text)
            return repaired, changed, should_close

        fallback_used = self._provider_fallback(provider)
        should_close = False
        priority_reply = self._course_priority_reply(last_user, last_assistant, memory_state)
        if priority_reply:
            reply, should_close = priority_reply
            return reply, fallback_used, should_close

        if stage == "driver":
            reply = "那我稍后再打。"
            should_close = True
        elif stage == "non_owner":
            if "已请非负责人转达" in said:
                reply = "请转达负责人，直播升级了。"
            else:
                reply = "麻烦帮负责人转达一下。"
        elif stage in {"owner", "upgrade_intro"}:
            if stage == "owner" and "已询问知情" not in said and not self._has_any(assistant_text, ["了解低延迟", "知道低延迟", "是否知道"]):
                reply = "您了解低延迟直播吗？"
            elif stage == "upgrade_intro" or self._has_any(last_user, ["升级", "新增", "改了", "变了"]):
                reply = "发布页新增了独立的低延迟直播选项。"
            elif "已说明发布页升级" not in said:
                reply = "我们直播产品升级了。"
            elif not self._has_any(assistant_text, ["低延迟选项", "低延迟直播选项", "新增低延迟", "独立的低延迟"]):
                reply = "发布页新增了独立的低延迟直播选项。"
            else:
                reply = "发课时选低延迟直播。"
        elif stage == "usage":
            reply = "发课时选低延迟直播。"
        elif stage == "flow_change":
            reply = "其他发课流程不变。"
        elif stage == "awareness_check":
            if self._has_any(last_user, ["不知道", "不知情", "没听过"]):
                reply = "发布页新增了独立的低延迟直播选项。"
            else:
                reply = "发布页新增了独立的低延迟直播选项。"
        elif stage == "live_difference":
            reply = self._course_live_difference_reply(assistant_text)
        elif self._has_any(last_user, ["到了", "下一步", "继续", "收到", "可以", "哪里", "选", "配置"]) and self._has_any(last_assistant, ["选择【直播平台】"]):
            reply = "勾选低延迟并保存。"
        elif self._has_any(last_user, ["到了", "下一步", "继续", "收到", "可以", "哪里", "选", "配置"]) and self._has_any(last_assistant, ["点直播平台管理"]):
            reply = "选择【直播平台】。"
        elif self._has_any(last_user, ["到了", "下一步", "继续", "收到", "可以", "哪里", "选", "配置"]) and self._has_any(last_assistant, ["进【我的】", "进入【我的】"]):
            reply = "点直播平台管理。"
        elif stage == "busy":
            if not self._has_any(assistant_text, ["1分钟", "1 分钟", "保证简短"]):
                reply = "就1分钟，保证简短。"
            elif "已说明发布页升级" in said:
                reply = "发布页新增了独立的低延迟直播选项。"
            else:
                reply = "我们直播产品升级了。"
        elif stage == "config_path":
            if self._has_any(assistant_text, ["标准直播延迟", "标准延迟", "5-10 秒", "5-10秒"]) and not self._has_any(
                assistant_text,
                ["低延迟约1-2 秒", "1-2 秒", "低延迟约", "低延迟1-2秒"],
            ):
                reply = self._course_live_difference_reply(assistant_text)
            elif self._has_any(last_user, ["怎么用", "如何用", "怎么使用"]):
                reply = "发课时选低延迟直播。"
            elif self._has_any(last_user, ["流程", "会变"]):
                reply = "其他发课流程不变。"
            elif "已询问发布方式" not in said:
                reply = "Web还是第三方发布？"
            elif self._has_any(last_user, ["SaaS", "校务", "第三方", "看不到"]):
                reply = "进【我的】。"
            else:
                reply = "发课时选低延迟直播。"
        elif stage == "visibility_check":
            is_web = self._has_any(user_text, ["Web控制台", "Web 控制台"])
            is_visible = self._has_any(last_user, ["已显示", "能看到"])
            if is_web and is_visible:
                reply = "直接使用即可。"
            elif is_web:
                reply = "后台配置，请明天查看。"
            elif is_visible:
                reply = "按需选择即可。"
            else:
                reply = "进【我的】。"
        elif stage == "web_path":
            if self._has_any(assistant_text, ["标准直播延迟", "标准延迟", "5-10 秒", "5-10秒"]) and not self._has_any(
                assistant_text,
                ["低延迟约1-2 秒", "1-2 秒", "低延迟约", "低延迟1-2秒"],
            ):
                reply = self._course_live_difference_reply(assistant_text)
            elif self._has_any(last_user, ["Web", "控制台"]):
                reply = "低延迟已显示吗？"
            else:
                reply = "Web可直接选择。"
        elif stage == "third_party_path":
            if self._has_any(assistant_text, ["标准直播延迟", "标准延迟", "5-10 秒", "5-10秒"]) and not self._has_any(
                assistant_text,
                ["低延迟约1-2 秒", "1-2 秒", "低延迟约", "低延迟1-2秒"],
            ):
                reply = self._course_live_difference_reply(assistant_text)
            elif self._has_any(last_user, ["SaaS", "校务", "第三方"]) and not self._has_any(last_user, ["看不到", "没显示", "未显示"]):
                reply = "低延迟已显示吗？"
            elif self._has_any(last_user, ["看不到", "没有选项", "SaaS", "校务", "第三方"]) and "已说明第三方系统路径" not in said:
                reply = "进【我的】。"
            elif "已说明第三方系统路径" in said and self._has_any(last_user, ["看不到", "没有选项"]):
                reply = "可能未配置，明天再查看。"
            else:
                reply = "进直播平台管理。"
        elif stage == "fee":
            if self._has_any(last_user, ["费用会不会更高", "价格", "贵", "费用高"]) and not self._has_any(
                last_user,
                ["学员端", "附加费", "加速线路", "已设置", "没设置", "未设置", "不会配置", "无法配置"],
            ):
                reply = "低延迟费用略高。"
            elif self._has_any(last_user, ["不会配置", "无法配置"]):
                reply = "进教务/财务设置。"
            elif self._has_any(last_user, ["已设置"]):
                reply = "低延迟也要适用该费用。"
            elif self._has_any(last_user, ["没设置", "未设置"]):
                reply = "那进入下一步。"
            elif self._has_any(last_user, ["学员端", "加速线路", "附加费"]):
                reply = "学员端有附加费吗？"
            else:
                reply = "学员端有附加费吗？"
        elif stage == "coupon":
            reply = "优惠券不能承诺。"
        elif stage == "enterprise_wechat":
            if self._has_any(last_user, ["加不了", "不能加", "不可添加"]):
                reply = "请提供可添加手机号。"
            else:
                reply = "企业微信加您，请验证。"
        elif self._has_any(last_user, ["可以", "继续", "下一步", "收到"]) and self._has_any(
            assistant_text,
            ["企业微信", "通过验证", "请提供可添加手机号"],
        ):
            reply = "祝课程顺利，先这样。"
            should_close = True
        elif stage == "accepted":
            reply = "祝课程顺利，先这样。"
            should_close = True
        else:
            if self._has_any(last_user, ["升级", "变", "页面"]):
                reply = "发布页新增了独立的低延迟直播选项。"
            elif "已确认负责人" not in said:
                reply = "请问您是负责人吗？"
            elif "已询问知情" not in said:
                reply = "您了解低延迟直播吗？"
            elif "已说明发布页升级" not in said:
                reply = "我们直播产品升级了。"
            elif not self._has_any(assistant_text, ["低延迟选项", "低延迟直播选项", "新增低延迟", "独立的低延迟"]):
                reply = "发布页新增了独立的低延迟直播选项。"
            elif "已询问发布方式" not in said:
                reply = "Web还是第三方发布？"
            elif "已询问前端是否可见" not in said:
                reply = "低延迟已显示吗？"
            elif "已询问学员端费用" not in said and self._has_any(assistant_text, ["直接使用", "按需选择", "明天查看", "保存", "勾选低延迟"]):
                reply = "学员端有附加费吗？"
            elif "已询问企业微信号码" not in said and self._has_any(assistant_text, ["适用该费用", "那进入下一步", "教务/财务设置"]):
                reply = "当前号码能加吗？"
            else:
                reply = "后续按发布页配置即可。"
        return reply, fallback_used, should_close

    def _course_urgent_reply(
        self,
        last_user: str,
        memory_state: Dict[str, Any] | None,
    ) -> Tuple[str, bool] | None:
        text = str(last_user or "")
        interaction = (memory_state or {}).get("interaction_memory") or {}
        if self._has_any(text, ["开车", "路上", "不方便说"]):
            return "那我稍后再打。", True
        if self._has_any(text, ["我现在很忙", "没时间", "很忙", "说重点"]):
            if interaction.get("is_busy") and self._has_any(text, ["不用", "别说", "先挂"]):
                return "那我稍后再联系。", True
            return "就1分钟，保证简短。", False
        return None

    def _course_priority_reply(
        self,
        last_user: str,
        last_assistant: str,
        memory_state: Dict[str, Any] | None,
    ) -> Tuple[str, bool] | None:
        text = str(last_user or "")
        interaction = (memory_state or {}).get("interaction_memory") or {}
        if self._has_any(text, ["那继续", "继续说", "你继续"]):
            pending = str(interaction.get("pending_return_step") or "")
            if pending in {"upgrade_intro", "option_intro", "awareness_check"}:
                return "之后会显示两个选项。", False
            if pending == "publish_method_check":
                return "您用哪种方式发课？", False
            if pending == "configuration_guidance":
                return "先进入【我的】。", False
            return None
        if interaction.get("interrupted") or self._has_any(
            text,
            [
                "等等",
                "先说",
                "你先",
                "没太听懂",
                "不理解",
                "为什么后台",
                "后台给我改",
                "之前不知道这事",
                "费用会变吗",
                "会影响",
                "学生端有影响",
                "第三方系统看不到",
                "看不到是哪一步",
                "一步一步",
                "不知道点哪里",
            ],
        ):
            interrupt_reply = self._course_interrupt_reply(text, last_assistant)
            if interrupt_reply:
                return interrupt_reply, False
        return None

    def _course_interrupt_reply(self, text: str, last_assistant: str) -> str:
        if not text:
            return ""
        if self._has_any(text, ["低延迟是啥", "低延迟到底", "低延迟是什么"]):
            return "就是互动更顺。"
        if self._has_any(text, ["升级什么", "升级了什么", "新增了什么"]):
            return "新增低延迟直播选项。"
        if self._has_any(text, ["和我有什么关系", "影响发课", "流程会变", "流程变"]):
            return "发课流程不变。"
        if self._has_any(text, ["后台给我改", "为什么后台"]) or (
            self._has_any(text, ["之前不知道"]) and self._has_any(last_assistant, ["后台", "走低延迟"])
        ):
            return "为保障音画同步。"
        if self._has_any(text, ["哪两个"]):
            return "标准和低延迟直播。"
        if self._has_any(text, ["怎么选"]):
            return "按课程类型选择。"
        if not last_assistant and self._has_any(text, ["区别", "差在哪", "差多少"]):
            return ""
        if last_assistant and self._has_any(text, ["区别", "差在哪", "差多少"]):
            return "标准便宜，低延迟更顺。"
        if self._has_any(text, ["小班课"]):
            return "低延迟更适合。"
        if self._has_any(text, ["大班课"]):
            return "标准直播更合适。"
        if self._has_any(text, ["延迟"]):
            return "低延迟约1到2秒。"
        if self._has_any(text, ["费用", "多收费", "价格", "贵"]):
            return "低延迟费用略高。"
        if self._has_any(text, ["优惠", "优惠券", "折扣"]):
            return "优惠券不能承诺。"
        if self._has_any(text, ["学生端", "学员端", "附加费"]):
            return "可能有附加费。"
        if self._has_any(text, ["Web和第三方", "发布方式", "不知道我们用哪个"]):
            return "先确认发布入口。"
        if self._has_any(text, ["第三方系统看不到", "看不到是哪一步", "一步一步", "不知道点哪里"]):
            if self._has_any(last_assistant, ["选择【直播平台】"]):
                return "勾选低延迟并保存。"
            if self._has_any(last_assistant, ["点直播平台管理"]):
                return "选择【直播平台】。"
            if self._has_any(last_assistant, ["进【我的】", "进入【我的】"]):
                return "点直播平台管理。"
            return "先进入【我的】。"
        if self._has_any(text, ["企业微信", "手机号加不了", "不想加企微"]):
            return "请给可添加手机号。"
        if self._has_any(text, ["没太听懂", "说重点"]):
            return "发布页新增低延迟。"
        return ""

    def _course_live_difference_reply(self, assistant_text: str) -> str:
        if not self._has_any(assistant_text, ["5-10 秒", "5-10秒", "5到10秒", "标准延迟"]):
            return "标准直播费用低，延迟5-10秒。"
        if not self._has_any(assistant_text, ["大班课"]):
            return "适合大班课。"
        if not self._has_any(assistant_text, ["1-2 秒", "1-2秒", "1到2秒", "低延迟约", "低延迟1-2秒"]):
            return "低延迟1-2秒，互动更流畅。"
        if not self._has_any(assistant_text, ["小班", "实操"]):
            return "适合小班和实操课。"
        return "发课时按需选择。"

    def _repair_course_reply(
        self,
        reply: str,
        stage: str,
        said: set[str],
        last_user: str,
        assistant_text: str,
    ) -> Tuple[str, bool, bool]:
        text = self._normalize_reply_text(reply, "course_platform_outbound").strip()
        should_close = False
        hard_invalid = False
        if self._has_any(text, ["好的", "哈哈", "嘿嘿", "嘻嘻", "嗯嗯"]):
            hard_invalid = True
        if self._has_any(text, ["稍后再打", "晚点再打"]) and stage != "driver":
            hard_invalid = True
        if self._has_any(text, ["给您优惠券", "送您优惠券", "承诺优惠", "给折扣", "可以打折"]):
            hard_invalid = True
        jumps_to_publish_method = self._has_any(text, ["Web", "校务", "SaaS", "第三方", "配置", "直播平台管理"])
        has_upgrade_context = "已说明发布页升级" in said or self._has_any(
            assistant_text,
            ["发布页", "新增", "两个选项", "标准直播", "低延迟直播"],
        )
        user_asked_config = self._has_any(last_user, ["哪里", "配置", "怎么选", "在哪里选", "选项", "第三方", "SaaS", "Web", "校务"])
        if jumps_to_publish_method and not has_upgrade_context and not user_asked_config:
            hard_invalid = True
        if stage == "driver":
            if "稍后再打" in text and not self._has_any(text, ["直播", "费用", "配置", "升级"]):
                return "那我稍后再打。", True, text != "那我稍后再打。"
            return "那我稍后再打。", True, True
        if not hard_invalid:
            return text, False, False
        repaired, repaired_close = self._course_stage_fallback(stage, said, last_user, assistant_text)
        return repaired, repaired_close, True

    def _course_stage_fallback(
        self,
        stage: str,
        said: set[str],
        last_user: str,
        assistant_text: str,
    ) -> Tuple[str, bool]:
        if stage in {"owner", "upgrade_intro"}:
            if stage == "owner" and "已询问知情" not in said and not self._has_any(assistant_text, ["了解低延迟", "知道低延迟", "是否知道"]):
                return "您了解低延迟直播吗？", False
            if stage == "upgrade_intro" or self._has_any(last_user, ["升级", "新增", "改了", "变了"]):
                return "发布页新增了独立的低延迟直播选项。", False
            if "已说明发布页升级" not in said:
                return "我们直播产品升级了。", False
            if not self._has_any(assistant_text, ["低延迟选项", "低延迟直播选项", "新增低延迟", "独立的低延迟"]):
                return "发布页新增了独立的低延迟直播选项。", False
            return "发课时选低延迟直播。", False
        if stage == "usage":
            return "发课时选低延迟直播。", False
        if stage == "flow_change":
            return "其他发课流程不变。", False
        if stage == "awareness_check":
            if self._has_any(last_user, ["不知道", "不知情", "没听过"]):
                return "发布页新增了独立的低延迟直播选项。", False
            return "发布页新增了独立的低延迟直播选项。", False
        if stage == "busy":
            if not self._has_any(assistant_text, ["1分钟", "1 分钟", "保证简短"]):
                return "就1分钟，我说重点。", False
            return "发布页新增了独立的低延迟直播选项。", False
        if stage == "non_owner":
            return "麻烦帮负责人转达一下。", False
        if stage == "live_difference":
            return self._course_live_difference_reply(assistant_text), False
        if stage in {"web_path", "third_party_path"} and self._has_any(last_user, ["Web", "控制台", "SaaS", "校务", "第三方"]):
            return "低延迟已显示吗？", False
        if stage in {"config_path", "third_party_path"}:
            if "已询问发布方式" not in said:
                return "Web还是第三方发布？", False
            if self._has_any(assistant_text, ["选择【直播平台】"]):
                return "勾选低延迟并保存。", False
            if self._has_any(assistant_text, ["点直播平台管理"]):
                return "选择【直播平台】。", False
            if self._has_any(assistant_text, ["进【我的】", "进入【我的】"]):
                return "点直播平台管理。", False
            return "进【我的】。", False
        if stage == "web_path":
            return "Web可直接选择。", False
        if stage == "visibility_check":
            if self._has_any(last_user, ["已显示", "能看到"]):
                return "按需选择即可。", False
            return "进【我的】。", False
        if stage == "fee":
            if self._has_any(last_user, ["费用会不会更高", "价格", "贵", "费用高"]):
                return "低延迟费用略高。", False
            return "学员端有附加费吗？", False
        if stage == "coupon":
            return "优惠券不能承诺。", False
        if stage == "enterprise_wechat":
            return "企业微信加您，请验证。", False
        if stage == "accepted":
            return "祝课程顺利，先这样。", True
        if self._has_any(last_user, ["升级", "变", "页面"]):
            return "发布页新增了独立的低延迟直播选项。", False
        if "已说明发布页升级" not in said:
            return "我们直播产品升级了。", False
        if not self._has_any(assistant_text, ["低延迟选项", "低延迟直播选项", "新增低延迟", "独立的低延迟"]):
            return "发布页新增了独立的低延迟直播选项。", False
        return "Web还是第三方发布？", False

    def generate_generic_outbound_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        provider: str,
        dialogue_state: Dict[str, Any],
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> Tuple[str, bool, bool]:
        external = self._provider_reply(task_payload, case_payload, messages, provider, retrieved_knowledge, memory_state)
        if external:
            return external, False, False

        opening = task_payload.get("opening_line") or "您好，我按当前外呼任务继续沟通。"
        text = self._trim(str(opening), 60)
        if not text:
            text = "您好，我按当前外呼任务继续沟通。"
        should_close = dialogue_state.get("current_stage") == "accepted"
        return text, self._provider_fallback(provider), should_close

    def validate_reply_by_task_type(self, content: str, task_type: str) -> str:
        normalized = self._normalize_reply_text(content, task_type)
        if self.reply_violates_task_type(normalized, task_type):
            if task_type == "rider_outbound":
                return self._rider_contract_requirement_reply()
            if task_type == "course_platform_outbound":
                return "麻烦转达负责人，直播升级了。"
        return normalized

    def reply_violates_task_type(self, content: str, task_type: str) -> bool:
        normalized = self._normalize_reply_text(content, task_type)
        if task_type == "rider_outbound" and self._has_any(normalized, self.rider_forbidden_terms):
            return True
        if task_type == "course_platform_outbound" and self._has_any(normalized, self.course_forbidden_terms):
            return True
        return False

    def _normalize_reply_text(self, content: str, task_type: str) -> str:
        normalized = (
            str(content or "")
            .replace("**", "")
            .replace("${rider_name}", "你本人")
            .replace("{rider_name}", "你本人")
        )
        if task_type != "course_platform_outbound":
            return normalized
        return (
            normalized.replace("5 - 10 秒", "5-10秒")
            .replace("5-10 秒", "5-10秒")
            .replace("1 - 2 秒", "1-2秒")
            .replace("1-2 秒", "1-2秒")
        )

    def deduplicate_assistant_reply(
        self,
        reply: str,
        messages: List[Dict[str, Any]],
        task_type: str,
        dialogue_state: Dict[str, Any],
    ) -> str:
        previous_replies = [
            str(item.get("assistant_message", "") or "")
            for item in messages
            if item.get("assistant_message")
        ]
        if not any(is_similar_text(reply, previous) for previous in previous_replies):
            return reply

        alternatives = self._alternative_replies(task_type, dialogue_state)
        for alternative in alternatives:
            if alternative != reply and not any(is_similar_text(alternative, previous) for previous in previous_replies):
                return alternative
        return alternatives[-1] if alternatives else reply

    def _finalize_rider_reply(
        self,
        reply: str,
        messages: List[Dict[str, Any]],
        dialogue_state: Dict[str, Any],
    ) -> str:
        text = str(reply or "").strip()
        stage = str(dialogue_state.get("current_stage") or "")
        said = set(dialogue_state.get("assistant_said_topics") or [])
        last_user = str(dialogue_state.get("last_user_message") or "")
        previous_replies = [
            str(item.get("assistant_message", "") or "")
            for item in messages
            if item.get("assistant_message")
        ]
        if not text:
            text = self._rider_next_flow_reply(said, last_user) or self._rider_contract_requirement_reply()

        repeats_previous = any(is_similar_text(text, previous) for previous in previous_replies)
        contract_already_said = "已说明 X 单/Y 单" in said or "已说明合同和派单影响" in said
        repeats_contract = self._rider_mentions_contract_requirement(text) and contract_already_said
        user_asks_contract = self._rider_user_asks_contract(last_user)
        if (repeats_previous or repeats_contract) and stage not in {"exit", "reward", "rank"}:
            if not user_asks_contract or self._has_any(last_user, ["说过", "重复", "刚才"]):
                next_reply = self._rider_next_flow_reply(said, last_user)
                if next_reply and not any(is_similar_text(next_reply, previous) for previous in previous_replies):
                    text = next_reply

        if len(text) <= 30:
            return text
        concise = self._rider_concise_reply(text, stage, said, last_user)
        return concise if len(concise) <= 30 else self._trim(concise, 30)

    def _rider_next_flow_reply(self, said: set[str], last_user: str = "") -> str:
        if "已说明合同已生效" not in said:
            return "飞毛腿合同已生效，可以开始配送吗？"
        if "已提醒高峰上线" not in said or "已说明 X 单/Y 单" not in said or "已说明合同和派单影响" not in said:
            return self._rider_peak_contract_reply()
        if "已询问是否开始配送" not in said:
            return "今天可以开始配送吗？"
        if "已提醒安全" not in said:
            return "好的，尽量完成，注意安全。"
        if "已说明排名与保资格规则" not in said:
            return self._rider_rank_qualification_reply()
        return "好的，后续有问题再联系。"

    def _rider_concise_reply(self, text: str, stage: str, said: set[str], last_user: str) -> str:
        if stage == "exit" or self._has_any(last_user, ["退出", "怎么退", "怎么取消", "不参加", "不想参加", "飞毛腿报名"]):
            return self._rider_exit_reply()
        if stage == "reward" or self._has_any(last_user, ["奖励", "补贴", "激励", "加钱", "W 天", "W天"]):
            return self._rider_reward_reply()
        if stage == "rank" or self._has_any(last_user, ["排名", "名额", "资格", "站长"]):
            return self._rider_rank_qualification_reply()
        if stage == "weather" or self._has_any(last_user, ["下雨", "雨天", "天气", "安全"]):
            if self._has_any(last_user, ["排名", "名额", "资格", "拒单", "取消", "超时"]):
                return "安全第一；名额按系统排名，非站长定，少拒单取消超时保资格。"
            return "理解，安全第一；雨天订单更多，有助保资格。"
        if stage in {"reject_delivery", "hesitant_delivery"}:
            return self._rider_unwilling_fallback()
        if self._rider_mentions_contract_requirement(text):
            return self._rider_contract_requirement_reply()
        if self._has_any(text, ["同事确认", "再回电"]):
            return "我同事确认后回电，先答我能答的。"
        return self._rider_next_flow_reply(said, last_user) or self._trim(text, 30)

    def _rider_mentions_contract_requirement(self, text: str) -> bool:
        return self._has_any(text, ["X 单", "X单", "Y 单", "Y单"]) and self._has_any(text, ["单日", "多日", "合同", "完成"])

    def _rider_user_asks_contract(self, text: str) -> bool:
        return self._has_any(text, ["多少单", "单日", "多日", "X 单", "Y 单", "X单", "Y单", "没完成", "影响", "会怎样", "会怎么样"])

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
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> str:
        if provider == "openai_compatible":
            try:
                return self._call_openai_compatible(task_payload, case_payload, messages, retrieved_knowledge, memory_state)
            except TargetModelError:
                if not self.allow_fallback:
                    raise
                logger.exception("openai_compatible target model failed; falling back to mock because fallback is allowed")
                return ""
        if provider == "custom_endpoint" and self.endpoint:
            return self._call_custom_endpoint(task_payload, case_payload, messages, retrieved_knowledge, memory_state)
        return ""

    def _provider_opening_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        opening_line: str,
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> str:
        if self.provider == "openai_compatible":
            try:
                return self._call_openai_chat(
                    messages=self._opening_messages(
                        task_payload,
                        case_payload,
                        opening_line,
                        retrieved_knowledge,
                        memory_state,
                    ),
                    temperature=0.1,
                )
            except TargetModelError:
                if not self.allow_fallback:
                    raise
                logger.exception("openai_compatible opening call failed; falling back because fallback is allowed")
                return ""
        if self.provider == "custom_endpoint" and self.endpoint:
            payload = {
                "task": task_payload,
                "case": case_payload,
                "messages": [],
                "model": self.model_name,
                "task_type": self.infer_task_type(task_payload, case_payload),
                "opening_stage": True,
                "opening_line": opening_line,
                "retrieved_knowledge": retrieved_knowledge,
                "memory_state": compact_memory_for_prompt(memory_state),
                "knowledge_instruction": "以下是本轮可用知识片段，请优先依据这些内容回答。",
                "instruction": "请只生成本次外呼的第一句开场白，必须完成身份确认，不要进入后续业务说明。",
            }
            if self.infer_task_type(task_payload, case_payload) == "rider_outbound":
                payload["rider_name"] = self._rider_name_for_case(case_payload)
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            return self._post_json(self.endpoint, payload, headers)
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
        retrieved_knowledge: List[Dict[str, Any]],
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
            retrieved_knowledge=retrieved_knowledge,
        )

    def _alternative_replies(self, task_type: str, dialogue_state: Dict[str, Any]) -> List[str]:
        stage = dialogue_state.get("current_stage", "")
        if task_type == "rider_outbound":
            said = set(dialogue_state.get("assistant_said_topics") or [])
            next_reply = self._rider_next_flow_reply(said, str(dialogue_state.get("last_user_message") or ""))
            by_stage = {
                "peak_online": [
                    self._rider_peak_contract_reply(),
                ],
                "weather": [
                    "雨天单量更多，完成有助保资格。",
                    "若确实跑不了，我先帮你记录。",
                    "路况不好先别冒险，安全第一。",
                ],
                "contract_impact": [
                    self._rider_contract_requirement_reply(),
                    "许多骑手申请，跑不了名额可能被占。",
                    "确实完不成，我先记录情况。",
                ],
                "reward": [
                    self._rider_reward_reply(),
                ],
                "hesitant_delivery": [
                    self._rider_unwilling_fallback(),
                    self._rider_reward_reply(),
                ],
                "out_of_scope": [
                    "我同事确认后回电，先答我能答的。",
                ],
                "reject_delivery": [
                    self._rider_unwilling_fallback(),
                    self._rider_reward_reply(),
                    "若确实跑不了，我先记录。",
                ],
                "start_delivery": [
                    "好的，尽量完成，注意安全。",
                    "少拒单取消超时，有助保资格。",
                ],
                "rank": [
                    self._rider_rank_qualification_reply(),
                ],
                "accepted": [
                    "辛苦了，今天跑单注意安全。",
                    "好的，后续有问题再联系。",
                ],
            }
            return by_stage.get(stage, [next_reply or self._rider_contract_requirement_reply()])

        if task_type == "course_platform_outbound":
            by_stage = {
                "owner": [
                    "您了解低延迟直播吗？",
                    "发布页新增了独立的低延迟直播选项。",
                    "发课时选低延迟直播。",
                ],
                "upgrade_intro": [
                    "发布页新增了独立的低延迟直播选项。",
                    "发课时选低延迟直播。",
                ],
                "usage": [
                    "发课时选低延迟直播。",
                ],
                "flow_change": [
                    "其他发课流程不变。",
                ],
                "awareness_check": [
                    "发布页新增了独立的低延迟直播选项。",
                    "发课时选低延迟直播。",
                ],
                "live_difference": [
                    "标准直播费用低，延迟5-10秒。",
                    "适合大班课。",
                    "低延迟1-2秒，互动更流畅。",
                    "适合小班和实操课。",
                ],
                "config_path": [
                    "Web还是第三方发布？",
                    "发课时选低延迟直播。",
                    "低延迟已显示吗？",
                    "进【我的】。",
                    "点直播平台管理。",
                ],
                "visibility_check": [
                    "低延迟已显示吗？",
                    "进【我的】。",
                    "按需选择即可。",
                ],
                "web_path": [
                    "低延迟已显示吗？",
                    "Web可直接选择。",
                ],
                "third_party_path": [
                    "进【我的】。",
                    "点直播平台管理。",
                    "勾选低延迟并保存。",
                ],
                "fee": [
                    "低延迟费用略高。",
                    "学员端有附加费吗？",
                    "那进入下一步。",
                ],
                "coupon": [
                    "优惠券不能承诺。",
                ],
                "non_owner": [
                    "麻烦帮负责人转达一下。",
                    "请转达负责人，直播升级了。",
                ],
                "busy": [
                    "就1分钟，我说重点。",
                    "发布页新增了独立的低延迟直播选项。",
                ],
                "driver": [
                    "那我稍后再打。",
                ],
                "enterprise_wechat": [
                    "企业微信加您，请验证。",
                    "当前号码能加吗？",
                ],
                "accepted": [
                    "祝课程顺利，先这样。",
                ],
            }
            return by_stage.get(
                stage,
                [
                    "Web还是第三方发布？",
                    "低延迟已显示吗？",
                    "进【我的】。",
                    "学员端有附加费吗？",
                    "当前号码能加吗？",
                    "祝课程顺利，先这样。",
                ],
            )
        return ["我换个说法：按当前外呼流程继续确认下一步。"]

    def _reply_should_close(self, reply: str, task_type: str, dialogue_state: Dict[str, Any]) -> bool:
        if dialogue_state.get("should_close"):
            if task_type == "rider_outbound":
                said = set(dialogue_state.get("assistant_said_topics") or [])
                if "已说明排名与保资格规则" not in said and not self._has_any(reply, ["后续有问题再联系"]):
                    return False
            return True
        if task_type == "course_platform_outbound":
            return self._has_any(reply, ["稍后再打", "祝课程顺利", "后续可再联系"])
        if task_type == "rider_outbound":
            said = set(dialogue_state.get("assistant_said_topics") or [])
            if self._has_any(reply, ["后续有问题再联系"]):
                return True
            return "已说明排名与保资格规则" in said and self._has_any(reply, ["跑单注意安全", "注意安全"])
        return False

    def _call_openai_compatible(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> str:
        return self._call_openai_chat(
            messages=self._messages(task_payload, case_payload, messages, retrieved_knowledge, memory_state),
            temperature=0.1,
        )

    def test_openai_compatible_connection(self) -> Dict[str, Any]:
        content = self._call_openai_chat(
            messages=[{"role": "user", "content": "请只回复 OK"}],
            temperature=0,
        )
        return {
            "success": True,
            "ok": True,
            "provider": "openai_compatible",
            "model_name": self.model_name,
            "reply_length": len(content),
            "message": "openai_compatible provider_call_success=true",
        }

    def _call_openai_chat(self, messages: List[Dict[str, str]], temperature: float) -> str:
        if not self.api_key:
            raise TargetModelError("missing_target_model_api_key", "TARGET_MODEL_API_KEY is not configured")
        if not self.base_url:
            raise TargetModelError("missing_target_model_base_url", "TARGET_MODEL_BASE_URL is not configured")
        if not self.model_name:
            raise TargetModelError("missing_target_model_name", "TARGET_MODEL_NAME is not configured")

        request_messages = self._openai_compatible_messages(messages)
        logger.info(
            "target_model_openai_call provider=openai_compatible api_key_configured=%s base_url=%s model_name=%s timeout=60",
            "true" if self.api_key else "false",
            "已配置",
            self.model_name,
        )
        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=60.0,
            )
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=request_messages,
                    temperature=temperature,
                    stream=True,
                )
                content = self._collect_openai_stream_response(response)
                logger.info(
                    "target_model_openai_call provider=openai_compatible provider_call_success=true stream=true reply_length=%s",
                    len(content),
                )
                return content
            except Exception as stream_exc:
                logger.warning(
                    "target_model_openai_call stream=true failed; retrying without stream error=%s",
                    stream_exc,
                )
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=request_messages,
                    temperature=temperature,
                )
        except Exception as exc:
            logger.exception("target_model_openai_call provider=openai_compatible provider_call_success=false")
            raise TargetModelError("openai_compatible_call_failed", str(exc)) from exc

        content = ""
        try:
            content = response.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise TargetModelError("empty_model_response", "empty_model_response") from exc
        content = str(content).strip()
        if not content:
            raise TargetModelError("empty_model_response", "empty_model_response")
        logger.info(
            "target_model_openai_call provider=openai_compatible provider_call_success=true reply_length=%s",
            len(content),
        )
        return content

    def _openai_compatible_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        parts: List[str] = []
        for message in messages or []:
            role = str(message.get("role") or "user").strip().lower()
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                label = "系统指令"
            elif role == "assistant":
                label = "被测模型历史回复"
            elif role == "user":
                label = "用户或任务上下文"
            else:
                label = "补充约束"
            parts.append(f"{label}：\n{content}")

        content = "\n\n".join(parts).strip()
        if not content:
            content = "请按当前任务指令生成一句简短回复。"
        prompt = (
            "请严格根据以下任务信息和历史对话，"
            "只输出被测模型本轮应该说的话术。不要输出 JSON，不要解释推理。\n\n"
            f"{content}"
        )
        return [{"role": "user", "content": prompt}]

    def _safe_opening_reply(self, content: str, opening_line: str, task_type: str) -> str:
        text = str(content or "").strip()
        fallback = str(opening_line or "").strip()
        if not text:
            return fallback
        if task_type == "rider_outbound":
            if "${" in text or len(text) > 45 or self._has_any(
                text,
                ["X 单", "Y 单", "合同", "报名", "上线", "午餐", "晚餐", "高峰", "完成", "配送", "飞毛腿"],
            ):
                return fallback
            if "站长" not in text or not self._has_any(text, ["本人", "是你", "是您", "吗"]):
                return fallback
            return self._trim(text, 45)
        if task_type == "course_platform_outbound":
            if len(text) > 45 or self._has_any(
                text,
                ["直播", "发布页", "低延迟", "标准", "费用", "配置", "企业微信", "升级"],
            ):
                return fallback
            if "负责人" not in text:
                return fallback
            return self._trim(text, 45)
        return self._trim(text, 80)

    def _repair_rider_external_reply(
        self,
        reply: str,
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        dialogue_state: Dict[str, Any],
    ) -> Tuple[str, bool]:
        text = self._replace_rider_placeholders(str(reply or "").replace("**", ""), case_payload).strip()
        stage = str(dialogue_state.get("current_stage") or "")
        said = set(dialogue_state.get("assistant_said_topics") or [])
        last_user = str(messages[-1].get("user_message", "") or "") if messages else ""
        repaired = text
        exit_requested = stage == "exit" or self._has_any(last_user, ["退出", "怎么退", "怎么取消", "取消飞毛腿", "取消报名", "飞毛腿报名", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"])
        weather_requested = stage == "weather" or self._has_any(last_user, ["下雨", "雨天", "天气", "恶劣", "危险", "安全"])
        reject_requested = stage in {"reject_delivery", "hesitant_delivery"} or self._has_any(
            last_user,
            ["不想干", "不干", "不想跑", "不想配送", "不跑", "跑不了", "无法配送", "不一定", "有点忙"],
        )
        rank_requested = stage == "rank" or self._has_any(
            last_user,
            ["排名", "排不上", "报不上", "别人能报", "站长能调", "站长定", "站长干预", "名额", "保资格", "资格"],
        ) or (
            self._has_any(last_user, ["拒单", "取消", "超时", "恶劣天气", "下雨", "雨天"])
            and self._has_any(last_user, ["影响", "资格", "名额", "保住"])
        )
        reward_requested = stage == "reward" or self._has_any(last_user, ["奖励", "补贴", "激励", "加钱", "W 天", "W天"])

        asks_user_to_verify_contract = self._has_any(
            text,
            ["合同是否已经生效", "合同是否已生效", "确认一下你的合同", "确认下你的合同", "合同生效了吗"],
        )
        if asks_user_to_verify_contract:
            repaired = "飞毛腿合同已生效，可以开始配送吗？"
        elif self._rider_contract_requirement_invalid(text):
            repaired = self._rider_peak_contract_reply() if stage in {"opening", "peak_online", "start_delivery"} or self._has_any(text, ["高峰", "午餐", "晚餐"]) else self._rider_contract_requirement_reply()
        elif stage == "opening" and "已说明合同已生效" not in said and not self._has_any(text, ["合同已生效", "合同今天已生效", "合同已签署", "签署并生效"]):
            repaired = "飞毛腿合同已生效，可以开始配送吗？"
        elif stage == "opening" and "已说明合同已生效" in said and not (
            self._has_any(text, ["午晚高峰", "高峰", "上线"])
            and self._has_any(text, ["X 单", "X单"])
            and self._has_any(text, ["Y 单", "Y单"])
            and self._has_any(text, ["能跑吗", "开始配送", "方便配送"])
        ):
            repaired = self._rider_next_flow_reply(said, last_user)
        elif stage == "peak_online" and not self._has_any(text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]):
            repaired = self._rider_peak_contract_reply()
        elif stage == "start_delivery" and "已说明 X 单/Y 单" in said and not self._has_any(text, ["拒单", "取消", "超时", "安全"]):
            repaired = "好的，尽量完成，注意安全。"
        elif reward_requested:
            repaired = self._rider_reward_reply()
        elif weather_requested and rank_requested:
            repaired = "安全第一；名额按系统排名，非站长定，少拒单取消超时保资格。"
        elif reject_requested:
            repaired = self._rider_unwilling_fallback()
        elif exit_requested:
            repaired = self._rider_exit_reply()
        elif rank_requested:
            repaired = self._rider_rank_qualification_reply()
        elif self._has_any(last_user, ["多少单", "单日", "多日", "X 单", "Y 单", "X单", "Y单"]):
            repaired = self._rider_contract_requirement_reply()
        elif weather_requested:
            repaired = "理解，安全第一；雨天订单更多，有助保资格。"
        elif self._has_any(last_user, ["影响合同", "影响派单", "会影响吗", "会不会影响"]) and not self._has_any(
            text,
            ["影响合同", "影响派单", "合同和派单", "可能受影响"],
        ):
            repaired = "未完会影响合同和派单。"
        elif self._has_any(last_user, ["注意", "提醒", "安全", "拒单", "取消", "超时"]) and not self._has_any(
            text,
            ["安全", "拒单", "取消", "超时"],
        ):
            repaired = "少拒单取消超时，有助保资格。"
        elif stage == "out_of_scope" and not self._has_any(text, ["同事确认", "再回电"]):
            repaired = "我同事确认后回电，先答我能答的。"
        elif stage == "accepted" and not self._has_any(text, ["注意安全", "辛苦", "先这样", "后续"]):
            repaired = "辛苦了，今天跑单注意安全。"

        return repaired, repaired != text

    def _collect_openai_stream_response(self, response: Any) -> str:
        parts: List[str] = []
        for chunk in response:
            content = None
            if isinstance(chunk, dict):
                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
            else:
                try:
                    choice = chunk.choices[0]
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None) if delta is not None else None
                except (AttributeError, IndexError, TypeError):
                    content = None
            if content:
                parts.append(str(content))
        content = "".join(parts).strip()
        if not content:
            raise TargetModelError("empty_model_response", "empty_model_response")
        return content

    def _call_custom_endpoint(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "task": task_payload,
            "case": case_payload,
            "messages": messages,
            "model": self.model_name,
            "task_type": self.infer_task_type(task_payload, case_payload),
            "retrieved_knowledge": retrieved_knowledge,
            "memory_state": compact_memory_for_prompt(memory_state),
            "knowledge_instruction": "以下是本轮可用知识片段，请优先依据这些内容回答。",
        }
        if self.infer_task_type(task_payload, case_payload) == "course_platform_outbound":
            payload["response_policy"] = self._course_response_policy()
        if self.infer_task_type(task_payload, case_payload) == "rider_outbound":
            payload["rider_name"] = self._rider_name_for_case(case_payload)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return self._post_json(self.endpoint, payload, headers)

    def _messages(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> List[Dict[str, str]]:
        task_type = self.infer_task_type(task_payload, case_payload)
        guardrails = {
            "rider_outbound": {
                "allowed": "飞毛腿合同、生效、开始配送、X 单、Y 单、合同影响、派单、安全、雨天、资格、报名排名、拒单、取消、超时、App 取消、同事确认后回电",
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
            "以下是本轮可用知识片段，请优先依据这些内容回答。"
            "memory_state 是本次评测 run 内的上下文状态，只能用于判断当前阶段、用户分支和待覆盖事项。"
            "不要替用户回答分支，不要跨 run 假设任何历史。"
        )
        if task_type == "course_platform_outbound":
            system += self._course_response_policy()
        elif task_type == "rider_outbound":
            system += (
                "除第0轮开场外，每次回复控制在30字内；已说过的内容不要原样重复，应推进下一个未覆盖流程点。"
                "飞毛腿递进式外呼按：确认身份、告知今天合同已签署并生效、"
                "提醒午餐/晚餐高峰上线、说明“单日合同生效当天必须完成 X 单；多日合同每天必须完成 Y 单；未完成合同及派单可能受影响”、询问能否开始配送、"
                "根据骑手态度鼓励挽留或安抚、提醒注意安全、最后补充说明报名按系统排名且不是站长人工干预，"
                "少拒单取消超时、恶劣天气订单更多有助保住资格，再做结束确认。"
                "FAQ 不要主动全量展开，只在用户问到退出、奖励、排名、天气、不想配送时短句回答。"
                "如果骑手说不想干、不想跑、无法配送或犹豫，必须先理解安抚，再结合 FAQ 挽留："
                "目前许多骑手正在申请飞毛腿；如果无法连续配送 Y 天，名额可能会被他人占用；"
                "单日合同生效当天必须完成 X 单，否则合同及派单可能受到影响；"
                "多日合同每天必须完成 Y 单，否则后续合同及派单可能受到影响；"
                "连续完成 W 天多日合同且每天完成 Y 单，将获得额外奖励，例如每单多 +$ 元。"
                "如用户问退出、不参加或取消，必须回答：如需退出飞毛腿，必须在前一天 Z 点之前在 App 的“飞毛腿报名”中取消；次日生效。"
                "如用户问奖励或激励，必须回答：连续完成 W 天多日合同，且每天完成 Y 单，将获得额外奖励，例如与单日合同相比每单多 +$ 元。"
                "如用户问单日/多日或没完成，必须同时说明 X 单/Y 单和合同及派单影响。"
                "超出职责问题只有用户主动追问时再回答。"
                "不要反问骑手合同是否生效；这是站长需要告知的信息。"
            )
        case_context = dict(case_payload)
        if task_type == "rider_outbound":
            case_context["rider_name"] = self._rider_name_for_case(case_payload)
        task_context = {
            "instruction_text": task_payload.get("instruction_text", ""),
            "role_text": task_payload.get("role_text", ""),
            "task_text": task_payload.get("task_text", ""),
            "opening_line": self._replace_rider_placeholders(task_payload.get("opening_line", ""), case_payload)
            if task_type == "rider_outbound"
            else task_payload.get("opening_line", ""),
            "call_flow": task_payload.get("call_flow", ""),
            "knowledge_points": task_payload.get("knowledge_points", ""),
            "constraints": task_payload.get("constraints", ""),
            "task_type": task_type,
            "case": case_context,
            "retrieved_knowledge": retrieved_knowledge,
            "memory_state": compact_memory_for_prompt(memory_state),
            "knowledge_instruction": "以下是本轮可用知识片段，请优先依据这些内容回答。",
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

    def _opening_messages(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        opening_line: str,
        retrieved_knowledge: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> List[Dict[str, str]]:
        task_type = self.infer_task_type(task_payload, case_payload)
        system = (
            "你是被测对话模型。现在只生成外呼第一句开场白。"
            "必须完成身份确认，符合当前任务角色，不要说明费用、配置路径、企业微信或其他后续流程。"
            f"task_type={task_type}。以下是本轮可用知识片段，请优先依据这些内容回答。"
            "memory_state 只表示当前 run 初始状态，不可跨 run 使用。"
        )
        task_context = {
            "opening_line": opening_line,
            "instruction_text": task_payload.get("instruction_text", ""),
            "role_text": task_payload.get("role_text", ""),
            "task_type": task_type,
            "case": case_payload,
            "retrieved_knowledge": retrieved_knowledge,
            "memory_state": compact_memory_for_prompt(memory_state),
        }
        if task_type == "rider_outbound":
            task_context["rider_name"] = self._rider_name_for_case(case_payload)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(task_context, ensure_ascii=False)},
        ]

    def _course_response_policy(self) -> str:
        return (
            "课程直播回复硬约束：每次最多 15-20 个中文字符左右；"
            "主流程按身份确认、知情确认、升级内容、区别价格、发布方式、配置路径、费用检查、企业微信、结束确认渐进推进；"
            "每次只说一个信息点；说完必须停下来等商家回应；"
            "负责人确认后先问：您了解低延迟直播吗？"
            "常规推进优先按：您了解低延迟直播吗？/发布页新增了独立的低延迟直播选项。/发课时选低延迟直播。/其他发课流程不变。"
            "直播区别分轮回答：标准直播费用低，延迟5-10秒。/适合大班课。/低延迟1-2秒，互动更流畅。/适合小班和实操课。"
            "只生成被测模型该说的话，不要替商家回答知道/不知道、Web/SaaS、是否已显示等分支；"
            "条件分支只在当前步骤内处理，处理后回到主流程；"
            "不要一次性说明标准直播、低延迟、费用、配置路径、企业微信；"
            "用户问多个问题时也要分步回答，先答最核心问题再引导下一步；"
            "不要使用“好的、哈哈、嗯嗯、嘿嘿、嘻嘻”等语气词；"
            "商家说开车时只回复“那我稍后再打。”并结束；"
            "商家说忙时先回复“就1分钟，保证简短。”，后续再用一句话说重点。"
        )

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

    def _extract_opening_line(self, instruction_text: str) -> str:
        lines = str(instruction_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        collecting = False
        collected: List[str] = []
        for raw_line in lines:
            line = raw_line.strip()
            lower = line.lower()
            heading_match = re.match(r"^#{1,6}\s+(.+)$", line)
            heading = heading_match.group(1).strip().lower() if heading_match else lower
            is_opening_heading = heading.startswith("opening line")
            is_next_heading = bool(heading_match) and not is_opening_heading
            if not heading_match and collecting and lower.startswith(
                ("role", "task", "call flow", "conversation flow", "knowledge points", "faq", "constraints")
            ):
                break
            if is_opening_heading:
                collecting = True
                inline = ""
                for separator in [":", "："]:
                    if separator in line:
                        inline = line.split(separator, 1)[1].strip()
                        break
                if inline:
                    collected.append(inline)
                continue
            if collecting:
                if is_next_heading:
                    break
                if line:
                    collected.append(line)
        return self._trim(" ".join(collected).strip(), 100)

    def _course_opening_line(self, raw_opening: str) -> str:
        if raw_opening and "负责人" not in raw_opening:
            return self._trim(raw_opening, 80)
        return "您好，请问您是负责人吗？"

    def _rider_opening_line(self, raw_opening: str, case_payload: Dict[str, Any]) -> str:
        rider_name = self._rider_name_for_case(case_payload)
        normalized = self._replace_rider_placeholders(str(raw_opening or ""), case_payload).replace("**", "").strip()
        if normalized and "站长" in normalized:
            sentences = re.findall(r"[^。！？!?]+[。！？!?]?", normalized)
            collected: List[str] = []
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                collected.append(sentence)
                if "站长" in sentence:
                    break
            candidate = "".join(collected).strip()
            if candidate and "站长" in candidate and self._has_any(candidate, ["请问是", "是您", "是你", "吗"]):
                return self._trim(candidate.replace("我是站长", "我是美团外卖骑手的站长"), 70)
        return f"你好，请问是{rider_name}吗？我是美团外卖骑手的站长。"

    def _replace_rider_placeholders(self, text: str, case_payload: Dict[str, Any]) -> str:
        rider_name = self._rider_name_for_case(case_payload)
        return (
            str(text or "")
            .replace("${rider_name}", rider_name)
            .replace("{rider_name}", rider_name)
            .replace("{{rider_name}}", rider_name)
        )

    def _rider_name_for_case(self, case_payload: Dict[str, Any]) -> str:
        text = self._conversation_text([], case_payload)
        patterns = [
            r"(?:rider_name|骑手姓名|姓名|名字)\s*[:：=]\s*([\u4e00-\u9fa5A-Za-z0-9_\-]{1,12})",
            r"([\u4e00-\u9fa5]{1,4}师傅)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return "王师傅"

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

    def _knowledge_reply(
        self,
        retrieved_knowledge: List[Dict[str, Any]],
        title: str,
        limit: int = 70,
    ) -> str:
        for chunk in retrieved_knowledge or []:
            if chunk.get("title") != title:
                continue
            content = str(chunk.get("content") or "").strip()
            if content:
                return self._trim(content, limit)
        return ""

    def _rider_contract_requirement_reply(self) -> str:
        return "单日合同当天X单，多日每天Y单，未完影响合同派单。"

    def _rider_peak_contract_reply(self) -> str:
        return "午晚高峰上线；单日当天X单，多日每天Y单，未完影响合同派单。"

    def _rider_reward_reply(self) -> str:
        return "连续W天每天Y单，可获额外奖励，每单多+$。"

    def _rider_exit_reply(self) -> str:
        return "前一天Z点前在App飞毛腿报名取消，次日生效。"

    def _rider_rank_qualification_reply(self) -> str:
        return "名额按系统排名，非站长定；少拒单取消超时保资格。"

    def _rider_contract_requirement_complete(self, text: str) -> bool:
        return (
            not self._rider_contract_requirement_invalid(text)
            and self._has_any(text, ["单日合同生效当天", "单日合同当天", "单日当天", "单日X单", "单日 X 单"])
            and self._has_any(text, ["多日合同每天必须完成 Y 单", "多日每天必须完成 Y 单", "多日合同每天完成 Y 单", "多日每天Y单", "多日每天 Y 单"])
            and self._has_any(text, ["影响合同", "影响派单", "合同及派单", "合同和派单", "合同派单", "可能受影响"])
        )

    def _rider_contract_requirement_invalid(self, text: str) -> bool:
        return self._has_any(
            text,
            [
                "每天至少完成 X 单或 Y 单",
                "每天至少完成X单或Y单",
                "每天完成 X 单或 Y 单",
                "每天完成X单或Y单",
                "每天至少完成 X 单",
                "单日合同每天",
                "X 单或 Y 单",
                "X单或Y单",
                "X 或 Y",
                "X或Y",
            ],
        )

    def _rider_unwilling_fallback(self) -> str:
        return "理解；许多骑手申请，跑不了名额可能被占。"

    def _rider_unwilling_reply_complete(self, text: str) -> bool:
        return (
            self._has_any(text, ["理解", "辛苦", "明白", "能理解", "安抚", "记录"])
            and self._has_any(text, ["许多骑手", "很多骑手", "名额", "被占", "占用", "资格"])
            and self._has_any(text, ["连续 Y 天", "连续Y天", "Y 天", "Y天"])
            and self._has_any(text, ["X 单", "X单", "单日"])
            and self._has_any(text, ["Y 单", "Y单", "多日"])
            and self._has_any(text, ["影响合同", "影响派单", "合同及派单", "合同和派单", "可能受影响"])
            and self._has_any(text, ["W 天", "W天", "额外奖励", "+$"])
        )

    def _rider_rank_reply_complete(self, text: str) -> bool:
        return (
            rider_rank_qualification_done(text)
            and self._has_any(text, ["连续 Y 天", "连续Y天", "Y 天", "Y天", "名额可能被占", "被占用"])
        )

    def _rider_variant(self, memory_state: Dict[str, Any] | None, *options: str) -> str:
        if not options:
            return ""
        return options[0]

    def _has_any(self, text: str, keywords: List[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)
