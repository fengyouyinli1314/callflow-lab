from __future__ import annotations

import json
from typing import Any, Dict, List


def generate_executable_policy(task: Any) -> Dict[str, Any]:
    payload = _as_dict(task)
    task_type = str(payload.get("task_type") or _infer_task_type(payload))
    constraints = _list_field(payload.get("constraints"))
    steps = _list_field(payload.get("steps"))
    max_chars, hard_limit = _reply_limits(task_type, constraints)
    base = {
        "reply_rules": {
            "max_chars_per_reply": max_chars,
            "hard_limit_chars": hard_limit,
            "one_assistant_message_per_turn": True,
            "wait_user_after_each_reply": True,
            "no_multi_step_in_one_reply": True,
            "no_consecutive_assistant_messages": True,
            "style": "简短、自然、口语化、电话沟通风格",
        },
        "global_priority_rules": [],
        "step_policies": [],
        "branch_policies": [],
        "forbidden_rules": [],
        "memory_fields": [],
        "examples": [],
        "source": {
            "task_type": task_type,
            "steps_count": len(steps),
            "constraints_count": len(constraints),
        },
    }
    if task_type == "course_platform_outbound":
        return _course_policy(base, steps)
    if task_type == "rider_outbound":
        return _rider_policy(base, steps)
    return _generic_policy(base, steps)


def _course_policy(policy: Dict[str, Any], steps: List[Any]) -> Dict[str, Any]:
    policy["global_priority_rules"] = [
        {
            "priority": 1,
            "name": "商家说在开车",
            "condition": "用户表示在开车、不方便接电话、开车中",
            "action": "立即停止当前流程",
            "reply": "那我稍后再打。",
            "should_continue": False,
            "forbidden": ["不允许继续介绍直播产品", "不允许继续推进 Step"],
        },
        {
            "priority": 2,
            "name": "商家说忙",
            "condition": "用户表示忙、没时间、不方便听",
            "action": "先简短挽留",
            "reply": "就1分钟，保证简短。",
            "should_continue": True,
            "note": "说完后必须等待用户回应；如果用户仍拒绝，则礼貌结束",
        },
        {
            "priority": 3,
            "name": "用户打断",
            "condition": "用户打断、纠正、追问、说“等等”",
            "action": "停止当前 Step，先回应打断点",
            "transition_examples": ["您刚才问区别，对吗？", "我刚说到直播选项。"],
            "note": "不允许强行继续原 Step",
        },
        {
            "priority": 4,
            "name": "用户提出问题",
            "condition": "用户问区别、费用、怎么配置、在哪里看、优惠券、企业微信等",
            "action": "先回答用户问题",
            "note": "回答后暂停等待用户回应，不要同一轮继续推进多个 Step",
        },
        {
            "priority": 5,
            "name": "用户正常配合",
            "condition": "用户正常回答、表示继续",
            "action": "按当前 Step 推进",
        },
    ]
    policy["step_policies"] = [
        {
            "step_no": "1",
            "title": _step_title(steps, "1", "身份确认"),
            "assistant": "您是机构负责人吗？",
            "branches": [
                {"condition": "用户是负责人", "next_step": "2"},
                {"condition": "用户不是负责人", "assistant": "麻烦转达负责人一下。", "wait_user": True},
                {"condition": "用户不方便", "assistant": "那我稍后再打。", "should_continue": False},
            ],
        },
        {
            "step_no": "2",
            "title": _step_title(steps, "2", "确认是否知情"),
            "sequence": [
                {"assistant": "您之前选标准直播，对吗？", "wait_user": True},
                {"assistant": "后台已走低延迟，您知道吗？", "wait_user": True},
            ],
            "branches": [
                {"condition": "用户不知道", "assistant": "前端暂未开放，为保障同步。", "wait_user": True, "next_step": "3"},
                {"condition": "用户知道", "assistant": "之后会显示两个选项。", "next_step": "3"},
            ],
        },
        {
            "step_no": "3",
            "title": _step_title(steps, "3", "传达升级内容"),
            "assistant": "之后会显示两个选项。",
            "branch_replies": [
                {"condition": "用户问哪两个", "assistant": "标准直播和低延迟直播。"},
                {"condition": "用户问有什么区别", "assistant": "标准便宜，适合大班课。"},
                {"condition": "用户追问低延迟", "assistant": "互动更顺，适合小班课。"},
                {"condition": "用户问低延迟延迟", "assistant": "低延迟约1到2秒。"},
                {"condition": "用户问标准直播延迟", "assistant": "标准约5到10秒。"},
                {"condition": "用户问价格", "assistant": "标准更便宜。"},
                {"condition": "用户问低延迟费用", "assistant": "低延迟费用略高。"},
            ],
            "note": "不能一轮同时说完两个选项、区别、价格和适用场景。",
        },
        {
            "step_no": "4",
            "title": _step_title(steps, "4", "确认发布方式"),
            "assistant": "您用哪种方式发课？",
            "branches": [
                {"condition": "用户不清楚", "assistant": "Web还是第三方系统？"},
                {"condition": "Web 控制台已显示", "assistant": "那直接选择即可。"},
                {"condition": "Web 控制台未显示", "assistant": "后台配置后明天再看。"},
                {"condition": "第三方系统已显示", "assistant": "按需选择即可。"},
                {
                    "condition": "第三方系统未显示",
                    "guided_steps": ["先进入【我的】。", "点服务商管理。", "选择直播平台。", "勾选低延迟并保存。"],
                    "wait_user_each_step": True,
                },
            ],
        },
        {
            "step_no": "5",
            "title": _step_title(steps, "5", "费用设置"),
            "branches": [
                {"condition": "用户未设置费用", "next_step": "6"},
                {"condition": "用户已设置费用", "assistant": "低延迟也要适用费用。"},
                {
                    "condition": "用户不会配置",
                    "guided_steps": ["先进入财务设置。", "再点收费规则。", "编辑线路附加费。", "给低延迟启用。"],
                    "wait_user_each_step": True,
                },
            ],
        },
        {
            "step_no": "6",
            "title": _step_title(steps, "6", "企业微信"),
            "branches": [
                {"condition": "当前号码可添加", "assistant": "稍后企微添加您。"},
                {"condition": "需要补充验证", "assistant": "麻烦通过验证。"},
                {"condition": "当前号码不可添加", "assistant": "请给可添加手机号。"},
            ],
        },
        {
            "step_no": "7",
            "title": _step_title(steps, "7", "结束通话"),
            "branches": [
                {"condition": "用户还有问题", "action": "继续简短作答"},
                {"condition": "用户无问题", "assistant": "祝您课程顺利。", "should_continue": False},
            ],
        },
    ]
    policy["branch_policies"] = [
        {"name": "区别问题", "reply_order": ["标准便宜，适合大班课。", "互动更顺，适合小班课。"]},
        {"name": "费用问题", "reply_order": ["标准更便宜。", "低延迟费用略高。"]},
        {"name": "第三方配置", "one_step_per_turn": True},
    ]
    policy["forbidden_rules"] = [
        "不允许回复超过25个中文字符",
        "不允许一轮推进多个流程点",
        "不允许连续生成多条 assistant message",
        "不允许商家开车后继续推销",
        "不允许商家说忙后直接长篇说明",
        "不允许用户打断后继续强推原 Step",
        "不允许承诺折扣券或优惠券",
        "不允许使用“好的”“哈哈”“嘿嘿”“嘻嘻”“嗯嗯”",
        "不允许任务完成后忽略商家问题",
    ]
    policy["memory_fields"] = [
        "current_step",
        "current_sub_step",
        "is_responsible_person",
        "is_busy",
        "is_driving",
        "interrupted",
        "last_user_question",
        "publish_channel",
        "can_see_option",
        "fee_configured",
        "wecom_phone_available",
        "should_continue",
        "next_best_action",
        "required_rules_done",
        "required_rules_pending",
        "forbidden_rules_hit",
    ]
    policy["examples"] = [
        "您是机构负责人吗？",
        "您之前选标准直播，对吗？",
        "后台已走低延迟，您知道吗？",
        "之后会显示两个选项。",
        "标准直播和低延迟直播。",
    ]
    return policy


def _rider_policy(policy: Dict[str, Any], steps: List[Any]) -> Dict[str, Any]:
    policy["global_priority_rules"] = [
        {"name": "骑手说忙", "action": "简短说明重点，尽量确认是否能配送，不长篇解释"},
        {"name": "骑手拒绝配送", "action": "先挽留，说明不完成可能影响合同和派单；若坚持无法配送，安慰并结束"},
        {"name": "骑手抱怨天气", "action": "先安抚，提醒安全，不强迫恶劣天气配送"},
        {"name": "骑手问排名", "action": "说明报名按排名，不是站长干预"},
        {"name": "骑手问退出", "action": "按知识点说明退出流程，不编造其他方式"},
        {"name": "骑手问超出范围问题", "reply": "我向同事确认后再回电。"},
    ]
    policy["step_policies"] = _steps_or_default(
        steps,
        [
            {"step_no": "1", "title": "身份确认与合同生效", "assistant": "合同今天已经生效。"},
            {"step_no": "2", "title": "确认能否配送", "assistant": "您今天能开始配送吗？"},
            {"step_no": "3", "title": "完成要求与影响", "assistant": "未完成会影响合同派单。"},
            {"step_no": "4", "title": "安全与收口", "assistant": "安全第一，量力而行。"},
        ],
    )
    policy["branch_policies"] = [
        {"name": "天气抱怨分支", "assistant": "安全第一，量力而行。"},
        {"name": "拒绝配送分支", "assistant": "未完成会影响合同派单。"},
        {"name": "排名质疑分支", "assistant": "报名是按排名来的。"},
        {"name": "退出流程分支", "action": "说明前一天 Z 点前在 App 飞毛腿报名中取消，次日生效"},
        {"name": "超范围兜底分支", "assistant": "这个我确认后回电。"},
    ]
    policy["forbidden_rules"] = [
        "不允许强迫恶劣天气配送",
        "不允许承诺额外资格",
        "不允许说排名由站长决定",
        "不允许忽略骑手拒绝配送",
        "不允许长篇大论",
        "不允许重复机械回复",
        "不允许严重串场到课程直播业务",
    ]
    policy["memory_fields"] = [
        "current_step",
        "rider_identity_confirmed",
        "can_start_delivery",
        "refused_delivery",
        "asked_contract_impact",
        "asked_exit_method",
        "complained_weather",
        "questioned_ranking",
        "should_continue",
        "next_best_action",
        "required_rules_done",
        "required_rules_pending",
        "forbidden_rules_hit",
    ]
    policy["examples"] = [
        "您今天能开始配送吗？",
        "合同今天已经生效。",
        "安全第一，量力而行。",
        "报名是按排名来的。",
        "这个我确认后回电。",
    ]
    return policy


def _generic_policy(policy: Dict[str, Any], steps: List[Any]) -> Dict[str, Any]:
    policy["step_policies"] = _steps_or_default(steps, [])
    policy["memory_fields"] = ["current_step", "should_continue", "next_best_action", "required_rules_done", "required_rules_pending", "forbidden_rules_hit"]
    return policy


def _reply_limits(task_type: str, constraints: List[Any]) -> tuple[int, int]:
    text = "\n".join(str(item) for item in constraints)
    if task_type == "rider_outbound" and ("30字" in text or "30 字" in text or "三十字" in text):
        return 30, 40
    if task_type == "rider_outbound":
        return 30, 40
    if any(keyword in text for keyword in ["15-20", "15 到 20", "15至20", "极简", "暂停等待", "发言和提问"]):
        return 20, 25
    return 20, 25


def _steps_or_default(steps: List[Any], default: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not steps:
        return default
    result = []
    for step in steps:
        if isinstance(step, dict):
            result.append(
                {
                    "step_no": str(step.get("step_no") or ""),
                    "title": str(step.get("title") or ""),
                    "source_content": str(step.get("content") or ""),
                    "note": "原始步骤仅作语义参考，执行时仍按短句和等待用户规则推进。",
                }
            )
    return result or default


def _step_title(steps: List[Any], step_no: str, fallback: str) -> str:
    for step in steps:
        if isinstance(step, dict) and str(step.get("step_no") or "") == step_no:
            return str(step.get("title") or fallback)
    return fallback


def _list_field(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [line.strip() for line in value.splitlines() if line.strip()]
        return parsed if isinstance(parsed, list) else []
    return []


def _as_dict(task: Any) -> Dict[str, Any]:
    if isinstance(task, dict):
        return dict(task)
    return {
        "instruction_text": getattr(task, "instruction_text", ""),
        "task_type": getattr(task, "task_type", ""),
        "role_text": getattr(task, "role_text", ""),
        "task_text": getattr(task, "task_text", ""),
        "constraints": getattr(task, "constraints", ""),
        "opening_line": getattr(task, "opening_line", ""),
        "steps": getattr(task, "steps", ""),
        "knowledge_points": getattr(task, "knowledge_points", ""),
    }


def _infer_task_type(payload: Dict[str, Any]) -> str:
    text = " ".join(str(payload.get(key) or "") for key in ["instruction_text", "task_text", "role_text"])
    if any(keyword in text for keyword in ["飞毛腿", "骑手", "配送", "派单"]):
        return "rider_outbound"
    if any(keyword in text for keyword in ["课程", "直播", "低延迟", "机构", "负责人", "商家"]):
        return "course_platform_outbound"
    return "generic_outbound"
