from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List

from sqlmodel import Session


def init_memory(task: Any, case: Any) -> Dict[str, Any]:
    """Return a clean run-level memory state for one evaluation run."""

    memory = _default_memory()
    pending_rules = _list_field(case, "required_rules")
    memory["unfinished_memory"]["required_rules_pending"] = pending_rules
    memory["unfinished_memory"]["next_best_action"] = _first_pending_action(case, pending_rules)
    return memory


def reset_memory_for_new_run(task: Any, case: Any) -> Dict[str, Any]:
    """Every new run gets a fresh memory object; callers must not reuse it."""

    return init_memory(task, case)


def load_memory(run: Any) -> Dict[str, Any]:
    raw = getattr(run, "memory_state", None)
    if not isinstance(raw, dict):
        return _default_memory()
    return _normalize_memory(raw)


def save_memory(db: Session, run: Any, memory: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_memory(memory)
    run.memory_state = normalized
    db.add(run)
    db.commit()
    db.refresh(run)
    return normalized


def update_after_user(
    memory: Dict[str, Any],
    user_message: str,
    user_metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    result = _normalize_memory(memory)
    text = str(user_message or "")
    metadata = user_metadata or {}
    branch = result["user_branch_memory"]
    performance = result["model_performance_memory"]
    conversation = result["conversation_memory"]
    unfinished = result["unfinished_memory"]
    interaction = result["interaction_memory"]

    if _has_any(text, ["不是负责人", "非负责人", "只是前台", "前台"]):
        branch["is_responsible_person"] = False
    elif _has_any(text, ["我是负责人", "是负责人", "机构负责人", "校区负责人"]):
        branch["is_responsible_person"] = True

    if _has_any(text, ["不知道", "不知情", "没听过", "之前不知道"]):
        branch["knows_feature"] = False
    elif _has_any(text, ["知道", "已知情", "知道后台"]):
        branch["knows_feature"] = True

    if _has_any(text, ["忙", "没时间", "说重点"]):
        branch["is_busy"] = True
    if _has_any(text, ["开车", "路上", "不方便说"]):
        branch["is_driving"] = True

    if _has_any(text, ["Web控制台", "Web 控制台", "web控制台"]):
        branch["publish_channel"] = "web_console"
    elif _has_any(text, ["校务系统A", "校务 A"]):
        branch["publish_channel"] = "school_system_a"
    elif _has_any(text, ["SaaS系统B", "SaaS B", "SaaS"]):
        branch["publish_channel"] = "saas_system_b"
    elif _has_any(text, ["第三方系统", "第三方"]):
        branch["publish_channel"] = "third_party"

    if _has_any(text, ["已显示", "能看到"]):
        branch["can_see_option"] = True
    elif _has_any(text, ["看不到", "没显示", "未显示", "没有选项"]):
        branch["can_see_option"] = False

    if _has_any(text, ["费用", "价格", "贵", "优惠券", "折扣", "附加费", "加速线路"]):
        branch["cares_about_price"] = True

    if _has_any(text, ["加不了", "不能加", "不可添加"]):
        branch["can_add_wecom"] = False
    elif _has_any(text, ["能加", "可添加", "可以添加"]):
        branch["can_add_wecom"] = True

    interrupted = _has_any(text, ["说重点", "没时间", "别继续", "先挂", "不方便说"])
    if interrupted:
        performance["interrupted_count"] = int(performance.get("interrupted_count") or 0) + 1

    intent = str(metadata.get("intent") or _infer_user_intent(text))
    conversation["last_user_intent"] = intent
    conversation["last_user_question"] = _major_question(text)
    conversation["short_summary"] = _short_summary_after_user(text, intent)
    user_event = str(metadata.get("user_event") or "normal")
    current_step = str(metadata.get("current_step") or flow_current_stage(result))
    interrupted = bool(metadata.get("interrupted"))
    if _has_any(text, ["那继续", "继续说", "你继续"]):
        interrupted = False
        interaction["pending_return_step"] = ""
    interaction.update(
        {
            "current_step": current_step,
            "interrupted": interrupted,
            "interrupted_from_step": metadata.get("interrupted_from_step") or (current_step if interrupted else ""),
            "last_user_question": metadata.get("last_user_question") or conversation["last_user_question"],
            "user_event": user_event,
            "is_busy": bool(metadata.get("is_busy")) or branch["is_busy"],
            "is_driving": bool(metadata.get("is_driving")) or branch["is_driving"],
            "should_continue": bool(metadata.get("should_continue", True)),
            "next_best_action": metadata.get("next_best_action") or interaction.get("next_best_action") or "",
        }
    )
    if interrupted:
        interaction["pending_return_step"] = metadata.get("pending_return_step") or current_step

    next_action = _next_best_action(result)
    if next_action:
        unfinished["next_best_action"] = next_action
    if interaction.get("next_best_action"):
        unfinished["next_best_action"] = interaction["next_best_action"]
    return result


def update_after_model(
    memory: Dict[str, Any],
    model_reply: str,
    judge_result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    result = _normalize_memory(memory)
    reply = str(model_reply or "")
    judge = judge_result or {}
    flow = result["flow_memory"]
    performance = result["model_performance_memory"]
    unfinished = result["unfinished_memory"]
    conversation = result["conversation_memory"]

    current_stage = str(judge.get("current_stage") or flow.get("current_stage") or "start")
    flow["current_stage"] = current_stage

    hit_rules = _rules_from(judge, "hit_rules", "matched_rules")
    missed_rules = _rules_from(judge, "missed_rules", "pending_rules")
    forbidden_hits = _rules_from(judge, "forbidden_hits", "violated_rules")
    hidden_violated = (judge.get("hidden_guardrail_rules") or {}).get("violated", [])
    forbidden_hits.extend(str(item) for item in hidden_violated if str(item).strip())

    flow["completed_stages"] = _dedupe(list(flow.get("completed_stages") or []) + hit_rules)
    flow["pending_stages"] = _dedupe([item for item in list(flow.get("pending_stages") or []) if item not in hit_rules] + missed_rules)

    required_done = _dedupe(list(unfinished.get("required_rules_done") or []) + hit_rules)
    required_pending = [item for item in list(unfinished.get("required_rules_pending") or []) if item not in required_done]
    for rule in missed_rules:
        if rule not in required_done and rule not in required_pending:
            required_pending.append(rule)
    forbidden_rules = _dedupe(list(unfinished.get("forbidden_rules_hit") or []) + forbidden_hits)

    unfinished["required_rules_done"] = required_done
    unfinished["required_rules_pending"] = required_pending
    unfinished["forbidden_rules_hit"] = forbidden_rules

    if forbidden_hits:
        performance["constraint_violation_count"] = int(performance.get("constraint_violation_count") or 0) + 1
    if bool(judge.get("is_too_long")) or _reply_too_long(reply):
        performance["too_verbose_count"] = int(performance.get("too_verbose_count") or 0) + 1
    if judge.get("answered_user_question") is False:
        performance["unanswered_question_count"] = int(performance.get("unanswered_question_count") or 0) + 1
        conversation["last_unanswered_question"] = str(
            judge.get("last_unanswered_question")
            or conversation.get("last_user_question")
            or ""
        )
    elif conversation.get("last_unanswered_question") and _has_any(reply, ["可以", "是", "不", "费用", "区别", "路径", "配置", "稍后"]):
        conversation["last_unanswered_question"] = ""
    if bool(judge.get("is_off_topic")):
        performance["off_topic_count"] = int(performance.get("off_topic_count") or 0) + 1
    if bool(judge.get("is_repetitive")):
        performance["repeat_count"] = int(performance.get("repeat_count") or 0) + 1
    if bool(judge.get("jumped_step")) or bool(judge.get("is_jump_step")):
        performance["jump_step_count"] = int(performance.get("jump_step_count") or 0) + 1

    conversation["last_model_action"] = _infer_model_action(reply)
    conversation["short_summary"] = _short_summary_after_model(result, reply)
    unfinished["next_best_action"] = _next_best_action(result)
    interaction = result["interaction_memory"]
    if interaction.get("interrupted") and reply:
        interaction["next_best_action"] = "回答后回到原流程"
    return result


def update_memory_from_snapshot(
    memory: Dict[str, Any],
    snapshot: Dict[str, Any],
    history: List[Dict[str, Any]] | None = None,
    user_turn: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Map the per-message runtime snapshot into the stable run model shape."""

    result = _normalize_memory(memory)
    flow = snapshot.get("flow_memory") or {}
    branch = snapshot.get("user_branch_memory") or {}
    performance = snapshot.get("model_performance_memory") or {}
    unfinished = snapshot.get("unfinished_items_memory") or {}
    history = history or []
    last = history[-1] if history else {}

    result["flow_memory"] = {
        "current_stage": flow.get("current_stage") or result["flow_memory"]["current_stage"] or "start",
        "completed_stages": _dedupe(flow.get("covered_steps") or result["flow_memory"]["completed_stages"]),
        "pending_stages": _dedupe(flow.get("pending_steps") or result["flow_memory"]["pending_stages"]),
        "skipped_stages": _dedupe(result["flow_memory"].get("skipped_stages", [])),
    }

    result["user_branch_memory"] = _course_branch_memory(branch, result["user_branch_memory"])
    result["model_performance_memory"] = {
        "too_verbose_count": len(performance.get("verbose_turns") or []),
        "unanswered_question_count": len(performance.get("unanswered_turns") or []),
        "repeat_count": len(performance.get("repeated_turns") or []),
        "jump_step_count": len(performance.get("jumped_steps") or []),
        "interrupted_count": len(performance.get("interrupted_turns") or []),
        "off_topic_count": len(performance.get("cross_task_terms") or []),
        "constraint_violation_count": len(performance.get("constraint_violations") or []),
    }

    forbidden_hits = list(performance.get("constraint_violations") or [])
    forbidden_hits.extend(
        str(item.get("term"))
        for item in performance.get("cross_task_terms") or []
        if isinstance(item, dict) and item.get("term")
    )
    next_best = unfinished.get("next_suggested_step") or unfinished.get("next_user_prompt") or ""
    result["unfinished_memory"] = {
        "required_rules_done": _dedupe(flow.get("covered_steps") or []),
        "required_rules_pending": _dedupe(unfinished.get("required_pending") or flow.get("pending_steps") or []),
        "forbidden_rules_hit": _dedupe(forbidden_hits),
        "next_best_action": str(next_best or ""),
    }

    user_text = str(last.get("user_message", "") or "")
    assistant_text = str(last.get("assistant_message", "") or "")
    intent = str((user_turn or {}).get("intent") or "")
    result["conversation_memory"] = {
        "last_user_intent": intent,
        "last_user_question": user_text if "？" in user_text or "?" in user_text else "",
        "last_model_action": _infer_model_action(assistant_text),
        "last_unanswered_question": _last_unanswered_question(user_text, assistant_text),
        "short_summary": snapshot.get("summary") or result["conversation_memory"].get("short_summary", ""),
    }
    return result


def _default_memory() -> Dict[str, Any]:
    return {
        "run_context": {
            "run_seed": 0,
            "variant_id": 0,
        },
        "flow_memory": {
            "current_stage": "start",
            "completed_stages": [],
            "pending_stages": [],
            "skipped_stages": [],
        },
        "user_branch_memory": {
            "is_responsible_person": None,
            "knows_feature": None,
            "is_busy": False,
            "is_driving": False,
            "publish_channel": None,
            "can_see_option": None,
            "cares_about_price": False,
            "can_add_wecom": None,
        },
        "model_performance_memory": {
            "too_verbose_count": 0,
            "unanswered_question_count": 0,
            "repeat_count": 0,
            "jump_step_count": 0,
            "interrupted_count": 0,
            "off_topic_count": 0,
            "constraint_violation_count": 0,
        },
        "unfinished_memory": {
            "required_rules_done": [],
            "required_rules_pending": [],
            "forbidden_rules_hit": [],
            "next_best_action": "",
        },
        "conversation_memory": {
            "last_user_intent": "",
            "last_user_question": "",
            "last_model_action": "",
            "last_unanswered_question": "",
            "short_summary": "",
        },
        "interaction_memory": {
            "current_step": "",
            "interrupted": False,
            "interrupted_from_step": "",
            "last_user_question": "",
            "pending_return_step": "",
            "user_event": "normal",
            "is_busy": False,
            "is_driving": False,
            "should_continue": True,
            "next_best_action": "",
        },
    }


def flow_current_stage(memory: Dict[str, Any]) -> str:
    return str((memory.get("flow_memory") or {}).get("current_stage") or "")


def _normalize_memory(memory: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _default_memory()
    if not isinstance(memory, dict):
        return normalized
    for section, defaults in normalized.items():
        incoming = memory.get(section)
        if isinstance(incoming, dict):
            section_value = deepcopy(defaults)
            for key in defaults:
                if key in incoming:
                    section_value[key] = incoming[key]
            normalized[section] = section_value
    return normalized


def _course_branch_memory(branch: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(current)
    if "is_owner" in branch:
        result["is_responsible_person"] = branch.get("is_owner")
    awareness = branch.get("awareness")
    if awareness == "known":
        result["knows_feature"] = True
    elif awareness == "unknown":
        result["knows_feature"] = False
    result["is_busy"] = bool(branch.get("busy", result.get("is_busy", False)))
    result["is_driving"] = bool(branch.get("driving", result.get("is_driving", False)))
    if branch.get("publish_method") is not None:
        result["publish_channel"] = branch.get("publish_method")
    if branch.get("low_latency_visible") is not None:
        result["can_see_option"] = branch.get("low_latency_visible")
    result["cares_about_price"] = bool(branch.get("fee_focus", result.get("cares_about_price", False)))
    if branch.get("enterprise_wechat_addable") is not None:
        result["can_add_wecom"] = branch.get("enterprise_wechat_addable")
    return result


def _list_field(obj: Any, field_name: str) -> List[str]:
    if isinstance(obj, dict):
        value = obj.get(field_name)
    else:
        value = getattr(obj, field_name, None)
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _first_pending_action(case: Any, pending_rules: List[str]) -> str:
    expected_steps = _list_field(case, "expected_steps")
    if expected_steps:
        return expected_steps[0]
    if pending_rules:
        return pending_rules[0]
    return ""


def _infer_model_action(text: str) -> str:
    if not text:
        return ""
    if _has_any(text, ["稍后再打", "先挂"]):
        return "结束或约定稍后联系"
    if _has_any(text, ["请问", "吗", "是否"]):
        return "提问确认"
    if _has_any(text, ["说明", "新增", "发布页", "合同", "高峰", "费用"]):
        return "说明规则或信息"
    return "普通回复"


def _last_unanswered_question(user_text: str, assistant_text: str) -> str:
    if not ("？" in user_text or "?" in user_text):
        return ""
    if not assistant_text:
        return user_text
    return ""


def _rules_from(judge_result: Dict[str, Any], *keys: str) -> List[str]:
    values: List[str] = []
    for key in keys:
        raw = judge_result.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            values.append(raw.strip())
    return _dedupe(values)


def _infer_user_intent(text: str) -> str:
    if _has_any(text, ["开车", "路上", "不方便说"]):
        return "开车不方便沟通"
    if _has_any(text, ["忙", "没时间", "说重点"]):
        return "忙碌要求简短"
    if _has_any(text, ["不是负责人", "非负责人", "前台"]):
        return "非负责人要求转达"
    if _has_any(text, ["区别", "差多少", "延迟", "互动"]):
        return "询问直播区别"
    if _has_any(text, ["费用", "价格", "贵", "优惠券", "折扣"]):
        return "关注费用"
    if _has_any(text, ["看不到", "没显示", "未显示", "没有选项", "第三方"]):
        return "反馈选项不可见"
    if _has_any(text, ["企业微信", "手机号", "加不了", "不能加"]):
        return "确认企业微信添加"
    if "？" in text or "?" in text:
        return "追问问题"
    return "普通回应"


def _major_question(text: str) -> str:
    if not text:
        return ""
    if _has_any(text, ["区别", "差多少", "延迟", "互动"]):
        return "标准直播和低延迟直播有什么区别"
    if _has_any(text, ["费用", "价格", "贵"]):
        return "费用是否更高"
    if _has_any(text, ["看不到", "没显示", "未显示", "没有选项", "第三方"]):
        return "看不到低延迟选项怎么办"
    if _has_any(text, ["企业微信", "手机号", "加不了", "不能加"]):
        return "企业微信如何添加"
    if _has_any(text, ["排名", "名额", "资格", "站长"]):
        return "飞毛腿排名和资格规则"
    if _has_any(text, ["退出", "取消"]):
        return "如何取消或退出"
    if "？" in text or "?" in text:
        return text
    return ""


def _next_best_action(memory: Dict[str, Any]) -> str:
    branch = memory.get("user_branch_memory") or {}
    unfinished = memory.get("unfinished_memory") or {}
    conversation = memory.get("conversation_memory") or {}
    pending = list(unfinished.get("required_rules_pending") or [])
    intent = str(conversation.get("last_user_intent") or "")
    question = str(conversation.get("last_user_question") or "")

    if branch.get("is_driving"):
        return "礼貌说明稍后再打并结束"
    if branch.get("is_busy"):
        return "用一句话简短说明重点并给发言机会"
    if "直播区别" in intent or "区别" in question:
        return "简短说明标准直播和低延迟直播区别"
    if branch.get("cares_about_price") or "费用" in intent:
        return "简短说明费用差异并避免承诺优惠"
    if branch.get("can_see_option") is False or branch.get("publish_channel") in {"third_party", "saas_system_b", "school_system_a"}:
        return "按发布渠道给出配置路径或说明明天再查看"
    if branch.get("can_add_wecom") is False:
        return "请用户提供可添加企业微信的手机号"
    if pending:
        return f"自然推进下一个未完成流程：{pending[0]}"
    return ""


def _reply_too_long(text: str) -> bool:
    compact = "".join(str(text or "").split())
    return len(compact) > 42


def _short_summary_after_user(text: str, intent: str) -> str:
    if not text:
        return ""
    return f"用户表示：{intent}。"


def _short_summary_after_model(memory: Dict[str, Any], reply: str) -> str:
    stage = (memory.get("flow_memory") or {}).get("current_stage") or "start"
    action = _infer_model_action(reply)
    next_action = (memory.get("unfinished_memory") or {}).get("next_best_action") or ""
    if next_action:
        return f"当前阶段 {stage}，模型动作：{action}，下一步：{next_action}。"
    return f"当前阶段 {stage}，模型动作：{action}。"


def _has_any(text_value: str, keywords: Iterable[str]) -> bool:
    return any(keyword and keyword in text_value for keyword in keywords)


def _dedupe(values: Iterable[Any]) -> List[Any]:
    result: List[Any] = []
    for value in values or []:
        if value not in result:
            result.append(value)
    return result
