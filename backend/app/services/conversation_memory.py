from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List

from app.services.case_mode import normalize_case_mode
from app.services.course_flow import course_full_flow_expected_steps, course_full_flow_step_done
from app.services.dialogue_state import analyze_dialogue_state, is_similar_text
from app.services.rider_flow import rider_full_flow_expected_steps, rider_rank_qualification_done


COURSE_CROSS_TASK_TERMS = [
    "飞毛腿",
    "骑手",
    "配送",
    "派单",
    "合同 X 单",
    "合同Y单",
]

RIDER_CROSS_TASK_TERMS = [
    "标准直播",
    "低延迟直播",
    "负责人",
]


def initialize_memory_state(
    task_payload: Dict[str, Any],
    case_payload: Dict[str, Any],
    task_type: str,
    planned_max_turns: int,
    run_id: int | None = None,
) -> Dict[str, Any]:
    """Create an isolated, run-scoped memory state.

    The object is intentionally JSON-friendly and stored on RunMessage.detail.
    It is rebuilt for every run and never read from previous runs.
    """

    expected_steps = _expected_steps(task_type, case_payload)
    return {
        "scope": "run",
        "run_id": run_id,
        "task_type": task_type,
        "case_mode": normalize_case_mode(case_payload.get("case_mode"), case_payload),
        "planned_max_turns": planned_max_turns,
        "updated_at_turn": 0,
        "current_step": "opening",
        "interrupted": False,
        "interrupted_from_step": "",
        "last_user_question": "",
        "pending_return_step": "",
        "user_event": "normal",
        "is_busy": False,
        "is_driving": False,
        "should_continue": True,
        "next_best_action": "",
        "flow_memory": {
            "current_stage": "opening",
            "expected_steps": expected_steps,
            "covered_steps": [],
            "pending_steps": expected_steps,
            "assistant_said_topics": [],
            "user_asked_topics": [],
        },
        "user_branch_memory": _initial_branch_memory(task_type),
        "model_performance_memory": {
            "verbose_turns": [],
            "unanswered_turns": [],
            "repeated_turns": [],
            "jumped_steps": [],
            "interrupted_turns": [],
            "cross_task_terms": [],
            "constraint_violations": [],
            "fallback_used_turns": [],
        },
        "unfinished_items_memory": {
            "required_pending": expected_steps,
            "pending_rules": [],
            "next_suggested_step": expected_steps[0] if expected_steps else "",
            "next_user_prompt": _next_user_prompt(task_type, expected_steps[0] if expected_steps else ""),
        },
        "summary": "新评测 run 已初始化，尚未进入主流程。",
    }


def update_memory_state(
    memory_state: Dict[str, Any] | None,
    task_payload: Dict[str, Any],
    case_payload: Dict[str, Any],
    history: List[Dict[str, Any]],
    *,
    turn_index: int,
    planned_max_turns: int,
    turn_score: Dict[str, Any] | None = None,
    user_turn: Dict[str, Any] | None = None,
    target_result: Any | None = None,
    stop_decision: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    task_type = _task_type(task_payload, case_payload)
    state = deepcopy(
        memory_state
        or initialize_memory_state(task_payload, case_payload, task_type, planned_max_turns)
    )
    state["scope"] = "run"
    state["task_type"] = task_type
    state["case_mode"] = normalize_case_mode(case_payload.get("case_mode"), case_payload)
    state["planned_max_turns"] = planned_max_turns
    state["updated_at_turn"] = turn_index

    dialogue_state = analyze_dialogue_state(task_payload, case_payload, history)
    expected_steps = _expected_steps(task_type, case_payload)
    covered_steps, pending_steps = _step_status(task_type, case_payload, history, dialogue_state, expected_steps)

    state["flow_memory"] = {
        "current_stage": (turn_score or {}).get("current_stage") or dialogue_state.get("current_stage", ""),
        "expected_steps": expected_steps,
        "covered_steps": covered_steps,
        "pending_steps": pending_steps,
        "assistant_said_topics": dialogue_state.get("assistant_said_topics", []),
        "user_asked_topics": dialogue_state.get("user_asked_topics", []),
    }
    state["user_branch_memory"] = _branch_memory(task_type, case_payload, history, user_turn)
    state["model_performance_memory"] = _model_performance_memory(
        task_type,
        history,
        turn_score,
        target_result,
    )
    pending_rules = list((turn_score or {}).get("pending_rules") or [])
    next_step = pending_steps[0] if pending_steps else ""
    state["unfinished_items_memory"] = {
        "required_pending": pending_steps,
        "pending_rules": pending_rules,
        "next_suggested_step": next_step,
        "next_user_prompt": _next_user_prompt(task_type, next_step),
        "stop_decision": stop_decision or {},
    }
    _merge_user_event_memory(state, user_turn, history)
    state["summary"] = _summary(state)
    return state


def compact_memory_for_prompt(memory_state: Dict[str, Any] | None) -> Dict[str, Any]:
    """Keep prompts small while preserving the useful state."""

    if not memory_state:
        return {}
    flow = memory_state.get("flow_memory") or {}
    branch = memory_state.get("user_branch_memory") or {}
    performance = memory_state.get("model_performance_memory") or {}
    unfinished = memory_state.get("unfinished_items_memory") or memory_state.get("unfinished_memory") or {}
    covered_steps = (
        flow.get("covered_steps")
        or flow.get("completed_stages")
        or unfinished.get("required_rules_done")
        or []
    )
    pending_steps = (
        flow.get("pending_steps")
        or flow.get("pending_stages")
        or unfinished.get("required_pending")
        or unfinished.get("required_rules_pending")
        or []
    )
    next_suggested_step = unfinished.get("next_suggested_step") or unfinished.get("next_best_action") or ""
    next_user_prompt = unfinished.get("next_user_prompt") or unfinished.get("next_best_action") or ""
    return {
        "scope": "run",
        "task_type": memory_state.get("task_type", ""),
        "case_mode": memory_state.get("case_mode", ""),
        "updated_at_turn": memory_state.get("updated_at_turn", 0),
        "current_stage": flow.get("current_stage", ""),
        "covered_steps": covered_steps,
        "pending_steps": pending_steps,
        "user_branch_memory": branch,
        "model_performance_memory": {
            "verbose_turns": performance.get("verbose_turns", []),
            "unanswered_turns": performance.get("unanswered_turns", []),
            "repeated_turns": performance.get("repeated_turns", []),
            "interrupted_turns": performance.get("interrupted_turns", []),
            "constraint_violations": performance.get("constraint_violations", []),
            "too_verbose_count": performance.get("too_verbose_count", 0),
            "unanswered_question_count": performance.get("unanswered_question_count", 0),
            "repeat_count": performance.get("repeat_count", 0),
            "interrupted_count": performance.get("interrupted_count", 0),
            "off_topic_count": performance.get("off_topic_count", 0),
            "constraint_violation_count": performance.get("constraint_violation_count", 0),
        },
        "next_suggested_step": next_suggested_step,
        "next_user_prompt": next_user_prompt,
        "current_step": memory_state.get("current_step", ""),
        "interrupted": bool(memory_state.get("interrupted", False)),
        "interrupted_from_step": memory_state.get("interrupted_from_step", ""),
        "last_user_question": memory_state.get("last_user_question", ""),
        "pending_return_step": memory_state.get("pending_return_step", ""),
        "user_event": memory_state.get("user_event", "normal"),
        "is_busy": bool(memory_state.get("is_busy", False)),
        "is_driving": bool(memory_state.get("is_driving", False)),
        "should_continue": bool(memory_state.get("should_continue", True)),
        "next_best_action": memory_state.get("next_best_action", ""),
        "summary": memory_state.get("summary", "") or (memory_state.get("conversation_memory") or {}).get("short_summary", ""),
    }


def _merge_user_event_memory(
    state: Dict[str, Any],
    user_turn: Dict[str, Any] | None,
    history: List[Dict[str, Any]],
) -> None:
    metadata = (user_turn or {}).get("metadata") or {}
    flow = state.get("flow_memory") or {}
    current_step = str(metadata.get("current_step") or state.get("current_step") or flow.get("current_stage") or "")
    user_message = str(history[-1].get("user_message", "") or "") if history else ""
    if _has_any(user_message, ["那继续", "继续说", "你继续"]):
        state["interrupted"] = False
        state["pending_return_step"] = ""
    elif metadata:
        state["interrupted"] = bool(metadata.get("interrupted", state.get("interrupted", False)))
    state["current_step"] = current_step
    state["user_event"] = str(metadata.get("user_event") or state.get("user_event") or "normal")
    state["interrupted_from_step"] = str(metadata.get("interrupted_from_step") or (current_step if state.get("interrupted") else ""))
    state["last_user_question"] = str(metadata.get("last_user_question") or _major_question(user_message) or state.get("last_user_question") or "")
    state["pending_return_step"] = str(metadata.get("pending_return_step") or state.get("pending_return_step") or "")
    state["is_busy"] = bool(metadata.get("is_busy", state.get("is_busy", False)))
    state["is_driving"] = bool(metadata.get("is_driving", state.get("is_driving", False)))
    state["should_continue"] = bool(metadata.get("should_continue", state.get("should_continue", True)))
    state["next_best_action"] = str(metadata.get("next_best_action") or state.get("next_best_action") or "")


def _major_question(text: str) -> str:
    if not text:
        return ""
    if "？" in text or "?" in text:
        return text
    if _has_any(text, ["费用", "区别", "低延迟", "配置", "看不到", "企业微信", "附加费"]):
        return text
    return ""


def _expected_steps(task_type: str, case_payload: Dict[str, Any]) -> List[str]:
    configured = [str(item).strip() for item in case_payload.get("expected_steps", []) or [] if str(item).strip()]
    if task_type == "course_platform_outbound":
        return course_full_flow_expected_steps(configured, case_payload)
    if task_type == "rider_outbound":
        return rider_full_flow_expected_steps(configured, case_payload)
    return configured or ["说明目的", "推进下一步", "结束确认"]


def _step_status(
    task_type: str,
    case_payload: Dict[str, Any],
    history: List[Dict[str, Any]],
    dialogue_state: Dict[str, Any],
    expected_steps: List[str],
) -> tuple[List[str], List[str]]:
    assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in history)
    user_text = "\n".join(str(item.get("user_message", "") or "") for item in history)
    said = set(dialogue_state.get("assistant_said_topics") or [])
    covered: List[str] = []
    pending: List[str] = []
    for step in expected_steps:
        done = _step_done(task_type, step, user_text, assistant_text, said)
        if done:
            covered.append(step)
        else:
            pending.append(step)
    return covered, pending


def _step_done(task_type: str, step: str, user_text: str, assistant_text: str, said: set[str]) -> bool:
    combined = f"{user_text}\n{assistant_text}"
    if task_type == "course_platform_outbound":
        return course_full_flow_step_done(step, user_text, assistant_text, said)
    if task_type == "rider_outbound":
        checks = {
            "确认身份": _has_any(combined, ["本人", "骑手", "站长", "请问"]),
            "告知合同生效": _has_any(assistant_text, ["合同已生效", "合同今天已生效", "飞毛腿合同已生效"]),
            "告知今天飞毛腿合同已生效": _has_any(assistant_text, ["合同已签署", "签署并生效", "合同已生效", "飞毛腿合同已生效"]),
            "说明午晚高峰上线和单量要求": _has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and _has_any(assistant_text, ["X 单", "X单"]) and _has_any(assistant_text, ["Y 单", "Y单"]),
            "说明午晚高峰和单量要求": _has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and _has_any(assistant_text, ["X 单", "X单"]) and _has_any(assistant_text, ["Y 单", "Y单"]),
            "询问是否开始配送": _has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送"]) or _has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
            "询问是否可以开始配送": _has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送", "是否可以"]) or _has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
            "根据骑手态度鼓励挽留或安抚": _has_any(assistant_text, ["尽量", "建议", "理解", "辛苦", "名额", "高峰"]),
            "提醒注意安全": _has_any(assistant_text, ["安全", "注意"]),
            "说明排名与保资格规则": rider_rank_qualification_done(assistant_text),
            "结束确认": _has_any(user_text, ["明白", "按要求", "按规则", "知道了", "尽量完成", "会按要求"]) and _has_any(assistant_text, ["好的", "注意安全", "先这样", "辛苦", "后续有问题", "再联系"]),
        }
        return bool(checks.get(step, False))
    return bool(assistant_text.strip())


def _initial_branch_memory(task_type: str) -> Dict[str, Any]:
    if task_type == "course_platform_outbound":
        return {
            "is_owner": None,
            "awareness": None,
            "busy": False,
            "driving": False,
            "publish_method": None,
            "low_latency_visible": None,
            "fee_focus": False,
            "fee_setting": None,
            "enterprise_wechat_addable": None,
        }
    if task_type == "rider_outbound":
        return {
            "identity_confirmed": None,
            "delivery_attitude": None,
            "weather_concern": False,
            "rank_concern": False,
            "exit_requested": False,
            "reward_requested": False,
        }
    return {"accepted": None, "busy": False}


def _branch_memory(
    task_type: str,
    case_payload: Dict[str, Any],
    history: List[Dict[str, Any]],
    user_turn: Dict[str, Any] | None,
) -> Dict[str, Any]:
    branch = _initial_branch_memory(task_type)
    user_text = "\n".join(str(item.get("user_message", "") or "") for item in history)
    profile = " ".join(
        str(case_payload.get(key, "") or "")
        for key in ["name", "user_profile", "initial_message", "user_behavior_type"]
    )
    text = f"{profile}\n{user_text}"
    if task_type == "course_platform_outbound":
        if _has_any(text, ["不是负责人", "非负责人", "前台"]):
            branch["is_owner"] = False
        if _has_any(text, ["我是负责人", "是负责人", "机构负责人", "校区负责人"]):
            branch["is_owner"] = True
        if _has_any(text, ["不知道", "不知情", "没听过", "之前不知道"]):
            branch["awareness"] = "unknown"
        elif _has_any(text, ["已知情", "知道后台", "知道低延迟", "知道。"]):
            branch["awareness"] = "known"
        branch["busy"] = _has_any(text, ["忙", "没时间", "说重点"])
        branch["driving"] = _has_any(text, ["开车", "路上", "不方便说"])
        if _has_any(text, ["Web控制台", "Web 控制台"]):
            branch["publish_method"] = "web_console"
        elif _has_any(text, ["校务系统A", "校务 A"]):
            branch["publish_method"] = "school_system_a"
        elif _has_any(text, ["SaaS系统B", "SaaS B", "SaaS"]):
            branch["publish_method"] = "saas_system_b"
        elif _has_any(text, ["第三方系统", "第三方"]):
            branch["publish_method"] = "third_party"
        if _has_any(text, ["已显示", "能看到"]):
            branch["low_latency_visible"] = True
        elif _has_any(text, ["没显示", "未显示", "看不到", "没有选项"]):
            branch["low_latency_visible"] = False
        branch["fee_focus"] = _has_any(text, ["费用", "价格", "贵", "附加费", "加速线路", "优惠券"])
        if _has_any(text, ["没设置费用", "未设置费用"]):
            branch["fee_setting"] = "not_set"
        elif _has_any(text, ["不会配置", "无法自行配置"]):
            branch["fee_setting"] = "needs_guidance"
        elif _has_any(text, ["已设置费用", "已经设置费用"]):
            branch["fee_setting"] = "set"
        if _has_any(text, ["加不了", "不能加", "不可添加"]):
            branch["enterprise_wechat_addable"] = False
        elif _has_any(text, ["当前号码能加", "可以添加", "可添加"]):
            branch["enterprise_wechat_addable"] = True
        return branch

    if task_type == "rider_outbound":
        if _has_any(text, ["是我", "本人", "王师傅"]):
            branch["identity_confirmed"] = True
        if _has_any(text, ["可以", "能跑", "马上上线", "按要求跑"]):
            branch["delivery_attitude"] = "willing"
        if _has_any(text, ["不一定", "看看情况", "有点忙", "不确定"]):
            branch["delivery_attitude"] = "hesitant"
        if _has_any(text, ["不想干", "不干", "不想跑", "跑不了", "无法配送", "不送"]):
            branch["delivery_attitude"] = "reject"
        branch["weather_concern"] = _has_any(text, ["下雨", "雨天", "恶劣天气", "安全"])
        branch["rank_concern"] = _has_any(text, ["排名", "名额", "站长", "资格"])
        branch["exit_requested"] = _has_any(text, ["退出", "取消飞毛腿", "怎么取消", "取消报名"])
        branch["reward_requested"] = _has_any(text, ["奖励", "补贴", "额外"])
        return branch

    branch["accepted"] = _has_any(text, ["知道了", "明白", "没问题"])
    branch["busy"] = _has_any(text, ["忙", "没时间", "稍后"])
    return branch


def _model_performance_memory(
    task_type: str,
    history: List[Dict[str, Any]],
    turn_score: Dict[str, Any] | None,
    target_result: Any | None,
) -> Dict[str, Any]:
    verbose_turns: List[int] = []
    unanswered_turns: List[int] = []
    repeated_turns: List[int] = []
    jumped_steps: List[Dict[str, Any]] = []
    interrupted_turns: List[int] = []
    cross_task_terms: List[Dict[str, Any]] = []
    previous_reply = ""

    for item in history:
        turn = int(item.get("turn_index") or 0)
        user = str(item.get("user_message", "") or "")
        assistant = str(item.get("assistant_message", "") or "")
        if assistant and _reply_too_long(task_type, assistant):
            verbose_turns.append(turn)
        if user and _has_any(user, ["说重点", "没时间", "忙", "先挂", "不方便"]):
            interrupted_turns.append(turn)
        if previous_reply and assistant and is_similar_text(assistant, previous_reply):
            repeated_turns.append(turn)
        if assistant:
            previous_reply = assistant
        for term in _cross_task_hits(task_type, assistant):
            cross_task_terms.append({"turn_index": turn, "term": term})
        if task_type == "course_platform_outbound" and _jumps_course_flow(history, turn):
            jumped_steps.append({"turn_index": turn, "reason": "未完成升级说明前进入配置/发布方式"})

    if turn_score and turn_score.get("current_stage") and turn_score.get("reason"):
        if "未回答" in str(turn_score.get("deduction_reason", "")):
            unanswered_turns.append(int(history[-1].get("turn_index") or 0) if history else 0)
    violations = list((turn_score or {}).get("violated_rules") or [])
    violations.extend(((turn_score or {}).get("hidden_guardrail_rules") or {}).get("violated", []))
    fallback_turns: List[int] = []
    if target_result is not None and getattr(target_result, "fallback_used", False) and history:
        fallback_turns.append(int(history[-1].get("turn_index") or 0))

    return {
        "verbose_turns": _dedupe_ints(verbose_turns),
        "unanswered_turns": _dedupe_ints(unanswered_turns),
        "repeated_turns": _dedupe_ints(repeated_turns),
        "jumped_steps": jumped_steps,
        "interrupted_turns": _dedupe_ints(interrupted_turns),
        "cross_task_terms": cross_task_terms,
        "constraint_violations": list(dict.fromkeys(violations)),
        "fallback_used_turns": fallback_turns,
    }


def _jumps_course_flow(history: List[Dict[str, Any]], turn: int) -> bool:
    assistant_before = "\n".join(
        str(item.get("assistant_message", "") or "")
        for item in history
        if int(item.get("turn_index") or 0) <= turn
    )
    current = next((str(item.get("assistant_message", "") or "") for item in history if int(item.get("turn_index") or 0) == turn), "")
    has_upgrade = _has_any(assistant_before, ["直播产品升级", "发布页", "新增低延迟", "两个选项"])
    jumps_config = _has_any(current, ["Web", "SaaS", "校务", "直播平台管理", "配置"])
    return jumps_config and not has_upgrade


def _next_user_prompt(task_type: str, next_step: str) -> str:
    if not next_step:
        return ""
    course = {
        "身份确认": "我是负责人，你说吧。",
        "确认是否知情": "我之前不知道，你继续说。",
        "传达升级内容": "你先说升级了什么。",
        "说明标准直播和低延迟直播区别": "标准直播和低延迟有什么区别？",
        "说明价格差异": "费用会不会更高？",
        "询问发布方式": "我们从哪里发课？",
        "确认前端是否可见并说明配置路径": "第三方里看不到，怎么开？",
        "检查学员端费用/加速线路费": "学员端费用要不要处理？",
        "企业微信添加": "后续怎么联系？",
        "结束确认": "没问题了。",
    }
    rider = {
        "确认身份": "是我，你说。",
        "告知今天飞毛腿合同已生效": "你先说今天合同状态。",
        "说明午晚高峰和单量要求": "今天具体有什么要求？",
        "询问是否可以开始配送": "那今天需要我开始配送吗？",
        "根据骑手态度鼓励挽留或安抚": "我能跑，你简单说重点。",
        "提醒注意安全": "配送时有什么安全要注意？",
        "说明排名与保资格规则": "飞毛腿名额是站长定的吗？",
        "结束确认": "好，我明白了。",
    }
    if task_type == "course_platform_outbound":
        return course.get(next_step, "下一步怎么做？")
    if task_type == "rider_outbound":
        return rider.get(next_step, "继续说下一步。")
    return "下一步是什么？"


def _summary(memory_state: Dict[str, Any]) -> str:
    flow = memory_state.get("flow_memory") or {}
    unfinished = memory_state.get("unfinished_items_memory") or {}
    current = flow.get("current_stage") or "unknown"
    covered_count = len(flow.get("covered_steps") or [])
    pending = flow.get("pending_steps") or []
    next_step = unfinished.get("next_suggested_step") or ""
    if next_step:
        return f"当前阶段 {current}，已覆盖 {covered_count} 项，下一步应自然推进：{next_step}。"
    return f"当前阶段 {current}，主流程关键项已覆盖。"


def _task_type(task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
    task_type = str(task_payload.get("task_type") or "").strip()
    if task_type:
        return task_type
    text = " ".join(
        str(value or "")
        for value in [
            task_payload.get("instruction_text", ""),
            task_payload.get("name", ""),
            case_payload.get("name", ""),
            case_payload.get("initial_message", ""),
        ]
    )
    if _has_any(text, ["飞毛腿", "骑手", "配送", "派单"]):
        return "rider_outbound"
    if _has_any(text, ["课程", "直播", "低延迟", "机构", "负责人"]):
        return "course_platform_outbound"
    return "generic_outbound"


def _cross_task_hits(task_type: str, assistant: str) -> List[str]:
    if task_type == "course_platform_outbound":
        return [term for term in COURSE_CROSS_TASK_TERMS if term and term in assistant]
    if task_type == "rider_outbound":
        return [term for term in RIDER_CROSS_TASK_TERMS if term and term in assistant]
    return []


def _reply_too_long(task_type: str, text: str) -> bool:
    compact = "".join(str(text or "").split())
    if not compact:
        return False
    if task_type == "course_platform_outbound":
        return len(compact) > 24
    if task_type == "rider_outbound":
        return len(compact) > 60
    return len(compact) > 80


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def _dedupe_ints(values: Iterable[int]) -> List[int]:
    return list(dict.fromkeys(int(value) for value in values if value is not None))
