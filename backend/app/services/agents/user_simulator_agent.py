from __future__ import annotations

import random
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, List, Tuple

from app.services.case_mode import normalize_case_mode
from app.services.course_flow import course_full_flow_expected_steps, course_full_flow_step_done
from app.services.dialogue_state import analyze_dialogue_state, is_similar_text
from app.services.rider_flow import rider_full_flow_expected_steps, rider_rank_qualification_done


@dataclass
class SimulatedUserState:
    persona: str
    emotion_level: int
    patience: int
    info_completeness: str
    goal_progress: str
    interruption_count: int
    current_intent: str
    task_type: str
    profile: str


class UserSimulatorAgent:
    """被外呼对象模拟器 Agent.

    The agent is deterministic by default for stable demos, but every turn is
    derived from task instruction, case persona, historical messages, and the
    target model's latest reply instead of a fixed turn template.
    """

    def generate_message(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        turn_index: int,
        memory_state: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        task_type = self._task_type(task_payload, case_payload)
        profile = self._profile_kind(task_type, case_payload)
        case_mode = normalize_case_mode(case_payload.get("case_mode"), case_payload)
        recent_messages = list(messages[-6:])
        memory_state = self._memory_state(memory_state, messages)
        base_state = self._build_user_state(task_payload, case_payload, recent_messages, turn_index, task_type, profile)

        if turn_index <= 1:
            content = self._initial_response(task_type, profile, case_mode, case_payload)
            event = self.choose_user_event(memory_state, case_payload, turn_index)
            return self._pack(
                content,
                replace(base_state, current_intent="初始回应"),
                True,
                self._event_metadata(event, memory_state, content, "初始回应"),
            )

        dialogue_state = analyze_dialogue_state(task_payload, case_payload, recent_messages or messages)
        last_assistant = dialogue_state.get("last_assistant_message", "")
        event = self.choose_user_event(memory_state, case_payload, turn_index)
        event_reaction = self._course_event_reaction(
            task_type,
            event,
            profile,
            memory_state,
            dialogue_state,
            case_payload,
            messages,
        )
        direct_branch = self._direct_course_branch_reaction(task_type, case_payload, last_assistant)
        memory_reaction = self._memory_reaction(
            task_type,
            profile,
            case_payload,
            memory_state,
            recent_messages,
            last_assistant,
            base_state,
        )
        risk = self._detect_risk(task_type, profile, last_assistant, recent_messages)

        if event_reaction and (event in {"driving", "busy"} or not memory_reaction):
            content, intent, should_continue, progress, emotion_delta, patience_delta = event_reaction
        elif direct_branch:
            content, intent, should_continue, progress, emotion_delta, patience_delta = direct_branch
        elif memory_reaction:
            content, intent, should_continue, progress, emotion_delta, patience_delta = memory_reaction
        elif risk:
            content, intent, should_continue, progress, emotion_delta, patience_delta = risk
        elif self._assistant_closes(last_assistant):
            if case_mode == "full_flow" and not self._full_flow_ready(task_type, case_payload, dialogue_state, messages):
                content, intent = self._full_flow_followup(
                    task_type,
                    profile,
                    dialogue_state,
                    case_payload,
                    messages,
                    memory_state,
                )
                should_continue, progress, emotion_delta, patience_delta = True, "in_progress", 0, 0
            else:
                content, intent, should_continue, progress, emotion_delta, patience_delta = (
                    self._closing_user_message(task_type, profile),
                    "接受并结束",
                    False,
                    "accepted",
                    -1,
                    1,
                )
        elif self._reply_too_long(task_type, last_assistant, base_state):
            recent_user_text = "\n".join(str(item.get("user_message", "") or "") for item in recent_messages)
            interruption = "再短点。" if self._has_any(recent_user_text, ["说重点", "没时间", "太长"]) else "你说重点，我没时间听太长。"
            content, intent, should_continue, progress, emotion_delta, patience_delta = (
                interruption,
                "打断冗长回复",
                True,
                "in_progress",
                1,
                -1,
            )
        elif self._assistant_repeated(recent_messages):
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._repeat_reaction(
                task_type,
                profile,
                base_state,
            )
        elif not self._answered_current_need(task_type, profile, dialogue_state, last_assistant):
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._follow_unanswered(
                task_type,
                profile,
            )
        elif case_mode == "full_flow":
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._full_flow_message(
                task_type,
                case_payload,
                dialogue_state,
                messages,
                memory_state,
            )
        elif task_type == "rider_outbound":
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._rider_message(
                profile,
                dialogue_state,
                memory_state,
            )
        elif task_type == "course_platform_outbound":
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._course_message(
                profile,
                dialogue_state,
                memory_state,
            )
        else:
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._generic_message(
                turn_index,
            )

        state = replace(
            base_state,
            emotion_level=self._clamp(base_state.emotion_level + emotion_delta),
            patience=self._clamp(base_state.patience + patience_delta),
            goal_progress=progress,
            current_intent=intent,
            interruption_count=base_state.interruption_count + (1 if intent == "打断冗长回复" else 0),
        )
        if should_continue:
            content = self.deduplicate_user_message(content, messages, asdict(state)).strip()
        if not should_continue:
            state = replace(state, goal_progress=progress if progress in {"accepted", "rejected"} else "accepted")
        return self._pack(
            content,
            state,
            should_continue,
            self._event_metadata(event, memory_state, content, state.current_intent),
        )

    def choose_user_event(
        self,
        memory_state: Dict[str, Any] | None,
        case: Dict[str, Any],
        turn_index: int,
    ) -> str:
        profile_text = self._joined(
            case.get("name", ""),
            case.get("user_profile", ""),
            case.get("initial_message", ""),
            case.get("user_behavior_type", ""),
            case.get("trigger_conditions", []),
        )
        identity_text = self._joined(
            case.get("name", ""),
            case.get("user_profile", ""),
            case.get("initial_message", ""),
            case.get("user_behavior_type", ""),
        )
        if "正在开车商家" in identity_text or ("开车" in identity_text and turn_index <= 2):
            return "driving"
        if "忙碌商家" in identity_text and turn_index <= 2:
            return "busy"
        explicit_event_profile = self._has_any(
            identity_text,
            ["反复追问商家", "技术不熟悉商家", "价格敏感商家", "被打断后继续追问商家"],
        )
        if "被打断后继续追问商家" in identity_text and turn_index >= 2:
            return "interrupt"
        if "反复追问商家" in identity_text and turn_index >= 2:
            return "ask_question"
        has_seed = bool((memory_state or {}).get("run_context")) if isinstance(memory_state, dict) else False
        if not explicit_event_profile and (not has_seed or "强渐进" in profile_text or "完整流程" in profile_text or case.get("case_mode") == "full_flow" or "课程直播产品升级外呼" in profile_text or "飞毛腿骑手合同生效外呼" in profile_text):
            return "normal"
        current_step = self._course_current_step(memory_state)
        available = self._available_events_for_step(current_step)
        weights = {
            "normal": 60,
            "ask_question": 15,
            "interrupt": 10,
            "confused": 5,
            "technical_issue": 5,
            "price_sensitive": 3,
            "busy": 1,
            "driving": 1,
        }
        if "忙碌商家" in profile_text:
            weights.update({"busy": 60, "normal": 30})
        if "反复追问商家" in profile_text or "追问直播区别" in profile_text:
            weights.update({"ask_question": 30, "interrupt": 20, "normal": 40})
        if "技术不熟悉商家" in profile_text or "第三方" in profile_text or "看不到" in profile_text:
            weights.update({"technical_issue": 45, "ask_question": 20, "normal": 30})
        if "价格敏感商家" in profile_text or "优惠券" in profile_text or "费用" in profile_text:
            weights.update({"price_sensitive": 45, "ask_question": 20, "normal": 30})
        if "被打断后继续追问商家" in profile_text:
            weights.update({"interrupt": 45, "ask_question": 20, "normal": 30})

        filtered = [(event, weight) for event, weight in weights.items() if event in available and weight > 0]
        if not filtered:
            return "normal"
        rng = random.Random(self._event_seed(memory_state, case, turn_index))
        total = sum(weight for _, weight in filtered)
        draw = rng.uniform(0, total)
        upto = 0.0
        for event, weight in filtered:
            upto += weight
            if draw <= upto:
                return event
        return filtered[-1][0]

    def _course_event_reaction(
        self,
        task_type: str,
        event: str,
        profile: str,
        memory_state: Dict[str, Any],
        dialogue_state: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> Tuple[str, str, bool, str, int, int] | None:
        if task_type != "course_platform_outbound" or event == "normal":
            return None
        current_step = self._course_current_step(memory_state)
        if event == "driving":
            branch_memory = (memory_state or {}).get("user_branch_memory") or {}
            if branch_memory.get("is_driving"):
                return "我在开车，先不说了。", "开车后拒绝继续沟通", False, "rejected", 1, -2
            return "我在开车，不方便说。", "开车后拒绝继续沟通", False, "rejected", 1, -2
        if event == "busy":
            return "我现在很忙。", "忙碌中断", True, "in_progress", 1, -1
        content = self._event_question(event, current_step, profile, case_payload, messages)
        if not content:
            return None
        intent = {
            "interrupt": "随机打断",
            "ask_question": "随机追问",
            "confused": "表示不理解",
            "technical_issue": "技术配置问题",
            "price_sensitive": "费用敏感追问",
        }.get(event, "随机事件")
        return content, intent, True, "in_progress", 0, -1 if event in {"interrupt", "confused"} else 0

    def _event_question(
        self,
        event: str,
        current_step: str,
        profile: str,
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> str:
        assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in messages)
        if event == "technical_issue":
            if self._has_any(assistant_text, ["进【我的】", "进入【我的】", "点直播平台管理", "选择【直播平台】"]):
                return "到了，继续。"
            return "第三方系统看不到是哪一步？"
        if event == "price_sensitive":
            if current_step in {"fee_check", "difference_explain", "awareness_check"}:
                return self._variant_text(None, "费用会变吗？", "能不能优惠？", "学员端费用也要看吗？")
            return "这个会多收费吗？"
        step_questions = {
            "identity_check": ["我是负责人，你说吧。", "我现在很忙。", "我在开车，不方便说。"],
            "upgrade_intro": ["等等，升级什么？", "这个和我有什么关系？", "你先说重点。"],
            "awareness_check": ["为什么后台给我改了？", "我之前不知道这事。", "这个会多收费吗？"],
            "option_intro": ["哪两个选项？", "这个怎么选？", "我没太听懂。"],
            "difference_explain": ["标准和低延迟差在哪？", "哪个更适合小班课？", "大班课选哪个？"],
            "publish_method_check": ["发课流程会变吗？", "Web和第三方有区别吗？", "我不知道我们用哪个。"],
            "configuration_guidance": ["第三方系统看不到是哪一步？", "我不知道点哪里。", "你一步一步说。"],
            "fee_check": ["费用还要重新配吗？", "学员会看到附加费吗？", "能不能优惠？"],
            "wecom_check": ["手机号加不了怎么办？", "我不想加企微。", "后续怎么联系？"],
            "closing": ["那学生端有影响吗？", "没问题了。", "还有费用要看吗？"],
        }
        options = step_questions.get(current_step) or ["等等，你说的低延迟是啥？", "你先说重点。", "我没太听懂。"]
        if event == "confused":
            options = ["我没太听懂。", "你先说重点。", "这个会影响发课吗？"]
        if event == "ask_question" and current_step == "closing":
            options = ["那学生端有影响吗？", "费用还要看吗？", "后续怎么联系？"]
        index = self._event_seed(None, case_payload, len(messages) + len(current_step)) % len(options)
        return options[index]

    def _event_metadata(
        self,
        event: str,
        memory_state: Dict[str, Any] | None,
        content: str,
        intent: str,
    ) -> Dict[str, Any]:
        current_step = self._course_current_step(memory_state)
        interrupted = event in {"interrupt", "ask_question", "confused", "technical_issue", "price_sensitive"}
        return {
            "user_event": event,
            "current_step": current_step,
            "interrupted": interrupted,
            "interrupted_from_step": current_step if interrupted else "",
            "pending_return_step": current_step if interrupted else "",
            "last_user_question": content if ("？" in content or "?" in content or interrupted) else "",
            "is_busy": event == "busy",
            "is_driving": event == "driving",
            "should_continue": event != "driving",
            "next_best_action": "先回答问题，再回到原流程" if interrupted else intent,
        }

    def _direct_course_branch_reaction(
        self,
        task_type: str,
        case_payload: Dict[str, Any],
        last_assistant: str,
    ) -> Tuple[str, str, bool, str, int, int] | None:
        if task_type != "course_platform_outbound" or not last_assistant:
            return None
        if self._has_any(last_assistant, ["Web还是第三方", "发布方式"]):
            return self._course_branch_answer(case_payload, "publish_method"), "回答发布方式", True, "in_progress", 0, 0
        if self._has_any(last_assistant, ["保障质量", "您知道吗", "后台已走低延迟"]):
            return self._course_branch_answer(case_payload, "awareness"), "回答是否知情", True, "in_progress", 0, 0
        if self._has_any(last_assistant, ["低延迟已显示吗", "已显示吗", "显示吗"]):
            return self._course_branch_answer(case_payload, "visibility"), "回答前端是否可见", True, "in_progress", 0, 0
        if self._has_any(last_assistant, ["附加费", "学员端"]):
            return self._course_branch_answer(case_payload, "fee"), "回答费用设置情况", True, "in_progress", 0, 0
        if self._has_any(last_assistant, ["当前号码能加吗", "号码能加吗"]):
            return self._course_branch_answer(case_payload, "wechat"), "回答企业微信号码状态", True, "in_progress", 0, 0
        return None

    def deduplicate_user_message(
        self,
        content: str,
        messages: List[Dict[str, Any]],
        user_state: Dict[str, Any],
    ) -> str:
        previous = [str(item.get("user_message", "") or "") for item in messages if item.get("user_message")]
        if not any(is_similar_text(content, item) for item in previous):
            return content

        alternatives = self._user_alternatives(user_state.get("task_type", ""), user_state.get("profile", ""))
        for alternative in alternatives:
            if not any(is_similar_text(alternative, item) for item in previous):
                return alternative
        return alternatives[-1] if alternatives else content

    def _build_user_state(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        turn_index: int,
        task_type: str,
        profile: str,
    ) -> SimulatedUserState:
        persona = case_payload.get("user_profile") or self._persona_label(task_type, profile)
        emotion = self._base_emotion(profile, case_payload.get("difficulty", "中等"))
        patience = self._base_patience(profile, case_payload.get("difficulty", "中等"))
        interruption_count = 0
        progress = "not_started" if turn_index <= 1 else "in_progress"
        current_intent = "等待说明"

        for item in messages:
            user = str(item.get("user_message", "") or "")
            assistant = str(item.get("assistant_message", "") or "")
            if self._has_any(user, ["说重点", "没时间", "先挂了", "不方便说"]):
                interruption_count += 1
            if self._reply_too_long(task_type, assistant, None):
                emotion += 1
                patience -= 1
            if self._has_any(assistant, ["稍后再打", "后续可再联系", "后续有问题再联系", "祝课程顺利"]):
                progress = "accepted"
            if self._detect_risk(task_type, profile, assistant, messages):
                emotion += 2
                patience -= 2

        info_completeness = self._info_completeness(task_payload, case_payload, task_type, profile)
        return SimulatedUserState(
            persona=persona,
            emotion_level=self._clamp(emotion),
            patience=self._clamp(patience),
            info_completeness=info_completeness,
            goal_progress=progress,
            interruption_count=interruption_count,
            current_intent=current_intent,
            task_type=task_type,
            profile=profile,
        )

    def _memory_state(
        self,
        memory_state: Dict[str, Any] | None,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if isinstance(memory_state, dict) and memory_state:
            return memory_state
        for item in reversed(messages or []):
            detail = item.get("detail") or {}
            candidate = detail.get("memory_state") or detail.get("memoryState")
            if isinstance(candidate, dict) and candidate:
                return candidate
        return {}

    def _memory_reaction(
        self,
        task_type: str,
        profile: str,
        case_payload: Dict[str, Any],
        memory_state: Dict[str, Any],
        recent_messages: List[Dict[str, Any]],
        last_assistant: str,
        base_state: SimulatedUserState,
    ) -> Tuple[str, str, bool, str, int, int] | None:
        if not memory_state or not last_assistant:
            return None

        user_text = "\n".join(str(item.get("user_message", "") or "") for item in recent_messages)
        if self._memory_bool(memory_state, "is_driving", "driving") and self._assistant_pushes_business(task_type, last_assistant):
            return "我都说开车了，先不说了。", "开车后拒绝继续沟通", False, "rejected", 2, -2

        if (
            self._memory_bool(memory_state, "is_busy", "busy")
            and "说重点" not in user_text
            and "没时间" not in user_text
            and not self._assistant_handles_busy(last_assistant)
        ):
            if self._assistant_pushes_business(task_type, last_assistant) or self._reply_too_long(task_type, last_assistant, base_state):
                return "你说重点，我没时间。", "忙碌后打断", True, "in_progress", 1, -1

        responsible = self._memory_value(memory_state, "is_responsible_person", "is_owner")
        if responsible is False and self._assistant_pushes_business(task_type, last_assistant):
            return "我不是负责人，你跟我说也没用。", "非负责人拒绝强推", False, "rejected", 1, -2

        performance = self._performance_memory(memory_state)
        if performance.get("off_topic_count", 0) > 0 or performance.get("cross_task_terms"):
            if task_type == "course_platform_outbound":
                return "你是不是说错业务了？我问的是直播功能。", "指出业务串场", False, "rejected", 2, -2
            if task_type == "rider_outbound":
                return "你是不是说错业务了？我问的是飞毛腿。", "指出业务串场", False, "rejected", 2, -2

        if performance.get("repeat_count", 0) > 0 or self._assistant_repeated(recent_messages):
            if "已经说过" not in user_text and "重复" not in user_text:
                return "你刚才已经说过了。", "指出模型重复", True, "in_progress", 1, -1

        if performance.get("too_verbose_count", 0) > 0 and self._reply_too_long(task_type, last_assistant, base_state):
            if "说重点" not in user_text:
                return "你说重点。", "打断冗长回复", True, "in_progress", 1, -1

        unanswered = self._conversation_memory(memory_state).get("last_unanswered_question", "")
        if unanswered or performance.get("unanswered_question_count", 0) > 0:
            if "不是别的" not in user_text:
                return "我问的是这个，不是别的。", "继续追问未回答问题", True, "in_progress", 1, -1

        assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in recent_messages)
        flow_prompt = self._flow_memory_prompt(task_type, memory_state, last_assistant, user_text, assistant_text)
        if flow_prompt:
            return flow_prompt

        unfinished_prompt = self._unfinished_memory_prompt(task_type, memory_state, last_assistant, user_text, case_payload)
        if unfinished_prompt:
            return unfinished_prompt
        return None

    def _flow_memory_prompt(
        self,
        task_type: str,
        memory_state: Dict[str, Any],
        last_assistant: str,
        user_text: str,
        assistant_text: str,
    ) -> Tuple[str, str, bool, str, int, int] | None:
        pending = self._pending_memory_items(memory_state)
        if task_type == "course_platform_outbound":
            early_pending = self._has_pending(
                pending,
                ["确认是否知情", "传达升级内容", "产品升级说明", "说明标准直播", "说明价格差异"],
            )
            if self._has_pending(pending, ["身份确认"]) and not self._has_any(last_assistant, ["负责人", "转达"]):
                return "你先说你找谁？", "追问身份确认", True, "in_progress", 1, -1
            if self._has_pending(pending, ["传达升级内容", "产品升级说明"]) and not self._has_any(assistant_text, ["新增低延迟直播选项", "分标准和低延迟", "发布页以后"]):
                return "到底新增了什么？", "追问升级内容", True, "in_progress", 0, -1
            if (
                self._has_pending(pending, ["询问发布方式"])
                and not early_pending
                and "发布方式" not in user_text
                and self._has_any(last_assistant, ["标准直播", "低延迟", "费用", "互动"])
                and not self._has_any(last_assistant, ["Web", "校务", "SaaS", "第三方"])
            ):
                return "这个跟我现在发布方式有关系吗？", "引导发布方式确认", True, "in_progress", 0, 0
        if task_type == "rider_outbound":
            if self._has_pending(pending, ["告知今天飞毛腿合同已生效", "告知合同生效"]) and not self._has_any(last_assistant, ["合同已签署", "合同已生效"]):
                return "你先说合同现在是什么状态。", "追问合同状态", True, "in_progress", 0, -1
            if self._has_pending(pending, ["说明午晚高峰", "单量要求"]) and not self._has_any(last_assistant, ["X 单", "Y 单", "高峰"]):
                return "今天具体要跑多少单？", "追问配送要求", True, "in_progress", 0, -1
        return None

    def _unfinished_memory_prompt(
        self,
        task_type: str,
        memory_state: Dict[str, Any],
        last_assistant: str,
        user_text: str,
        case_payload: Dict[str, Any],
    ) -> Tuple[str, str, bool, str, int, int] | None:
        unfinished = memory_state.get("unfinished_memory") or memory_state.get("unfinished_items_memory") or {}
        next_action = str(
            unfinished.get("next_best_action")
            or unfinished.get("next_suggested_step")
            or ""
        )
        pending = self._pending_memory_items(memory_state)
        if next_action and pending and not any(next_action in item or item in next_action for item in pending):
            next_action = ""
        focus = next_action or (pending[0] if pending else "")
        if not focus:
            return None
        if task_type == "course_platform_outbound":
            if self._has_any(last_assistant, ["Web还是第三方", "发布方式", "Web", "第三方"]):
                return self._course_branch_answer(case_payload, "publish_method"), "回答发布方式", True, "in_progress", 0, 0
            if self._has_any(last_assistant, ["低延迟已显示吗", "已显示吗", "显示吗"]):
                return self._course_branch_answer(case_payload, "visibility"), "回答前端是否可见", True, "in_progress", 0, 0
            if self._has_any(last_assistant, ["附加费", "学员端"]):
                return self._course_branch_answer(case_payload, "fee"), "回答费用设置情况", True, "in_progress", 0, 0
            if self._has_any(last_assistant, ["当前号码能加吗", "号码能加吗"]):
                return self._course_branch_answer(case_payload, "wechat"), "回答企业微信号码状态", True, "in_progress", 0, 0
            if self._has_pending(pending, ["确认是否知情", "传达升级内容", "产品升级说明", "说明标准直播和低延迟直播区别", "说明价格差异"]) and not self._has_any(last_assistant, ["保障质量", "您知道吗", "后台已走低延迟"]):
                return None
            prompts = {
                "传达升级内容": ("到底新增了什么？", "追问升级内容"),
                "说明标准直播和低延迟直播区别": ("区别是什么？", "追问直播区别"),
                "说明价格差异": ("费用会不会更高？", "追问价格差异"),
                "询问发布方式": ("这个跟我现在发布方式有关系吗？", "引导发布方式确认"),
                "确认前端是否可见并说明配置路径": ("那我现在在哪里看？", "追问配置路径"),
                "检查学员端费用/加速线路费": ("学员端费用要不要处理？", "追问费用配置"),
                "企业微信添加": ("后续怎么联系？", "追问企业微信"),
            }
            for key, value in prompts.items():
                if key in focus and value[0] not in user_text:
                    return value[0], value[1], True, "in_progress", 0, 0
        if task_type == "rider_outbound":
            if "说明排名与保资格规则" in focus:
                if not self._has_any(user_text, ["名额", "站长", "排名"]):
                    return "那飞毛腿名额是你们站长定的吗？", "追问排名保资格规则", True, "in_progress", 0, 0
                return "怎么才能保住飞毛腿资格？", "追问保资格规则", True, "in_progress", 0, 0
            prompts = {
                "提醒注意安全": ("好，我今天按要求跑。", "等待站长安全提醒"),
                "询问是否可以开始配送": ("那今天要我开始配送吗？", "追问是否开始配送"),
            }
            for key, value in prompts.items():
                if key in focus and value[0] not in user_text:
                    return value[0], value[1], True, "in_progress", 0, 0
        return None

    def _pending_memory_items(self, memory_state: Dict[str, Any]) -> List[str]:
        flow = memory_state.get("flow_memory") or {}
        unfinished = memory_state.get("unfinished_memory") or memory_state.get("unfinished_items_memory") or {}
        values = (
            flow.get("pending_steps")
            or flow.get("pending_stages")
            or unfinished.get("required_rules_pending")
            or unfinished.get("required_pending")
            or []
        )
        return [str(item) for item in values if str(item).strip()]

    def _has_pending(self, pending: List[str], keywords: List[str]) -> bool:
        return any(self._has_any(item, keywords) for item in pending)

    def _performance_memory(self, memory_state: Dict[str, Any]) -> Dict[str, Any]:
        performance = memory_state.get("model_performance_memory") or {}
        return performance if isinstance(performance, dict) else {}

    def _conversation_memory(self, memory_state: Dict[str, Any]) -> Dict[str, Any]:
        conversation = memory_state.get("conversation_memory") or {}
        return conversation if isinstance(conversation, dict) else {}

    def _memory_value(self, memory_state: Dict[str, Any], run_key: str, snapshot_key: str) -> Any:
        branch = memory_state.get("user_branch_memory") or {}
        if run_key in branch:
            return branch.get(run_key)
        return branch.get(snapshot_key)

    def _memory_bool(self, memory_state: Dict[str, Any], run_key: str, snapshot_key: str) -> bool:
        return bool(self._memory_value(memory_state, run_key, snapshot_key))

    def _assistant_pushes_business(self, task_type: str, text: str) -> bool:
        if task_type == "course_platform_outbound":
            return self._has_any(text, ["直播", "低延迟", "标准直播", "升级", "发布页", "费用", "配置", "企业微信"])
        if task_type == "rider_outbound":
            return self._has_any(text, ["飞毛腿", "合同", "配送", "派单", "高峰", "X 单", "Y 单", "资格"])
        return bool(text.strip())

    def _assistant_handles_busy(self, text: str) -> bool:
        return self._has_any(text, ["1分钟", "1 分钟", "保证简短", "说重点", "简单说", "简短"])

    def _detect_risk(
        self,
        task_type: str,
        profile: str,
        last_assistant: str,
        messages: List[Dict[str, Any]],
    ) -> Tuple[str, str, bool, str, int, int] | None:
        if not last_assistant:
            return None
        if task_type == "course_platform_outbound" and profile == "course_driver":
            keeps_selling = self._has_any(last_assistant, ["直播", "低延迟", "升级", "发布页", "费用", "配置"])
            stops = self._has_any(last_assistant, ["稍后", "再打", "注意安全", "方便时", "不打扰"])
            if keeps_selling and not stops:
                return "我都说在开车了，你还继续推销，先挂了。", "开车场景被继续推销后结束", False, "rejected", 2, -2
        if task_type == "rider_outbound" and profile == "rider_weather":
            if self._has_any(last_assistant, ["必须跑", "强制", "不跑不行", "冒雨也要", "必须配送"]):
                return "你这是让我冒险，我先不聊了。", "恶劣天气被强迫后不满", False, "rejected", 2, -2
        return None

    def _rider_message(
        self,
        profile: str,
        dialogue_state: Dict[str, Any],
        memory_state: Dict[str, Any] | None = None,
    ) -> Tuple[str, str, bool, str, int, int]:
        said = set(dialogue_state.get("assistant_said_topics", []))
        rank_done = "已说明排名与保资格规则" in said or (
            "已说明排名规则" in said
            and "已提醒少拒单取消超时" in said
            and ("已说明天气资格" in said or "已说明名额紧张" in said)
        )
        safety_done = "已提醒安全" in said
        if "已说明合同已生效" not in said:
            return self._variant_text(memory_state, "是我，你说。", "对，是我，你讲。", "是我，直接说吧。"), "确认本人身份", True, "in_progress", 0, 0
        if "已说明 X 单/Y 单" not in said or "已询问是否开始配送" not in said:
            return self._variant_text(memory_state, "你继续说要求。", "具体要求你接着说。", "那要怎么跑，你说。"), "等待基础通知", True, "in_progress", 0, 0
        if profile == "rider_weather":
            if "已提醒安全" in said and "已说明天气资格" in said:
                return self._variant_text(memory_state, "好，我注意安全，雨小了再看能不能跑。", "行，安全第一，雨小点我再接。", "知道了，我看天气情况再跑。"), "接受天气和资格说明", False, "accepted", -1, 1
            if "已提醒安全" in said:
                return self._variant_text(memory_state, "那我晚点看雨小不小，别影响安全就行。", "可以，但雨大我肯定先顾安全。", "我等雨小点，安全别受影响。"), "天气态度缓和", True, "in_progress", -1, 1
            return self._variant_text(memory_state, "今天下雨这么大，怎么还让我跑？", "雨这么大，还必须出去送吗？", "这种天气跑单安全吗？"), "继续追问天气安全", True, "in_progress", 1, -1
        if profile == "rider_reject":
            if "已说明合同和派单影响" in said and "已安抚无法配送" in said:
                return self._variant_text(memory_state, "如果真跑不了，你帮我记录一下。", "那我实在跑不了，你这边记一下。", "真不行的话，麻烦帮我备注。"), "请求记录无法配送", False, "accepted", -1, 1
            if "已说明奖励规则" in said and "已说明合同和派单影响" not in said:
                return self._variant_text(memory_state, "不完成会影响合同和派单吗？", "那没完成会不会影响后续派单？", "如果今天没跑够，会影响合同吗？"), "追问未完成影响", True, "in_progress", 0, 0
            if ("已说明名额紧张" in said or "已安抚无法配送" in said) and "已说明奖励规则" not in said:
                return self._variant_text(memory_state, "连续跑完会有激励吗？", "那连续完成有额外奖励吗？", "多日都跑满会多给奖励吗？"), "追问奖励规则", True, "in_progress", 0, 0
            if "已说明合同和派单影响" in said:
                return self._variant_text(memory_state, "我确实跑不了。", "我今天确实没法跑。", "我这边真安排不开。"), "坚持无法配送", True, "in_progress", 0, 0
            return self._variant_text(memory_state, "我今天真不想跑，不完成会怎样？", "今天我不想配送，会影响什么？", "要是我今天不跑，后果是什么？"), "表达拒绝并追问影响", True, "in_progress", 1, -1
        if profile == "rider_hesitant":
            if "已说明名额紧张" in said or "已说明合同和派单影响" in said:
                return self._variant_text(memory_state, "行，我尽量高峰期跑一下。", "那我尽量午晚高峰上线。", "可以，我尽量挑高峰跑。"), "犹豫后接受挽留", False, "accepted", -1, 1
            return self._variant_text(memory_state, "我不一定，今天有点忙。", "我今天时间不太稳。", "我不确定能不能一直跑。"), "犹豫是否配送", True, "in_progress", 0, -1
        if profile == "rider_rank":
            if rank_done:
                return self._variant_text(memory_state, "明白，只要不是人为干预就行。", "知道了，不是站长定的就行。", "行，我了解排名规则了。"), "接受排名解释", False, "accepted", -1, 1
            return self._variant_text(memory_state, "为什么别人能报上，我排不上？", "名额到底按什么排的？", "这个排名不是站长能调的吗？"), "质疑报名排名", True, "in_progress", 1, -1
        if profile == "rider_exit":
            if "已说明退出流程" in said:
                return self._variant_text(memory_state, "明白了，我去 App 报名页看看。", "好，我去飞毛腿报名里取消。", "知道了，我按你说的去 App 看。"), "接受退出流程", False, "accepted", -1, 1
            return self._variant_text(memory_state, "我想退出飞毛腿，怎么取消？", "不想参加了，在哪里取消？", "飞毛腿报名能不能退，怎么操作？"), "追问退出流程", True, "in_progress", 0, -1
        if profile == "rider_reward":
            if "已说明奖励规则" in said:
                return self._variant_text(memory_state, "明白，别编具体金额就行。", "行，具体金额按规则看就行。", "知道了，有没有以页面规则为准。"), "接受奖励说明", False, "accepted", -1, 1
            return self._variant_text(memory_state, "连续跑完会有奖励或补贴吗？", "连续完成有没有额外激励？", "多日都跑满会多给奖励吗？"), "追问奖励规则", True, "in_progress", 0, -1
        if profile == "rider_out_of_scope":
            if "已说明超出范围回电" in said:
                return self._variant_text(memory_state, "行，那你确认后再回我。", "可以，你问清楚再联系我。", "那你确认完再回电话吧。"), "接受回电说明", False, "accepted", -1, 1
            return self._variant_text(memory_state, "平台算法怎么算，为什么我派单少？", "派单多少是系统怎么算的？", "为什么别人单多，我这边少？"), "追问职责外问题", True, "in_progress", 1, -1
        if profile == "rider_repeated":
            if "已说明合同和派单影响" in said and "已说明 X 单/Y 单" in said:
                return self._variant_text(memory_state, "那我今天尽量跑。", "明白，我尽量把单量完成。", "行，我今天尽量按要求跑。"), "接受合同影响说明", False, "accepted", -1, 1
            return self._variant_text(memory_state, "那如果今天没完成 X 单，会影响派单吗？", "今天没跑够 X 单，合同会受影响吗？", "单日没完成的话，会不会影响后续派单？"), "追问合同影响", True, "in_progress", 0, -1
        if safety_done and not rank_done:
            return self._variant_text(memory_state, "那飞毛腿名额是你们站长定的吗？", "名额是系统排还是站长定？", "飞毛腿名额是不是站长能调？"), "追问排名保资格规则", True, "in_progress", 0, 0
        if rank_done and not safety_done:
            return self._variant_text(memory_state, "配送时还有什么安全要注意？", "跑单安全上还要注意啥？", "那配送时安全方面怎么做？"), "追问安全提醒", True, "in_progress", 0, 0
        if rank_done and safety_done:
            return self._variant_text(memory_state, "好，我知道了，今天跑单注意安全。", "行，我按要求跑，也注意安全。", "明白，今天我尽量安全完成。"), "接受配送要求", False, "accepted", -1, 1
        return self._variant_text(memory_state, "可以，我今天能跑。", "能跑，我今天可以上线。", "可以，今天我会跑。"), "愿意配送", True, "in_progress", 0, 0

    def _course_message(
        self,
        profile: str,
        dialogue_state: Dict[str, Any],
        memory_state: Dict[str, Any] | None = None,
    ) -> Tuple[str, str, bool, str, int, int]:
        said = set(dialogue_state.get("assistant_said_topics", []))
        last_assistant = str(dialogue_state.get("last_assistant_message", "") or "")
        if profile == "course_driver":
            return self._variant_text(memory_state, "先挂了，路上不方便说。", "我在开车，先不聊了。", "路上不方便，回头再说。"), "开车结束", False, "accepted", 0, 0
        if profile == "course_non_owner":
            if "已请非负责人转达" in said and "已说明发布页升级" in said:
                return self._variant_text(memory_state, "好，我让负责人看一下。", "行，我转给负责人。", "可以，我帮你带给负责人。"), "接受转达", False, "accepted", -1, 1
            return self._variant_text(memory_state, "我不是负责人，你用一句话说重点。", "我不是负责人，简单说我转达。", "负责人不在，你说重点。"), "要求转达重点", True, "in_progress", 0, -1
        if profile == "course_busy":
            if self._has_any(last_assistant, ["1分钟", "说重点"]):
                return self._variant_text(memory_state, "那你说重点。", "行，直接说重点。", "先讲最重要的。"), "要求继续简短", True, "in_progress", 0, 0
            if "已说明发布页升级" in said or "已说明标准直播/低延迟直播区别" in said:
                return self._variant_text(memory_state, "行，我知道了，有空再看。", "知道了，我晚点看一下。", "可以，我忙完再处理。"), "接受简短说明", False, "accepted", -1, 1
            return self._variant_text(memory_state, "我现在很忙，你就 1 分钟说重点。", "我在忙，你长话短说。", "没太多时间，直接说重点。"), "要求简短", True, "in_progress", 1, -1
        if profile in {"course_owner", "course_repeated"}:
            if "已说明第三方系统路径" in said or "已说明 Web 控制台路径" in said:
                return self._variant_text(memory_state, "好，我让负责人看一下。", "行，我按这个路径去看。", "知道了，我回头照着试。"), "接受路径说明", False, "accepted", -1, 1
            if "已询问发布方式" in said:
                return self._variant_text(memory_state, "我们用第三方系统，看不到选项。", "我们不是 Web，是第三方系统。", "我这边第三方里没看到。"), "说明第三方系统", True, "in_progress", 0, 0
            if "已说明标准直播/低延迟直播区别" in said:
                return self._variant_text(memory_state, "那具体在哪里选？", "这个选项在哪配置？", "发课时从哪里切换？"), "追问配置路径", True, "in_progress", 0, 0
            return self._variant_text(memory_state, "标准直播和低延迟直播具体差多少秒？", "标准和低延迟区别是什么？", "低延迟到底好在哪？"), "追问直播区别", True, "in_progress", 0, -1
        if profile == "course_price":
            if "已拒绝优惠券承诺" in said or "已说明费用差异" in said:
                return self._variant_text(memory_state, "明白，我按页面费用看。", "知道了，费用按后台为准。", "行，优惠券不能承诺我知道。"), "接受费用说明", False, "accepted", -1, 1
            return self._variant_text(memory_state, "费用会不会更高？能给优惠券吗？", "低延迟会贵吗，有优惠吗？", "费用差多少，能不能减免？"), "追问费用优惠", True, "in_progress", 0, -1
        if profile == "course_tech":
            if "已说明第三方系统路径" in said:
                return self._variant_text(memory_state, "好，我按这个路径再查。", "可以，我照这个入口找。", "知道了，我去第三方入口看。"), "接受技术路径", False, "accepted", -1, 1
            return self._variant_text(memory_state, "我是第三方系统看不到选项，具体走什么路径？", "第三方系统里没有，怎么开通？", "我不用 Web，第三方怎么配置？"), "追问第三方路径", True, "in_progress", 0, -1
        return self._variant_text(memory_state, "那下一步在哪里配置？", "下一步要我点哪里？", "后面怎么操作？"), "追问下一步", True, "in_progress", 0, 0

    def _generic_message(self, turn_index: int) -> Tuple[str, str, bool, str, int, int]:
        if turn_index <= 2:
            return "我明白了，那下一步需要我配合什么？", "确认下一步", True, "in_progress", 0, 0
        return "好，你把结论再确认一下。", "总结确认", False, "accepted", 0, 0

    def _full_flow_ready(
        self,
        task_type: str,
        case_payload: Dict[str, Any],
        dialogue_state: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> bool:
        return self._full_flow_step_status(task_type, case_payload, messages, dialogue_state)["complete"]

    def _full_flow_followup(
        self,
        task_type: str,
        profile: str,
        dialogue_state: Dict[str, Any],
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> Tuple[str, str]:
        content, intent, *_ = self._full_flow_message(task_type, case_payload, dialogue_state, messages, memory_state)
        return content, intent
        return "先别结束，下一步还需要我配合什么？", "继续覆盖完整流程"

    def _full_flow_message(
        self,
        task_type: str,
        case_payload: Dict[str, Any],
        dialogue_state: Dict[str, Any],
        messages: List[Dict[str, Any]],
        memory_state: Dict[str, Any] | None = None,
    ) -> Tuple[str, str, bool, str, int, int]:
        status = self._full_flow_step_status(task_type, case_payload, messages, dialogue_state)
        memory_pending = (
            ((memory_state or {}).get("unfinished_items_memory") or {}).get("required_pending")
            or ((memory_state or {}).get("flow_memory") or {}).get("pending_steps")
            or []
        )
        if memory_pending:
            status = {**status, "pending_steps": list(memory_pending), "complete": False}
        pending = status["pending_steps"]
        assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in messages)
        last_assistant = str(messages[-1].get("assistant_message", "") or "") if messages else ""
        user_text = "\n".join(str(item.get("user_message", "") or "") for item in messages)
        said = set(dialogue_state.get("assistant_said_topics", []))

        if task_type == "course_platform_outbound":
            if not pending:
                return self._variant_text(memory_state, "没问题了。", "可以，没有别的问题了。", "行，我这边清楚了。"), "接受完整流程", False, "accepted", -1, 1
            if not self._has_any(assistant_text, ["直播产品升级", "产品升级", "发布页升级"]):
                return self._variant_text(memory_state, "我是负责人，你说吧。", "对，我是负责人。", "是负责人，你说。"), "确认负责人身份", True, "in_progress", 0, 0
            if self._has_any(assistant_text, ["直播产品升级", "产品升级"]) and not self._has_any(
                assistant_text,
                ["低延迟直播选项", "新增低延迟"],
            ):
                return self._variant_text(memory_state, "升级了什么？", "具体升级了什么？", "这次新增了什么？"), "追问升级内容", True, "in_progress", 0, 0
            if self._has_any(assistant_text, ["低延迟直播选项", "新增低延迟"]) and not self._has_any(
                assistant_text,
                ["分标准和低延迟", "标准和低延迟两个选项"],
            ):
                return self._variant_text(memory_state, "升级了什么？", "具体升级了什么？", "这次新增了什么？"), "追问升级内容", True, "in_progress", 0, 0
            if self._has_any(assistant_text, ["分标准和低延迟", "标准和低延迟两个选项"]) and not self._has_any(
                assistant_text,
                ["发课时选低延迟", "发课时选择低延迟"],
            ):
                return self._variant_text(memory_state, "我怎么用？", "那我要怎么用？", "发课时怎么操作？"), "追问使用方式", True, "in_progress", 0, 0
            if self._has_any(assistant_text, ["发课时选低延迟", "发课时选择低延迟"]) and not self._has_any(
                assistant_text,
                ["流程不变", "其他发课流程不变", "其他流程不变"],
            ):
                return self._variant_text(memory_state, "流程会变吗？", "其他流程变不变？", "发课流程会改吗？"), "追问流程变化", True, "in_progress", 0, 0
            step = pending[0]
            if step in {"产品升级说明", "传达升级内容"}:
                return self._variant_text(memory_state, "升级了什么？", "具体升级了什么？", "这次新增了什么？"), "追问升级内容", True, "in_progress", 0, 0
            if step == "确认是否知情":
                if self._has_any(last_assistant, ["保障质量", "您知道吗", "后台已走低延迟"]):
                    return self._course_branch_answer(case_payload, "awareness"), "回答是否知情", True, "in_progress", 0, 0
                return self._variant_text(memory_state, "好。", "嗯，知道了。", "行。"), "确认Step1完成", True, "in_progress", 0, 0
            if step == "说明标准直播和低延迟直播区别":
                if not self._has_any(assistant_text, ["5-10 秒", "5-10秒", "5到10秒"]):
                    return self._variant_text(memory_state, "区别是什么？", "标准和低延迟区别在哪？", "这两个直播区别是什么？"), "继续覆盖直播区别", True, "in_progress", 0, 0
                if "大班课" not in assistant_text:
                    return self._variant_text(memory_state, "适合什么课？", "标准适合什么课？", "场景怎么选？"), "继续覆盖标准场景", True, "in_progress", 0, 0
                if not self._has_any(assistant_text, ["1-2 秒", "1-2秒", "1到2秒"]):
                    return self._variant_text(memory_state, "低延迟呢？", "那低延迟具体强在哪？", "低延迟差多少秒？"), "继续覆盖低延迟区别", True, "in_progress", 0, 0
                if not self._has_any(assistant_text, ["小班", "实操"]):
                    return self._variant_text(memory_state, "低延迟适合什么课？", "低延迟适合哪类课？", "低延迟用在什么课？"), "继续覆盖低延迟场景", True, "in_progress", 0, 0
                return self._variant_text(memory_state, "我明白区别了。", "区别清楚了。", "这块我懂了。"), "接受直播区别", True, "in_progress", -1, 1
            if step == "说明价格差异":
                return self._variant_text(memory_state, "费用会不会更高？", "低延迟价格会贵吗？", "低延迟会不会更贵？"), "继续覆盖价格差异", True, "in_progress", 0, 0
            if step == "询问发布方式":
                return self._variant_text(memory_state, "后续从哪里发课？", "这个跟我发课入口有关吗？", "你要先确认我们怎么发布吗？"), "继续覆盖发布方式", True, "in_progress", 0, 0
            if step in {"根据发布方式给配置路径", "确认前端是否可见并说明配置路径"}:
                if self._has_any(last_assistant, ["已显示吗", "是否已显示", "页面显示了吗", "低延迟已显示吗", "显示了吗", "显示吗"]):
                    return self._course_branch_answer(case_payload, "visibility"), "回答前端是否可见", True, "in_progress", 0, 0
                if self._has_any(last_assistant, ["Web", "校务", "SaaS", "发布方式"]):
                    return self._course_branch_answer(case_payload, "publish_method"), "回答发布方式", True, "in_progress", 0, 0
                if self._has_any(last_assistant, ["进【我的】", "进入【我的】", "点直播平台管理", "选择【直播平台】"]):
                    return self._variant_text(memory_state, "到了，下一步？", "我进去了，继续说。", "找到这个入口了，然后呢？"), "等待下一步配置", True, "in_progress", 0, 0
                if self._has_any(last_assistant, ["勾选低延迟", "保存", "明天再查看"]):
                    return self._variant_text(memory_state, "继续。", "行，后面呢？", "可以，接着说。"), "接受配置路径并继续", True, "in_progress", -1, 1
                if self._has_any(last_assistant, ["直接使用", "按需选择", "明天查看", "后台配置"]):
                    return self._variant_text(memory_state, "继续。", "明白，然后呢？", "知道了，下一步？"), "接受可见性处理并继续", True, "in_progress", -1, 1
                return self._variant_text(memory_state, "第三方里看不到，怎么开？", "如果第三方没显示，怎么配置？", "第三方系统看不到的话走哪一步？"), "继续覆盖配置路径", True, "in_progress", 0, 0
            if step == "检查学员端费用/加速线路费":
                if self._has_any(last_assistant, ["附加费", "学员端", "直播线路"]):
                    return self._course_branch_answer(case_payload, "fee"), "回答费用设置情况", True, "in_progress", 0, 0
                if self._has_any(last_assistant, ["教务/财务设置", "收费规则", "保存"]):
                    return self._variant_text(memory_state, "继续。", "行，费用这块明白了。", "可以，后面呢？"), "接受费用配置并继续", True, "in_progress", 0, 0
                return self._variant_text(memory_state, "继续。", "学员端费用也要看吗？", "那费用设置要确认吗？"), "等待费用检查", True, "in_progress", 0, 0
            if step == "企业微信添加":
                if self._has_any(last_assistant, ["当前号码能加吗", "号码能加吗"]):
                    return self._course_branch_answer(case_payload, "wechat"), "回答企业微信号码状态", True, "in_progress", 0, 0
                if self._has_any(last_assistant, ["手机号"]):
                    return self._variant_text(memory_state, "我给可添加手机号。", "可以，我换个能加的号码。", "那我提供另一个手机号。"), "提供可添加手机号", True, "in_progress", 0, 0
                return self._variant_text(memory_state, "继续。", "后续怎么联系？", "企业微信这块怎么处理？"), "等待企业微信安排", True, "in_progress", 0, 0
            if step == "结束确认":
                return self._variant_text(memory_state, "没问题了。", "清楚了，先这样。", "可以，没有别的问题。"), "接受完整流程", False, "accepted", -1, 1
            return self._variant_text(memory_state, "下一步怎么做？", "接下来我要配合什么？", "后面还需要我做什么？"), "继续覆盖全流程", True, "in_progress", 0, 0

        if task_type == "rider_outbound":
            if not pending or set(pending) <= {"结束确认"}:
                optional_branch = self._rider_full_flow_optional_branch(memory_state, said, user_text)
                if optional_branch:
                    return optional_branch
                return self._variant_text(memory_state, "明白，今天我按要求跑。", "行，我今天按规则跑。", "知道了，我尽量完成要求。"), "接受完整流程", False, "accepted", -1, 1
            if "已询问是否开始配送" in said and not self._has_any(
                user_text,
                ["可以，我今天能跑", "可以，今天我会跑", "能跑", "可以上线", "马上上线", "晚上跑", "不想跑", "不一定"],
            ):
                return self._variant_text(memory_state, "可以，我今天能跑。", "可以，今天我会跑。", "能跑，我今天可以上线。"), "愿意开始配送", True, "in_progress", 0, 0
            step = pending[0]
            if step in {"告知合同生效", "告知今天飞毛腿合同已生效", "告知合同签署并询问是否开跑"}:
                return self._variant_text(memory_state, "你先说今天合同现在是什么状态。", "先确认下，合同今天生效了吗？", "我先问下合同是不是已经生效？"), "继续覆盖合同生效", True, "in_progress", 0, 0
            if step in {"询问是否开始配送", "询问是否可以开始配送", "告知合同签署并询问是否开跑"}:
                return self._variant_text(memory_state, "那今天需要我开始配送吗？", "所以今天就要开始跑吗？", "那我现在要上线配送吗？"), "继续覆盖开始配送", True, "in_progress", 0, 0
            if step in {"说明午晚高峰上线和单量要求", "说明午晚高峰和单量要求"}:
                return self._variant_text(memory_state, "那今天具体有什么要求？", "高峰和单量具体怎么算？", "今天要跑几个单、什么时间跑？"), "继续覆盖高峰和单量", True, "in_progress", 0, 0
            if step == "说明连续配送和未完成影响":
                if not self._has_any(user_text, ["连续 Y 天", "连续配送", "为什么要连续"]):
                    return self._variant_text(memory_state, "为什么要连续 Y 天？", "多日合同是不是每天都要完成？", "连续配送这个要求怎么算？"), "追问连续配送要求", True, "in_progress", 0, 0
                return self._variant_text(memory_state, "如果不完成会怎样？", "没完成会影响合同吗？", "少跑了会不会影响派单？"), "追问未完成影响", True, "in_progress", 0, 0
            if step in {"鼓励配送并安全收口", "挽留鼓励和安全提醒"}:
                return self._variant_text(memory_state, "好，我今天按要求跑。", "行，我尽量完成。", "明白，我会按要求上线。"), "等待站长安全提醒", True, "in_progress", 0, 0
            if step == "根据骑手态度鼓励挽留或安抚":
                return self._variant_text(memory_state, "我能跑，你简单说下就行。", "我可以跑，你说下重点就行。", "能配送，你继续说。"), "继续覆盖态度回应", True, "in_progress", 0, 0
            if step == "提醒注意安全":
                return self._variant_text(memory_state, "好，我今天按要求跑。", "行，我尽量完成。", "明白，我会按要求上线。"), "等待站长安全提醒", True, "in_progress", 0, 0
            if step == "说明排名与保资格规则":
                if not self._has_any(user_text, ["名额", "资格", "排名", "站长"]):
                    return self._variant_text(memory_state, "那飞毛腿名额是你们站长定的吗？", "名额按系统排还是站长排？", "飞毛腿名额站长能不能调整？"), "追问排名保资格规则", True, "in_progress", 0, 0
                return self._variant_text(memory_state, "怎么才能保住飞毛腿资格？", "那怎样更稳地保住资格？", "少拒单取消超时有用吗？"), "追问保资格规则", True, "in_progress", 0, 0
            if step == "处理超出职责问题":
                return self._variant_text(memory_state, "平台算法怎么算，为什么我派单少？", "系统派单逻辑你能解释吗？", "为什么我最近单量比别人少？"), "追问职责外问题", True, "in_progress", 0, 0
            if step == "结束确认":
                return self._variant_text(memory_state, "好，我明白了，今天按要求跑。", "行，我知道了，今天尽量跑。", "明白，今天按要求上线。"), "接受完整流程", False, "accepted", -1, 1
            return self._variant_text(memory_state, "继续说下一步。", "还有什么要注意？", "你接着说要求。"), "继续覆盖全流程", True, "in_progress", 0, 0

        if not pending:
            return self._variant_text(memory_state, "好，我知道了。", "行，我清楚了。", "可以，先这样。"), "接受完整流程", False, "accepted", -1, 1
        return self._variant_text(memory_state, "下一步是什么？", "后面怎么做？", "还需要我配合什么？"), "继续覆盖完整流程", True, "in_progress", 0, 0

    def _rider_full_flow_optional_branch(
        self,
        memory_state: Dict[str, Any] | None,
        said: set[str],
        user_text: str,
    ) -> Tuple[str, str, bool, str, int, int] | None:
        branch_id = self._variant_index(memory_state, 3)
        if branch_id == 1 and "已说明奖励规则" not in said and not self._has_any(user_text, ["奖励", "激励", "补贴", "加钱"]):
            return self._variant_text(
                memory_state,
                "连续跑完会有激励吗？",
                "连续完成有没有额外奖励？",
                "多日都跑满会多给奖励吗？",
            ), "追问奖励规则", True, "in_progress", 0, 0
        if branch_id == 2 and "已说明退出流程" not in said and not self._has_any(user_text, ["退出", "取消", "不参加", "飞毛腿报名"]):
            return self._variant_text(
                memory_state,
                "如果以后不参加，在哪里取消？",
                "后面不想参加了，怎么取消？",
                "飞毛腿报名以后能退吗？",
            ), "追问退出流程", True, "in_progress", 0, 0
        return None

    def _full_flow_step_status(
        self,
        task_type: str,
        case_payload: Dict[str, Any],
        messages: List[Dict[str, Any]],
        dialogue_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        expected_steps = self._expected_steps(task_type, case_payload)
        assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in messages)
        user_text = "\n".join(str(item.get("user_message", "") or "") for item in messages)
        said = set(dialogue_state.get("assistant_said_topics", []))
        steps = {step: self._full_flow_step_done(task_type, step, user_text, assistant_text, said) for step in expected_steps}
        pending = [step for step, done in steps.items() if not done]
        return {"steps": steps, "pending_steps": pending, "complete": not pending}

    def _course_branch_answer(self, case_payload: Dict[str, Any], branch: str) -> str:
        text = self._joined(
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("expected_goals", []),
            case_payload.get("trigger_conditions", []),
            case_payload.get("user_behavior_type", ""),
        )
        if branch == "awareness":
            if self._has_any(text, ["已知情", "知道后台", "知道低延迟"]):
                return "知道。"
            return "不知道。"
        if branch == "publish_method":
            if self._has_any(text, ["Web控制台", "Web 控制台"]):
                return "Web控制台。"
            if self._has_any(text, ["校务系统A", "校务 A"]):
                return "校务系统A。"
            return "SaaS系统B。"
        if branch == "visibility":
            if self._has_any(text, ["已显示", "能看到"]):
                return "已显示。"
            return "没显示。"
        if branch == "fee":
            if self._has_any(text, ["未设置费用", "没设置费用"]):
                return "没设置费用。"
            if self._has_any(text, ["不会配置", "无法自行配置"]):
                return "我不会配置。"
            return "已设置费用。"
        if branch == "wechat":
            if self._has_any(text, ["不可添加", "加不了", "不能加"]):
                return "这个号加不了。"
            return "当前号码能加。"
        return "知道。"

    def _expected_steps(self, task_type: str, case_payload: Dict[str, Any]) -> List[str]:
        configured = [str(item).strip() for item in case_payload.get("expected_steps", []) or [] if str(item).strip()]
        if task_type == "rider_outbound":
            return rider_full_flow_expected_steps(configured, case_payload)
        if task_type == "course_platform_outbound":
            return course_full_flow_expected_steps(configured, case_payload)
        if configured:
            return configured
        return ["说明目的", "推进下一步", "结束确认"]

    def _full_flow_step_done(
        self,
        task_type: str,
        step: str,
        user_text: str,
        assistant_text: str,
        said: set[str],
    ) -> bool:
        combined = f"{user_text}\n{assistant_text}"
        if task_type == "course_platform_outbound":
            return course_full_flow_step_done(step, user_text, assistant_text, said)
        if task_type == "rider_outbound":
            checks = {
                "确认身份": self._has_any(combined, ["本人", "骑手", "站长", "请问"]),
                "告知合同生效": self._has_any(assistant_text, ["合同已生效", "合同今天已生效", "飞毛腿合同已生效"]),
                "告知今天飞毛腿合同已生效": self._has_any(assistant_text, ["合同已签署", "签署并生效", "合同已生效", "飞毛腿合同已生效"]),
                "告知合同签署并询问是否开跑": self._has_any(assistant_text, ["合同已签署", "签署并生效", "合同已生效"]) and self._has_any(assistant_text, ["开始配送", "可以开始配送", "是否可以"]),
                "说明午晚高峰上线和单量要求": self._has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and self._has_any(assistant_text, ["X 单", "X单"]) and self._has_any(assistant_text, ["Y 单", "Y单"]),
                "说明午晚高峰和单量要求": self._has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and self._has_any(assistant_text, ["X 单", "X单"]) and self._has_any(assistant_text, ["Y 单", "Y单"]),
                "询问是否开始配送": self._has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送"]) or self._has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
                "询问是否可以开始配送": self._has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送", "是否可以"]) or self._has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
                "鼓励配送并安全收口": self._has_any(assistant_text, ["拒单", "取消", "超时"]) and self._has_any(assistant_text, ["安全", "注意"]),
                "说明连续配送和未完成影响": self._has_any(assistant_text, ["连续 Y 天", "连续", "Y 天", "Y天"]) and self._has_any(assistant_text, ["影响后续合同", "影响合同", "影响派单", "名额"]),
                "挽留鼓励和安全提醒": self._has_any(assistant_text, ["尽量", "少拒单", "少取消", "别超时"]) and self._has_any(assistant_text, ["安全", "注意"]),
                "根据骑手态度鼓励挽留或安抚": self._has_any(assistant_text, ["尽量", "建议", "理解", "辛苦", "名额", "高峰"]),
                "提醒注意安全": self._has_any(assistant_text, ["安全", "注意"]),
                "回答退出规则": self._has_any(assistant_text, ["前一天", "Z 点", "App", "飞毛腿报名", "次日生效"]),
                "回答奖励规则": self._has_any(assistant_text, ["连续 W 天", "W 天", "W天", "+$"]) and self._has_any(assistant_text, ["额外奖励", "激励"]),
                "说明排名与保资格规则": rider_rank_qualification_done(assistant_text),
                "处理超出职责问题": self._has_any(assistant_text, ["同事确认", "再回电", "能回答的先回答"]),
                "结束确认": self._has_any(user_text, ["明白", "按要求", "按规则", "知道了", "尽量完成", "会按要求"]) and self._has_any(assistant_text, ["好的", "注意安全", "先这样", "辛苦", "后续有问题", "再联系"]),
            }
            return bool(checks.get(step, False))
        return bool(assistant_text.strip())

    def _follow_unanswered(
        self,
        task_type: str,
        profile: str,
    ) -> Tuple[str, str, bool, str, int, int]:
        if task_type == "rider_outbound":
            questions = {
                "rider_weather": "你还没说安全问题，下雨这么大能不能先不跑？",
                "rider_reject": "我问的是不跑会怎么影响合同和派单。",
                "rider_rank": "你还没解释排名是不是站长能干预。",
                "rider_exit": "你还没说怎么退出飞毛腿。",
                "rider_reward": "你还没说奖励规则，别编具体金额。",
                "rider_hesitant": "你还没说不跑会不会影响名额。",
                "rider_out_of_scope": "这个超出你职责的话，你确认后回我。",
                "rider_repeated": "你直接回答，没完成 X 单会不会影响派单？",
            }
            return questions.get(profile, "你还没说清楚今天到底要完成多少单。"), "继续追问未回答问题", True, "in_progress", 1, -1
        if task_type == "course_platform_outbound":
            questions = {
                "course_driver": "我在开车，别继续说了，稍后再打。",
                "course_non_owner": "我不是负责人，你一句话说重点方便我转达。",
                "course_busy": "你说重点，不要展开。",
                "course_repeated": "你直接说标准直播和低延迟直播的区别。",
                "course_price": "你还没说费用和优惠券怎么处理。",
                "course_tech": "我问的是第三方系统看不到选项怎么办。",
            }
            should_continue = profile != "course_driver"
            return questions.get(profile, "你还没说下一步怎么配置。"), "继续追问未回答问题", should_continue, "in_progress", 1, -1
        return "你还没回答我的问题，直接说结论。", "继续追问未回答问题", True, "in_progress", 1, -1

    def _repeat_reaction(
        self,
        task_type: str,
        profile: str,
        state: SimulatedUserState,
    ) -> Tuple[str, str, bool, str, int, int]:
        if state.patience <= 2:
            return "你一直重复，我先不继续了。", "因机械重复结束", False, "rejected", 1, -1
        if task_type == "rider_outbound":
            return "你刚才说过了，资格怎么保？", "指出重复并追问", True, "in_progress", 1, -1
        if task_type == "course_platform_outbound":
            return "你刚才有点重复，我要的是下一步怎么配置。", "指出重复并追问", True, "in_progress", 1, -1
        return "你刚才重复了，换个说法直接回答。", "指出重复并追问", True, "in_progress", 1, -1

    def _answered_current_need(
        self,
        task_type: str,
        profile: str,
        dialogue_state: Dict[str, Any],
        last_assistant: str,
    ) -> bool:
        if not last_assistant:
            return True
        said = set(dialogue_state.get("assistant_said_topics", []))
        if task_type == "rider_outbound":
            asked = set(dialogue_state.get("user_asked_topics", []))
            if profile == "rider_weather" and "天气太差怎么办" not in asked:
                return True
            if profile == "rider_reject" and "是否能不配送" not in asked:
                return True
            if profile == "rider_rank" and "为什么排名不对" not in asked:
                return True
            if profile == "rider_exit" and "怎么退出飞毛腿" not in asked:
                return True
            if profile == "rider_reward" and "奖励补贴" not in asked:
                return True
            if profile == "rider_out_of_scope" and "职责外问题" not in asked:
                return True
            if profile == "rider_hesitant" and "犹豫配送" not in asked:
                return True
            if profile == "rider_repeated" and "不完成有什么影响" not in asked:
                return True
            checks = {
                "rider_weather": bool({"已提醒安全", "已说明天气资格"} & said),
                "rider_reject": "已说明合同和派单影响" in said or "已安抚无法配送" in said,
                "rider_rank": "已说明排名与保资格规则" in said,
                "rider_exit": "已说明退出流程" in said,
                "rider_reward": "已说明奖励规则" in said,
                "rider_hesitant": "已说明名额紧张" in said or "已说明合同和派单影响" in said,
                "rider_out_of_scope": "已说明超出范围回电" in said,
                "rider_repeated": "已说明合同和派单影响" in said or "已说明 X 单/Y 单" in said,
                "rider_willing": bool({"已说明合同已生效", "已说明 X 单/Y 单"} & said),
            }
            return checks.get(profile, True)
        if task_type == "course_platform_outbound":
            checks = {
                "course_driver": self._has_any(last_assistant, ["稍后", "再打", "注意安全"]),
                "course_non_owner": bool({"已请非负责人转达", "已说明发布页升级"} & said),
                "course_busy": bool({"已说明发布页升级", "已说明标准直播/低延迟直播区别"} & said)
                or self._has_any(last_assistant, ["1 分钟", "简短"]),
                "course_repeated": bool({"已说明标准直播/低延迟直播区别", "已询问发布方式", "已说明第三方系统路径"} & said),
                "course_price": bool({"已拒绝优惠券承诺", "已说明费用差异"} & said),
                "course_tech": bool({"已说明第三方系统路径", "已询问发布方式"} & said),
                "course_owner": bool({"已说明发布页升级", "已说明标准直播/低延迟直播区别"} & said),
            }
            return checks.get(profile, True)
        return True

    def _profile_kind(self, task_type: str, case_payload: Dict[str, Any]) -> str:
        text = self._joined(
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("expected_goals", []),
            case_payload.get("required_rules", []),
            case_payload.get("forbidden_rules", []),
            case_payload.get("trigger_conditions", []),
            case_payload.get("expected_final_state", ""),
            case_payload.get("user_behavior_type", ""),
        )
        if task_type == "rider_outbound":
            if case_payload.get("case_mode") == "full_flow" or self._has_any(text, ["递进式完整流程", "综合骑手", "完整覆盖飞毛腿递进式外呼流程"]):
                return "rider_full_flow"
            if self._has_any(text, ["超范围", "职责外", "平台算法", "派单少", "补贴多久到账", "工资", "保险", "工伤", "赔偿"]):
                return "rider_out_of_scope"
            if self._has_any(text, ["退出", "怎么取消", "取消飞毛腿", "取消报名", "飞毛腿报名"]):
                return "rider_exit"
            if self._has_any(text, ["奖励", "补贴", "额外奖励", "加钱", "W 天"]):
                return "rider_reward"
            if self._has_any(text, ["排名", "排不上", "质疑"]):
                return "rider_rank"
            if self._has_any(text, ["恶劣天气", "下雨", "雨", "天气", "抱怨", "不满"]):
                return "rider_weather"
            if self._has_any(text, ["犹豫", "不一定", "看看情况", "有点忙", "不确定"]):
                return "rider_hesitant"
            if self._has_any(text, ["反复追问", "没完成", "X 单", "影响"]):
                return "rider_repeated"
            if self._has_any(text, ["不想干", "不干", "不想配送", "不想跑", "拒绝", "无法配送"]):
                return "rider_reject"
            return "rider_willing"
        if task_type == "course_platform_outbound":
            if case_payload.get("case_mode") == "full_flow" or self._has_any(text, ["强渐进", "完整流程", "主流程"]):
                return "course_full_flow"
            if self._has_any(text, ["开车", "正在开车"]):
                return "course_driver"
            if self._has_any(text, ["非负责人", "前台", "不是负责人"]):
                return "course_non_owner"
            if self._has_any(text, ["忙", "没时间"]):
                return "course_busy"
            if self._has_any(text, ["追问直播区别", "反复追问", "区别", "标准直播", "低延迟"]):
                return "course_repeated"
            if self._has_any(text, ["第三方", "看不到", "技术不熟悉", "配置"]):
                return "course_tech"
            if self._has_any(text, ["优惠券", "价格", "费用"]):
                return "course_price"
            return "course_owner"
        return "normal"

    def _task_type(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
        task_type = (task_payload.get("task_type") or "").strip()
        if task_type:
            return task_type
        text = self._joined(
            task_payload.get("instruction_text", ""),
            task_payload.get("task_text", ""),
            task_payload.get("name", ""),
            case_payload.get("name", ""),
            case_payload.get("initial_message", ""),
        )
        if self._has_any(text, ["飞毛腿", "骑手", "配送", "派单"]):
            return "rider_outbound"
        if self._has_any(text, ["课程", "直播", "低延迟", "机构", "负责人"]):
            return "course_platform_outbound"
        return "generic_outbound"

    def _pack(
        self,
        content: str,
        state: SimulatedUserState,
        should_continue: bool,
        metadata_extra: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        metadata = {
            "intent": state.current_intent,
            "emotion_level": state.emotion_level,
            "patience": state.patience,
            "should_continue": should_continue,
            "branch_update": {},
        }
        metadata.update(metadata_extra or {})
        return {
            "content": content,
            "intent": state.current_intent,
            "user_state": asdict(state),
            "should_continue": should_continue,
            "metadata": metadata,
        }

    def _course_current_step(self, memory_state: Dict[str, Any] | None) -> str:
        if not isinstance(memory_state, dict):
            return "identity_check"
        explicit = str(memory_state.get("current_step") or "").strip()
        if explicit:
            return explicit
        flow = memory_state.get("flow_memory") or {}
        stage = str(flow.get("current_stage") or "").strip()
        mapping = {
            "opening": "identity_check",
            "identity_check": "identity_check",
            "owner": "awareness_check",
            "upgrade_intro": "upgrade_intro",
            "awareness_check": "awareness_check",
            "live_difference": "difference_explain",
            "config_path": "publish_method_check",
            "web_path": "publish_method_check",
            "third_party_path": "configuration_guidance",
            "visibility_check": "configuration_guidance",
            "fee": "fee_check",
            "coupon": "fee_check",
            "enterprise_wechat": "wecom_check",
            "accepted": "closing",
        }
        if stage in mapping:
            return mapping[stage]
        unfinished = memory_state.get("unfinished_memory") or memory_state.get("unfinished_items_memory") or {}
        next_step = str(unfinished.get("next_best_action") or unfinished.get("next_suggested_step") or "")
        return self._map_business_step_to_policy_step(next_step)

    def _map_business_step_to_policy_step(self, step: str) -> str:
        if self._has_any(step, ["身份", "负责人"]):
            return "identity_check"
        if self._has_any(step, ["知情"]):
            return "awareness_check"
        if self._has_any(step, ["升级", "传达"]):
            return "option_intro"
        if self._has_any(step, ["区别", "价格差异"]):
            return "difference_explain"
        if self._has_any(step, ["发布方式"]):
            return "publish_method_check"
        if self._has_any(step, ["配置路径", "前端是否可见"]):
            return "configuration_guidance"
        if self._has_any(step, ["费用", "附加费", "加速"]):
            return "fee_check"
        if self._has_any(step, ["企业微信"]):
            return "wecom_check"
        if self._has_any(step, ["结束"]):
            return "closing"
        return "identity_check"

    def _available_events_for_step(self, current_step: str) -> set[str]:
        base = {"normal", "ask_question", "interrupt", "confused", "busy", "driving"}
        by_step = {
            "identity_check": {"normal", "busy", "driving", "confused"},
            "upgrade_intro": base,
            "awareness_check": base | {"price_sensitive"},
            "option_intro": base,
            "difference_explain": base | {"price_sensitive"},
            "publish_method_check": base | {"technical_issue"},
            "configuration_guidance": base | {"technical_issue"},
            "fee_check": base | {"price_sensitive"},
            "wecom_check": base | {"technical_issue"},
            "closing": {"normal", "ask_question", "price_sensitive"},
        }
        return by_step.get(current_step, base)

    def _event_seed(
        self,
        memory_state: Dict[str, Any] | None,
        case: Dict[str, Any],
        turn_index: int,
    ) -> int:
        context = (memory_state or {}).get("run_context") if isinstance(memory_state, dict) else {}
        raw_seed = 0
        if isinstance(context, dict):
            try:
                raw_seed = int(context.get("run_seed") or context.get("variant_id") or 0)
            except (TypeError, ValueError):
                raw_seed = 0
        case_id = int(case.get("id") or 0) if isinstance(case, dict) else 0
        stable_text = self._joined(case.get("name", ""), case.get("user_profile", "")) if isinstance(case, dict) else ""
        text_value = sum(ord(char) for char in stable_text)
        return raw_seed * 1009 + case_id * 97 + int(turn_index) * 17 + text_value

    def _initial_response(
        self,
        task_type: str,
        profile: str,
        case_mode: str,
        case_payload: Dict[str, Any],
    ) -> str:
        content = str(case_payload.get("initial_message") or self._default_initial(task_type, profile)).strip()
        if task_type == "rider_outbound":
            text = self._joined(
                case_payload.get("name", ""),
                case_payload.get("user_profile", ""),
                case_payload.get("initial_message", ""),
                case_payload.get("user_behavior_type", ""),
            )
            if self._has_any(text, ["不是本人", "号码错误", "打错", "非本人"]):
                return "不是，你打错了。"
            return content or "是我，你说。"
        return content

    def _default_initial(self, task_type: str, profile: str) -> str:
        if task_type == "rider_outbound":
            defaults = {
                "rider_reject": "我今天不想跑了，能不能不送？",
                "rider_weather": "今天下雨这么大，怎么还让我跑？",
                "rider_rank": "为什么别人能报上，我排不上？",
                "rider_repeated": "如果我今天没完成 X 单会怎么样？",
                "rider_exit": "我想退出飞毛腿，怎么取消？",
                "rider_reward": "连续跑完会有奖励或补贴吗？",
                "rider_hesitant": "我不一定，今天有点忙。",
                "rider_out_of_scope": "平台算法怎么算，为什么我派单少？",
            }
            return defaults.get(profile, "是我，你说。")
        if task_type == "course_platform_outbound":
            defaults = {
                "course_non_owner": "我不是负责人，我只是前台。",
                "course_busy": "我现在很忙，没时间听。",
                "course_driver": "我在开车，不方便说。",
                "course_repeated": "标准直播和低延迟直播有什么区别？",
                "course_price": "你们能不能给我优惠券？",
                "course_tech": "我第三方系统里看不到低延迟直播选项。",
            }
            return defaults.get(profile, "我是负责人，你说吧。")
        return "您好，可以简单说一下。"

    def _closing_user_message(self, task_type: str, profile: str) -> str:
        if task_type == "rider_outbound":
            return "好，我注意安全。"
        if profile == "course_driver":
            return "好，稍后联系。"
        return "好，我让负责人看一下。"

    def _assistant_closes(self, text: str) -> bool:
        return self._has_any(text, ["稍后再打", "祝课程顺利", "后续可再联系", "后续有问题再联系"])

    def _assistant_repeated(self, messages: List[Dict[str, Any]]) -> bool:
        assistant_replies = [str(item.get("assistant_message", "") or "") for item in messages if item.get("assistant_message")]
        if len(assistant_replies) < 2:
            return False
        return is_similar_text(assistant_replies[-1], assistant_replies[-2])

    def _reply_too_long(
        self,
        task_type: str,
        text: str,
        state: SimulatedUserState | None,
    ) -> bool:
        if not text:
            return False
        limit = 90 if task_type == "rider_outbound" else 42
        if state and state.patience <= 2:
            limit -= 15
        return len(text) > limit

    def _info_completeness(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        task_type: str,
        profile: str,
    ) -> str:
        text = self._joined(
            task_payload.get("instruction_text", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("expected_goals", []),
        )
        if profile in {"course_non_owner", "course_driver", "rider_reject"}:
            return "missing"
        if profile in {"course_busy", "rider_weather", "course_tech", "course_price"}:
            return "unclear"
        required = {
            "rider_outbound": ["合同", "配送"],
            "course_platform_outbound": ["直播", "负责人"],
        }.get(task_type, [])
        if not required:
            return "unclear"
        hits = sum(1 for keyword in required if keyword in text)
        if hits >= len(required):
            return "complete"
        if hits:
            return "unclear"
        return "missing"

    def _base_emotion(self, profile: str, difficulty: str) -> int:
        value = {
            "rider_willing": 2,
            "rider_reject": 3,
            "rider_weather": 4,
            "rider_rank": 3,
            "rider_repeated": 3,
            "rider_exit": 2,
            "rider_reward": 2,
            "rider_hesitant": 3,
            "rider_out_of_scope": 3,
            "rider_full_flow": 3,
            "course_owner": 2,
            "course_non_owner": 2,
            "course_busy": 3,
            "course_driver": 3,
            "course_repeated": 3,
            "course_price": 3,
            "course_tech": 2,
        }.get(profile, 2)
        if difficulty == "困难":
            value += 1
        elif difficulty == "简单":
            value -= 1
        return self._clamp(value)

    def _base_patience(self, profile: str, difficulty: str) -> int:
        value = {
            "rider_willing": 5,
            "rider_reject": 3,
            "rider_weather": 3,
            "rider_rank": 3,
            "rider_repeated": 3,
            "rider_exit": 4,
            "rider_reward": 4,
            "rider_hesitant": 3,
            "rider_out_of_scope": 3,
            "rider_full_flow": 4,
            "course_owner": 5,
            "course_non_owner": 3,
            "course_busy": 2,
            "course_driver": 1,
            "course_repeated": 3,
            "course_price": 3,
            "course_tech": 4,
        }.get(profile, 4)
        if difficulty == "困难":
            value -= 1
        elif difficulty == "简单":
            value += 1
        return self._clamp(value)

    def _persona_label(self, task_type: str, profile: str) -> str:
        labels = {
            "rider_willing": "愿意配送骑手",
            "rider_reject": "不想配送骑手",
            "rider_weather": "抱怨恶劣天气骑手",
            "rider_rank": "质疑排名骑手",
            "rider_repeated": "追问合同影响骑手",
            "rider_exit": "咨询退出流程骑手",
            "rider_reward": "关注奖励骑手",
            "rider_hesitant": "犹豫配送骑手",
            "rider_out_of_scope": "咨询职责外问题骑手",
            "rider_full_flow": "递进式综合骑手",
            "course_owner": "课程机构负责人",
            "course_non_owner": "非负责人",
            "course_busy": "忙碌商家",
            "course_driver": "开车商家",
            "course_repeated": "追问直播区别商家",
            "course_price": "价格敏感商家",
            "course_tech": "技术不熟悉商家",
            "course_full_flow": "课程机构负责人",
        }
        return labels.get(profile, "通用外呼对象")

    def _user_alternatives(self, task_type: str, profile: str) -> List[str]:
        if task_type == "rider_outbound":
            return [
                "你换个说法，直接回答我会不会影响合同和派单。",
                "那我今天尽量跑。",
                "如果真跑不了，你帮我记录。",
                "好，我注意安全。",
            ]
        if task_type == "course_platform_outbound":
            if profile == "course_full_flow":
                return [
                    "收到，继续。",
                    "可以，继续。",
                    "我明白了。",
                    "你接着说。",
                ]
            return [
                "那具体在哪里选？",
                "你说重点，下一步怎么配置？",
                "费用会不会更高？",
                "好，我让负责人看一下。",
            ]
        return ["那下一步是什么？", "你说重点。", "好，我知道了。"]

    def _variant_text(self, memory_state: Dict[str, Any] | None, *options: str) -> str:
        clean = [item for item in options if item]
        if not clean:
            return ""
        return clean[self._variant_index(memory_state, len(clean))]

    def _variant_index(self, memory_state: Dict[str, Any] | None, modulo: int) -> int:
        if modulo <= 1:
            return 0
        context = (memory_state or {}).get("run_context") or {}
        raw_value = context.get("variant_id", context.get("run_seed", 0))
        try:
            value = int(raw_value or 0)
        except (TypeError, ValueError):
            value = 0
        return value % modulo

    def _joined(self, *values: Any) -> str:
        parts: List[str] = []
        for value in values:
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            elif isinstance(value, dict):
                parts.append(str(value))
            elif value is not None:
                parts.append(str(value))
        return " ".join(parts)

    def _has_any(self, text: str, keywords: List[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)

    def _clamp(self, value: int) -> int:
        return max(1, min(5, value))
