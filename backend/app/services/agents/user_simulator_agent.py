from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, List, Tuple

from app.services.dialogue_state import analyze_dialogue_state, is_similar_text


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
    ) -> Dict[str, Any]:
        task_type = self._task_type(task_payload, case_payload)
        profile = self._profile_kind(task_type, case_payload)
        base_state = self._build_user_state(task_payload, case_payload, messages, turn_index, task_type, profile)

        if turn_index <= 1:
            content = case_payload.get("initial_message") or self._default_initial(task_type, profile)
            return self._pack(content, replace(base_state, current_intent="初始回应"), True)

        dialogue_state = analyze_dialogue_state(task_payload, case_payload, messages)
        last_assistant = dialogue_state.get("last_assistant_message", "")
        risk = self._detect_risk(task_type, profile, last_assistant, messages)

        if risk:
            content, intent, should_continue, progress, emotion_delta, patience_delta = risk
        elif self._assistant_closes(last_assistant):
            content, intent, should_continue, progress, emotion_delta, patience_delta = (
                self._closing_user_message(task_type, profile),
                "接受并结束",
                False,
                "accepted",
                -1,
                1,
            )
        elif self._reply_too_long(task_type, last_assistant, base_state):
            content, intent, should_continue, progress, emotion_delta, patience_delta = (
                "你说重点，我现在没时间听太长。",
                "打断冗长回复",
                True,
                "in_progress",
                1,
                -1,
            )
        elif self._assistant_repeated(messages):
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
        elif task_type == "rider_outbound":
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._rider_message(
                profile,
                dialogue_state,
            )
        elif task_type == "course_platform_outbound":
            content, intent, should_continue, progress, emotion_delta, patience_delta = self._course_message(
                profile,
                dialogue_state,
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
        content = self.deduplicate_user_message(content, messages, asdict(state)).strip()
        if not should_continue:
            state = replace(state, goal_progress=progress if progress in {"accepted", "rejected"} else "accepted")
        return self._pack(content, state, should_continue)

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
        forbidden_hits = self._has_any(
            last_assistant,
            ["订单号", "退款", "手机号后四位", "酒店", "核销", "团购券"],
        )
        if forbidden_hits:
            return "你说的不是我这个事情吧？先别继续了。", "识别串场后拒绝", False, "rejected", 2, -2
        return None

    def _rider_message(
        self,
        profile: str,
        dialogue_state: Dict[str, Any],
    ) -> Tuple[str, str, bool, str, int, int]:
        said = set(dialogue_state.get("assistant_said_topics", []))
        if profile == "rider_weather":
            if "已提醒安全" in said and "已说明天气资格" in said:
                return "好，我注意安全，雨小了再看能不能跑。", "接受天气和资格说明", False, "accepted", -1, 1
            if "已提醒安全" in said:
                return "那我晚点看雨小不小，别影响安全就行。", "天气态度缓和", True, "in_progress", -1, 1
            return "雨这么大，安全怎么保证？别只催我跑。", "继续追问天气安全", True, "in_progress", 1, -1
        if profile == "rider_reject":
            if "已说明合同和派单影响" in said and "已安抚无法配送" in said:
                return "如果真跑不了，你帮我记录一下。", "请求记录无法配送", False, "accepted", -1, 1
            if "已说明合同和派单影响" in said:
                return "那如果真跑不了，你们能记录吗？", "追问无法配送处理", True, "in_progress", 0, 0
            return "我今天真不想跑，不完成到底会怎样？", "表达拒绝并追问影响", True, "in_progress", 1, -1
        if profile == "rider_rank":
            if "已说明排名规则" in said:
                return "明白，只要不是人为干预就行。", "接受排名解释", False, "accepted", -1, 1
            return "为什么别人能报上我不行，是站长能调吗？", "质疑报名排名", True, "in_progress", 1, -1
        if profile == "rider_exit":
            if "已说明退出流程" in said:
                return "明白了，我去 App 报名页看看。", "接受退出流程", False, "accepted", -1, 1
            return "那到底怎么退出飞毛腿？入口在哪里？", "追问退出流程", True, "in_progress", 0, -1
        if profile == "rider_repeated":
            if "已说明合同和派单影响" in said and "已说明 X 单/Y 单" in said:
                return "那我今天尽量跑。", "接受合同影响说明", False, "accepted", -1, 1
            return "那如果今天没完成 X 单，会影响派单吗？", "追问合同影响", True, "in_progress", 0, -1
        if "已说明 X 单/Y 单" in said:
            return "好，我知道了，后面按合同要求跑。", "接受配送要求", False, "accepted", -1, 1
        if "已说明合同已生效" in said:
            return "那今天单日和多日分别要完成多少单？", "追问完成要求", True, "in_progress", 0, 0
        return "可以，我今天能跑，你先说要求。", "愿意配送", True, "in_progress", 0, 0

    def _course_message(
        self,
        profile: str,
        dialogue_state: Dict[str, Any],
    ) -> Tuple[str, str, bool, str, int, int]:
        said = set(dialogue_state.get("assistant_said_topics", []))
        if profile == "course_driver":
            return "先挂了，路上不方便说。", "开车结束", False, "accepted", 0, 0
        if profile == "course_non_owner":
            if "已请非负责人转达" in said and "已说明发布页升级" in said:
                return "好，我让负责人看一下。", "接受转达", False, "accepted", -1, 1
            return "我不是负责人，你用一句话说重点。", "要求转达重点", True, "in_progress", 0, -1
        if profile == "course_busy":
            if "已说明发布页升级" in said or "已说明标准直播/低延迟直播区别" in said:
                return "行，我知道了，有空再看。", "接受简短说明", False, "accepted", -1, 1
            return "我现在很忙，你就 1 分钟说重点。", "要求简短", True, "in_progress", 1, -1
        if profile in {"course_owner", "course_repeated"}:
            if "已说明第三方系统路径" in said or "已说明 Web 控制台路径" in said:
                return "好，我让负责人看一下。", "接受路径说明", False, "accepted", -1, 1
            if "已询问发布方式" in said:
                return "我们用第三方系统，看不到选项。", "说明第三方系统", True, "in_progress", 0, 0
            if "已说明标准直播/低延迟直播区别" in said:
                return "那具体在哪里选？", "追问配置路径", True, "in_progress", 0, 0
            return "标准直播和低延迟直播具体差多少秒？", "追问直播区别", True, "in_progress", 0, -1
        if profile == "course_price":
            if "已拒绝优惠券承诺" in said or "已说明费用差异" in said:
                return "明白，我按页面费用看。", "接受费用说明", False, "accepted", -1, 1
            return "费用会不会更高？能给优惠券吗？", "追问费用优惠", True, "in_progress", 0, -1
        if profile == "course_tech":
            if "已说明第三方系统路径" in said:
                return "好，我按这个路径再查。", "接受技术路径", False, "accepted", -1, 1
            return "我是第三方系统看不到选项，具体走什么路径？", "追问第三方路径", True, "in_progress", 0, -1
        return "那下一步在哪里配置？", "追问下一步", True, "in_progress", 0, 0

    def _generic_message(self, turn_index: int) -> Tuple[str, str, bool, str, int, int]:
        if turn_index <= 2:
            return "我明白了，那下一步需要我配合什么？", "确认下一步", True, "in_progress", 0, 0
        return "好，你把结论再确认一下。", "总结确认", False, "accepted", 0, 0

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
                "rider_repeated": "你直接回答，没完成 X 单会不会影响派单？",
            }
            return questions.get(profile, "你还没说清楚今天到底要完成多少单。"), "继续追问未回答问题", True, "in_progress", 1, -1
        if task_type == "course_platform_outbound":
            questions = {
                "course_driver": "我在开车，别继续说了，稍后再打。",
                "course_non_owner": "我不是负责人，你一句话说重点方便我转达。",
                "course_busy": "你说重点，不要展开。",
                "course_repeated": "你直接说区别和在哪里配置。",
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
            return "你刚才重复了，我要明确答案：会不会影响合同和派单？", "指出重复并追问", True, "in_progress", 1, -1
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
            checks = {
                "rider_weather": bool({"已提醒安全", "已说明天气资格"} & said),
                "rider_reject": "已说明合同和派单影响" in said or "已安抚无法配送" in said,
                "rider_rank": "已说明排名规则" in said,
                "rider_exit": "已说明退出流程" in said,
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
            if self._has_any(text, ["退出", "取消", "怎么取消"]):
                return "rider_exit"
            if self._has_any(text, ["排名", "排不上", "质疑"]):
                return "rider_rank"
            if self._has_any(text, ["恶劣天气", "下雨", "雨", "天气", "抱怨", "不满"]):
                return "rider_weather"
            if self._has_any(text, ["反复追问", "没完成", "X 单", "影响"]):
                return "rider_repeated"
            if self._has_any(text, ["不想配送", "不想跑", "拒绝", "无法配送"]):
                return "rider_reject"
            return "rider_willing"
        if task_type == "course_platform_outbound":
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

    def _pack(self, content: str, state: SimulatedUserState, should_continue: bool) -> Dict[str, Any]:
        return {
            "content": content,
            "intent": state.current_intent,
            "user_state": asdict(state),
            "should_continue": should_continue,
        }

    def _default_initial(self, task_type: str, profile: str) -> str:
        if task_type == "rider_outbound":
            defaults = {
                "rider_reject": "我今天不想跑了，能不能不送？",
                "rider_weather": "今天下雨这么大，怎么还让我跑？",
                "rider_rank": "为什么别人能报上，我排不上？",
                "rider_repeated": "如果我今天没完成 X 单会怎么样？",
                "rider_exit": "我想退出飞毛腿，怎么取消？",
            }
            return defaults.get(profile, "可以，我今天能跑。")
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
        limit = 90 if task_type == "rider_outbound" else 70
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
            "course_owner": "课程机构负责人",
            "course_non_owner": "非负责人",
            "course_busy": "忙碌商家",
            "course_driver": "开车商家",
            "course_repeated": "追问直播区别商家",
            "course_price": "价格敏感商家",
            "course_tech": "技术不熟悉商家",
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
            return [
                "那具体在哪里选？",
                "你说重点，下一步怎么配置？",
                "费用会不会更高？",
                "好，我让负责人看一下。",
            ]
        return ["那下一步是什么？", "你说重点。", "好，我知道了。"]

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
