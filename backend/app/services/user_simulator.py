from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from app.services.agents.user_simulator_agent import UserSimulatorAgent
from app.services.llm_client import LLMClient


@dataclass
class UserState:
    emotion_level: int
    patience: int
    info_completeness: str
    goal_progress: str
    interruption_count: int
    question_focus: str


class UserSimulator:
    """Outbound-call target simulator for complex instruction evaluation."""

    def __init__(self) -> None:
        self.llm_client = LLMClient()
        self.agent = UserSimulatorAgent()

    def generate_message(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_index: int,
    ) -> Dict[str, Any]:
        result = self.agent.generate_message(task_payload, case_payload, history, turn_index)

        if not self.llm_client.use_mock:
            fallback = result["content"]
            result["content"] = self.llm_client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是复杂外呼评测中的被外呼对象模拟器。请严格根据任务指令、任务类型、"
                            "测试用例、对话历史、用户状态和当前轮次，生成自然、简短且有目标的下一轮用户发言。"
                            "输出只需要用户会说的话，不要解释。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": str(
                            {
                                "task": task_payload,
                                "case": case_payload,
                                "history": history,
                                "turn_index": turn_index,
                                "user_state": result["user_state"],
                                "intent": result["intent"],
                                "should_continue": result["should_continue"],
                            }
                        ),
                    },
                ],
                fallback,
            )
            result["content"] = self.agent.deduplicate_user_message(
                result["content"],
                history,
                result.get("user_state", {}),
            )
        user_state = result.setdefault("user_state", {})
        if user_state.get("goal_progress") != "rejected" and self._user_message_closes(result.get("content", "")):
            result["should_continue"] = False
            user_state["goal_progress"] = "accepted"
        return result

    def generate_next_message(
        self,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_index: int,
    ) -> Dict[str, Any]:
        """Backward-compatible entry point for older callers."""

        return self.generate_message({}, case_payload, history, turn_index)

    def _mock_turn(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_index: int,
        state: UserState,
    ) -> Dict[str, Any]:
        if turn_index <= 1:
            return self._pack(
                case_payload.get("initial_message") or self._default_initial(task_payload, case_payload),
                state,
                self._initial_intent(task_payload, case_payload),
                True,
            )

        task_type = self._task_type(task_payload, case_payload)
        profile = self._profile_kind(task_type, case_payload)
        last_assistant = self._last_assistant(history)

        violation = self._constraint_violation(task_type, profile, case_payload, history, last_assistant)
        if violation:
            content, intent = violation
            state = replace(state, emotion_level=5, patience=1, goal_progress="rejected")
            return self._pack(content, state, intent, False)

        if self._needs_identity_confirmation(task_type, case_payload, history, last_assistant):
            state = replace(
                state,
                emotion_level=self._clamp(state.emotion_level + 1),
                patience=self._clamp(state.patience - 1),
                question_focus="身份确认",
            )
            return self._pack("你是谁？先说清楚这通电话是做什么的。", state, "确认来电身份", True)

        if self._reply_too_long(task_type, last_assistant, state):
            state = replace(
                state,
                emotion_level=self._clamp(state.emotion_level + 1),
                patience=self._clamp(state.patience - 1),
                interruption_count=state.interruption_count + 1,
            )
            return self._pack(self._interrupt_text(profile), state, "打断冗长回复", True)

        if self._assistant_repeated(history):
            state = replace(
                state,
                emotion_level=self._clamp(state.emotion_level + 1),
                patience=self._clamp(state.patience - 1),
            )
            return self._pack(
                f"你刚才这句有点重复，我要的是明确答复：{self._focus_question(task_type, profile, state.question_focus)}",
                state,
                "指出重复并继续追问",
                True,
            )

        if self._focus_unanswered(task_type, state.question_focus, last_assistant):
            state = replace(
                state,
                emotion_level=self._clamp(state.emotion_level + 1),
                patience=self._clamp(state.patience - 1),
            )
            return self._pack(
                self._follow_up_question(task_type, profile, state.question_focus),
                state,
                "继续追问未回答问题",
                True,
            )

        if task_type == "rider_outbound":
            return self._rider_turn(profile, state, case_payload, turn_index)
        if task_type == "course_platform_outbound":
            return self._course_turn(profile, state, case_payload, turn_index)
        return self._generic_turn(profile, state, case_payload, turn_index)

    def _rider_turn(
        self,
        profile: str,
        state: UserState,
        case_payload: Dict[str, Any],
        turn_index: int,
    ) -> Dict[str, Any]:
        plans = {
            "rider_willing": [
                ("那我今天能跑。你再确认下单日和多日合同分别要完成多少单？", "确认配送要求"),
                ("明白，我会注意安全。如果临时跑不了，是在 App 里取消吗？", "咨询异常处理"),
                ("好，我知道了，后面按合同要求跑。", "接受任务安排"),
            ],
            "rider_reject": [
                ("我今天真不想跑。不完成到底会影响合同还是后面派单？", "表达拒绝并追问影响"),
                ("如果我坚持跑不了，你们这边能不能先记录一下？", "确认无法配送处理"),
                ("行，那你把取消或结束通话的规则说清楚。", "要求给出收尾方案"),
            ],
            "rider_weather": [
                ("雨这么大你先说安全怎么保证，别只催我跑。", "抱怨天气并要求安抚"),
                ("如果路况不好，我是不是可以减少接单，别因为这个影响资格？", "追问安全和资格"),
                ("好，那我先看路况，安全第一。", "谨慎接受"),
            ],
            "rider_repeated": [
                ("你再说清楚点，如果今天没完成 X 单会怎么样？", "追问合同影响"),
                ("会影响明天派单吗？有没有具体时效或后续处理？", "追问后果和时效"),
                ("好，我需要的就是这个明确规则。", "接受解释"),
            ],
            "rider_rank": [
                ("为什么别人能报上我排不上，是不是站长能调？", "质疑报名排名"),
                ("那排名规则是谁定的？你不能承诺我一定有资格吧？", "确认排名规则"),
                ("明白，只要不是人为干预就行。", "接受排名解释"),
            ],
            "rider_exit": [
                ("我想退出飞毛腿，具体在哪个入口取消？", "咨询退出流程"),
                ("必须前一天指定时间前取消吗？今天还能不能退？", "追问取消条件"),
                ("好，那我去 App 飞毛腿报名里看。", "接受退出路径"),
            ],
        }
        content, intent = self._step(plans.get(profile, plans["rider_willing"]), turn_index)
        should_continue = not content.endswith("按合同要求跑。") and not content.endswith("飞毛腿报名里看。")
        next_progress = "accepted" if not should_continue else "in_progress"
        return self._pack(content, replace(state, goal_progress=next_progress), intent, should_continue)

    def _course_turn(
        self,
        profile: str,
        state: UserState,
        case_payload: Dict[str, Any],
        turn_index: int,
    ) -> Dict[str, Any]:
        plans = {
            "course_owner": [
                ("可以，你用一句话说清楚标准直播和低延迟直播的区别。", "了解直播升级"),
                ("我们现在用的是后台发布，后续配置路径在哪里？", "询问配置路径"),
                ("明白，低延迟适合互动课，我后面去配置。", "接受升级说明"),
            ],
            "course_non_owner": [
                ("我不是负责人，我只是前台。你把重点说一句，我帮你转达。", "要求转达重点"),
                ("可以，我会转给负责人，你别展开太多。", "接受转达"),
                ("好，我记下了。", "结束转达"),
            ],
            "course_busy": [
                ("我现在很忙，你就 1 分钟说重点。", "要求简短沟通"),
                ("重点是多了两个直播选项，对吧？分别适合什么课？", "确认升级重点"),
                ("行，我知道了，有空再看。", "暂时接受"),
            ],
            "course_driver": [
                ("我在开车，不方便听，你稍后再打吧。", "说明开车不便"),
                ("先挂了，路上不方便说。", "结束通话"),
                ("不用继续了，稍后联系。", "拒绝继续沟通"),
            ],
            "course_repeated": [
                ("标准直播和低延迟直播具体差多少秒？费用是不是也不一样？", "追问直播区别"),
                ("你别讲太长，我只要知道哪个适合小班互动。", "要求聚焦场景"),
                ("好，那小班课我优先看低延迟。", "接受建议"),
            ],
            "course_tech": [
                ("我第三方系统里看不到低延迟直播选项，应该从哪里找？", "询问配置路径"),
                ("如果还是看不到，是不是后台没配置，要明天再看？", "确认异常处理"),
                ("好，我按你说的路径再查。", "接受技术指引"),
            ],
            "course_price": [
                ("你们能不能给我优惠券？低延迟费用会不会更贵？", "询问价格优惠"),
                ("不能给优惠也行，那你说清楚费用规则。", "确认费用规则"),
                ("明白，我按费用和互动需求选择。", "接受费用说明"),
            ],
            "course_interrupted_followup": [
                ("刚才被打断了，你接着说重点：低延迟直播适合什么场景？", "被打断后继续追问"),
                ("配置路径和费用规则再各说一句，别展开。", "追问路径和费用"),
                ("好，这次说清楚了。", "接受补充说明"),
            ],
        }
        content, intent = self._step(plans.get(profile, plans["course_owner"]), turn_index)
        should_continue = not any(ending in content for ending in ["记下了。", "稍后联系。", "再查。", "需求选择。"])
        if profile == "course_driver" and turn_index >= 2:
            should_continue = False
        next_progress = "accepted" if not should_continue else "in_progress"
        return self._pack(content, replace(state, goal_progress=next_progress), intent, should_continue)

    def _generic_turn(
        self,
        profile: str,
        state: UserState,
        case_payload: Dict[str, Any],
        turn_index: int,
    ) -> Dict[str, Any]:
        if state.patience <= 2:
            return self._pack("你先直接说结论和下一步，不要绕流程。", state, "要求明确结论", True)
        if turn_index <= 2:
            return self._pack("我明白了，那下一步需要我配合什么？", state, "确认下一步", True)
        return self._pack("好，你把处理结论、时效和注意事项再确认一下。", state, "总结确认", False)

    def _build_state(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        turn_index: int,
    ) -> UserState:
        task_type = self._task_type(task_payload, case_payload)
        profile = self._profile_kind(task_type, case_payload)
        focus = self._question_focus(task_type, profile, task_payload, case_payload)
        all_user_text = "\n".join(
            [case_payload.get("initial_message", "")]
            + [item.get("user_message", "") for item in history]
        )
        last_assistant = self._last_assistant(history)
        latest = history[-1] if history else {}
        missed_count = len(latest.get("missed_rules", []) or [])
        violated_count = len(latest.get("violated_rules", []) or [])

        info_completeness = self._info_completeness(task_type, profile, all_user_text)
        interruption_count = self._interruption_count(all_user_text)

        emotion = self._base_emotion(profile, case_payload.get("difficulty", "中等"))
        patience = self._base_patience(profile, case_payload.get("difficulty", "中等"))
        emotion += min(turn_index - 1, 3) // 2
        patience -= min(turn_index - 1, 3) // 2
        if missed_count:
            emotion += 1
            patience -= 1
        if violated_count:
            emotion += 2
            patience -= 2
        if self._reply_too_long(task_type, last_assistant, UserState(1, 1, "unclear", "in_progress", 0, focus)):
            emotion += 1
            patience -= 1
        if self._assistant_repeated(history):
            emotion += 1
            patience -= 1
        if self._has_any(last_assistant, ["安全", "稍后", "不打扰", "理解", "明白", "简短", "转达"]):
            emotion -= 1
            patience += 1

        goal_progress = "not_started"
        if history:
            if violated_count >= 2:
                goal_progress = "rejected"
            elif not self._focus_unanswered(task_type, focus, last_assistant) and missed_count <= 1:
                goal_progress = "accepted" if turn_index >= 3 else "in_progress"
            else:
                goal_progress = "in_progress"

        return UserState(
            emotion_level=self._clamp(emotion),
            patience=self._clamp(patience),
            info_completeness=info_completeness,
            goal_progress=goal_progress,
            interruption_count=interruption_count,
            question_focus=focus,
        )

    def _task_type(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
        task_type = task_payload.get("task_type") or ""
        if task_type:
            return task_type
        text = self._joined(
            task_payload.get("instruction_text", ""),
            task_payload.get("name", ""),
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
        if self._has_any(text, ["飞毛腿", "骑手", "配送", "站长"]):
            return "rider_outbound"
        if self._has_any(text, ["课程", "直播", "低延迟", "机构", "商家", "负责人"]):
            return "course_platform_outbound"
        return "generic_outbound"

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
            if self._has_any(text, ["恶劣天气", "下雨", "天气", "抱怨", "不满"]):
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
            if self._has_any(text, ["第三方", "看不到", "技术不熟悉", "配置"]):
                return "course_tech"
            if self._has_any(text, ["优惠券", "价格", "费用"]):
                return "course_price"
            if self._has_any(text, ["被打断", "继续追问"]):
                return "course_interrupted_followup"
            if self._has_any(text, ["反复追问", "区别", "标准直播", "低延迟"]):
                return "course_repeated"
            return "course_owner"

        if self._has_any(text, ["情绪", "不满", "强烈反馈"]):
            return "angry"
        if self._has_any(text, ["反复追问"]):
            return "repeated"
        if self._has_any(text, ["信息缺失"]):
            return "missing"
        return "normal"

    def _question_focus(
        self,
        task_type: str,
        profile: str,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
    ) -> str:
        text = self._joined(
            task_payload.get("instruction_text", ""),
            case_payload.get("name", ""),
            case_payload.get("user_profile", ""),
            case_payload.get("initial_message", ""),
            case_payload.get("expected_goals", []),
            case_payload.get("required_rules", []),
        )
        if task_type == "rider_outbound":
            mapping = {
                "rider_exit": "退出流程",
                "rider_rank": "报名排名",
                "rider_weather": "恶劣天气",
                "rider_repeated": "合同影响",
                "rider_reject": "拒绝配送",
                "rider_willing": "配送要求",
            }
            return mapping.get(profile, "配送要求")
        if task_type == "course_platform_outbound":
            mapping = {
                "course_driver": "稍后联系",
                "course_non_owner": "负责人转达",
                "course_busy": "简短说明",
                "course_tech": "配置路径",
                "course_price": "费用优惠",
                "course_interrupted_followup": "打断后追问",
                "course_repeated": "直播区别",
                "course_owner": "直播升级",
            }
            return mapping.get(profile, "直播升级")
        if self._has_any(text, ["时效", "多久", "时间"]):
            return "处理时效"
        return "下一步动作"

    def _info_completeness(self, task_type: str, profile: str, user_text: str) -> str:
        if profile in {"course_non_owner", "course_driver", "rider_reject"}:
            return "missing"
        if profile in {"course_busy", "rider_weather", "course_tech"}:
            return "unclear"
        required = {
            "rider_outbound": ["骑手", "今天", "合同"],
            "course_platform_outbound": ["负责人", "直播", "配置"],
        }.get(task_type, [])
        if not required:
            return "unclear"
        hit = sum(1 for keyword in required if keyword in user_text)
        if hit >= 2:
            return "complete"
        if hit == 1:
            return "unclear"
        return "missing"

    def _constraint_violation(
        self,
        task_type: str,
        profile: str,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        last_assistant: str,
    ) -> Tuple[str, str] | None:
        all_user = self._joined(
            case_payload.get("initial_message", ""),
            [item.get("user_message", "") for item in history],
        )
        if task_type == "course_platform_outbound" and profile == "course_driver":
            keeps_selling = self._has_any(last_assistant, ["直播", "低延迟", "配置", "升级", "费用"])
            politely_stops = self._has_any(last_assistant, ["稍后", "不打扰", "先挂", "路上", "安全", "方便再"])
            if "开车" in all_user and keeps_selling and not politely_stops:
                return "我都说在开车了，你还继续推销，先挂了。", "约束被违反后结束通话"
        if task_type == "course_platform_outbound" and profile == "course_price":
            if self._has_any(last_assistant, ["送优惠券", "给优惠券", "保证优惠", "一定便宜"]):
                return "你这样承诺优惠不靠谱，我先不继续了。", "识别不合规承诺"
        if task_type == "rider_outbound" and profile == "rider_weather":
            if self._has_any(last_assistant, ["必须冒雨", "强制配送", "不跑不行", "一定要跑"]):
                return "你这是让我冒险，我先不聊了。", "安全约束被违反后拒绝"
        return None

    def _needs_identity_confirmation(
        self,
        task_type: str,
        case_payload: Dict[str, Any],
        history: List[Dict[str, Any]],
        last_assistant: str,
    ) -> bool:
        if not history:
            return False
        all_user = self._joined(case_payload.get("initial_message", ""), [item.get("user_message", "") for item in history])
        if self._has_any(all_user, ["你是谁", "哪位", "做什么的"]):
            return False
        if task_type == "rider_outbound":
            return not self._has_any(last_assistant, ["站长", "飞毛腿", "合同", "骑手"])
        if task_type == "course_platform_outbound":
            return not self._has_any(last_assistant, ["机构", "校区", "负责人", "课程", "直播"])
        return False

    def _focus_unanswered(self, task_type: str, focus: str, assistant_text: str) -> bool:
        if not assistant_text:
            return False
        keywords = {
            "身份确认": ["站长", "飞毛腿", "机构", "负责人", "课程", "直播"],
            "配送要求": ["合同", "完成", "单", "配送", "安全"],
            "拒绝配送": ["影响", "合同", "派单", "无法", "结束"],
            "合同影响": ["影响", "合同", "派单", "完成"],
            "退出流程": ["App", "报名", "取消", "前一天"],
            "恶劣天气": ["安全", "恶劣天气", "订单", "资格", "不强迫"],
            "报名排名": ["排名", "站长", "干预", "资格"],
            "直播升级": ["标准直播", "低延迟", "两个", "选项"],
            "负责人转达": ["转达", "负责人", "简短"],
            "简短说明": ["1分钟", "简短", "重点", "标准直播", "低延迟"],
            "稍后联系": ["稍后", "不打扰", "先挂", "开车"],
            "直播区别": ["5-10", "1-2", "标准直播", "低延迟", "互动"],
            "配置路径": ["Web", "后台", "第三方", "服务产品", "明天"],
            "费用优惠": ["不能承诺", "优惠券", "费用", "价格"],
            "打断后追问": ["低延迟", "场景", "配置", "费用", "路径"],
        }.get(focus, [])
        if not keywords:
            return False
        return not self._has_any(assistant_text, keywords)

    def _follow_up_question(self, task_type: str, profile: str, focus: str) -> str:
        questions = {
            "配送要求": "你还没说清楚今天到底要完成多少单，以及不完成会怎样。",
            "拒绝配送": "我问的是如果今天实在跑不了，合同和派单具体怎么受影响？",
            "合同影响": "你直接回答，如果今天没完成 X 单，会不会影响后续派单？",
            "退出流程": "你还没说怎么退出飞毛腿，具体是在 App 哪个入口取消？",
            "恶劣天气": "你先回答安全问题，下雨这么大是不是可以不用冒险？",
            "报名排名": "你还没解释排名规则，站长到底能不能干预？",
            "直播升级": "你还没讲清楚新增的两个直播选项分别是什么。",
            "负责人转达": "我不是负责人，你用一句话说重点，我好转达。",
            "简短说明": "我现在没时间，你说重点，不要展开。",
            "稍后联系": "我在开车，别继续说了，稍后再联系。",
            "直播区别": "你直接说标准直播和低延迟直播的延迟、费用差别。",
            "配置路径": "我问的是第三方系统看不到选项时，具体该走什么路径。",
            "费用优惠": "你还没回答能不能给优惠券，费用规则是什么？",
            "打断后追问": "刚才被打断了，你接着用一句话说低延迟场景、配置路径和费用规则。",
        }
        return questions.get(focus, "你还没回答我的问题，直接说结论和下一步。")

    def _focus_question(self, task_type: str, profile: str, focus: str) -> str:
        return self._follow_up_question(task_type, profile, focus)

    def _reply_too_long(self, task_type: str, text: str, state: UserState) -> bool:
        if not text:
            return False
        threshold = 120 if task_type == "course_platform_outbound" else 150
        if state.patience >= 4:
            threshold += 40
        return len(text) > threshold

    def _assistant_repeated(self, history: List[Dict[str, Any]]) -> bool:
        if len(history) < 2:
            return False
        current = history[-1].get("assistant_message", "")
        previous = history[-2].get("assistant_message", "")
        if not current or not previous:
            return False
        if current == previous:
            return True
        return SequenceMatcher(None, current, previous).ratio() >= 0.88

    def _interrupt_text(self, profile: str) -> str:
        if profile == "course_driver":
            return "我在开车，别继续说了，稍后再打。"
        if profile in {"course_busy", "course_non_owner"}:
            return "你说重点，我现在没时间听完整流程。"
        if profile.startswith("rider"):
            return "你说重点，直接告诉我会不会影响合同和派单。"
        return "你说重点，直接讲结论。"

    def _step(self, plan: List[Tuple[str, str]], turn_index: int) -> Tuple[str, str]:
        index = min(max(turn_index - 2, 0), len(plan) - 1)
        return plan[index]

    def _pack(self, content: str, state: UserState, intent: str, should_continue: bool) -> Dict[str, Any]:
        return {
            "content": content,
            "user_state": asdict(state),
            "intent": intent,
            "should_continue": should_continue,
        }

    def _default_initial(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
        task_type = self._task_type(task_payload, case_payload)
        if task_type == "rider_outbound":
            return "可以，你说吧。"
        if task_type == "course_platform_outbound":
            return "您好，我是负责人，你简单说。"
        return "你好，我想确认一下这个问题怎么处理。"

    def _initial_intent(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
        task_type = self._task_type(task_payload, case_payload)
        focus = self._question_focus(task_type, self._profile_kind(task_type, case_payload), task_payload, case_payload)
        return f"发起外呼对象回应：{focus}"

    def _base_emotion(self, profile: str, difficulty: str) -> int:
        value = {
            "rider_willing": 2,
            "rider_reject": 3,
            "rider_weather": 4,
            "rider_repeated": 3,
            "rider_rank": 3,
            "rider_exit": 2,
            "course_owner": 2,
            "course_non_owner": 2,
            "course_busy": 3,
            "course_driver": 3,
            "course_repeated": 3,
            "course_tech": 2,
            "course_price": 3,
            "course_interrupted_followup": 3,
            "angry": 4,
            "repeated": 3,
            "missing": 2,
            "normal": 2,
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
            "rider_repeated": 3,
            "rider_rank": 3,
            "rider_exit": 4,
            "course_owner": 5,
            "course_non_owner": 3,
            "course_busy": 2,
            "course_driver": 1,
            "course_repeated": 3,
            "course_tech": 4,
            "course_price": 3,
            "course_interrupted_followup": 3,
            "angry": 2,
            "repeated": 3,
            "missing": 4,
            "normal": 4,
        }.get(profile, 4)
        if difficulty == "困难":
            value -= 1
        elif difficulty == "简单":
            value += 1
        return self._clamp(value)

    def _interruption_count(self, user_text: str) -> int:
        markers = ["你说重点", "没时间", "开车", "先挂", "别继续", "不要展开"]
        return sum(user_text.count(marker) for marker in markers)

    def _last_assistant(self, history: List[Dict[str, Any]]) -> str:
        return history[-1].get("assistant_message", "") if history else ""

    def _avoid_repeat(self, content: str, history: List[Dict[str, Any]]) -> str:
        previous_user = history[-1].get("user_message", "") if history else ""
        if content != previous_user:
            return content
        return f"{content} 这次请你换个说法直接回答。"

    def _user_message_closes(self, content: str) -> bool:
        return self._has_any(
            content,
            [
                "知道了",
                "明白了",
                "尽量跑",
                "按合同要求",
                "注意安全",
                "去 App 看看",
                "让负责人看一下",
                "稍后联系",
                "先挂了",
            ],
        )

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
