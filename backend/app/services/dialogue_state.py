from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, List


def analyze_dialogue_state(
    task: Dict[str, Any],
    case: Dict[str, Any],
    messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    task_type = _infer_task_type(task, case)
    last = messages[-1] if messages else {}
    last_user_message = str(last.get("user_message", "") or "")
    last_assistant_message = _last_assistant(messages)
    assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in messages)
    user_text = "\n".join(str(item.get("user_message", "") or "") for item in messages)
    assistant_said_topics = _assistant_topics(task_type, assistant_text)
    user_asked_topics = _user_topics(task_type, user_text)
    current_stage = _current_stage(task_type, last_user_message, case)
    answered_user_question = _answered_question(current_stage, last_assistant_message)
    should_close = _should_close(current_stage, last_user_message, last_assistant_message)

    return {
        "turn_index": len(messages) or 1,
        "task_type": task_type,
        "last_user_message": last_user_message,
        "last_assistant_message": last_assistant_message,
        "assistant_said_topics": assistant_said_topics,
        "user_asked_topics": user_asked_topics,
        "current_stage": current_stage,
        "answered_user_question": answered_user_question,
        "should_close": should_close,
    }


def is_similar_text(left: str, right: str) -> bool:
    left = (left or "").strip()
    right = (right or "").strip()
    if not left or not right:
        return False
    if left == right:
        return True
    if left[:8] == right[:8] and abs(len(left) - len(right)) <= 8:
        return True
    core_patterns = [
        "理解，安全第一",
        "标准直播和低延迟直播",
        "麻烦您帮忙转达负责人",
        "单日需完成 X 单",
        "飞毛腿合同已生效",
        "您是用 Web 控制台还是第三方系统",
    ]
    if any(pattern in left and pattern in right for pattern in core_patterns):
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.86


def _assistant_topics(task_type: str, text: str) -> List[str]:
    topics: List[str] = []
    if task_type == "rider_outbound":
        checks = [
            ("已说明合同已生效", ["合同已生效", "合同今天已生效"]),
            ("已询问是否开始配送", ["开始配送", "可以开始配送"]),
            ("已说明 X 单/Y 单", ["X 单", "Y 单", "单日", "多日", "每天完成"]),
            ("已说明合同和派单影响", ["合同和派单", "影响派单", "影响合同", "可能受影响"]),
            ("已安抚无法配送", ["理解", "先说明影响", "帮你记录", "确实跑不了"]),
            ("已提醒安全", ["安全第一", "注意安全", "能跑再接单"]),
            ("已说明天气资格", ["雨天", "单量更多", "保资格", "保住资格"]),
            ("已说明排名规则", ["按排名", "不是站长干预", "非站长干预"]),
            ("已说明退出流程", ["前一天", "Z 点", "App", "报名页", "取消"]),
            ("已说明超出范围回电", ["同事确认", "再回电"]),
            ("已结束通话", ["后续有问题再联系", "注意安全"]),
        ]
    elif task_type == "course_platform_outbound":
        checks = [
            ("已确认负责人", ["负责人", "请问您是负责人", "您是负责人"]),
            ("已请非负责人转达", ["转达负责人", "帮忙转达", "请您转达", "帮您转达"]),
            ("已说明发布页升级", ["发布页", "新增", "两个选项", "低延迟选项"]),
            ("已说明标准直播/低延迟直播区别", ["5-10 秒", "1-2 秒", "标准延迟", "低延迟"]),
            ("已说明互动场景", ["互动课", "大班课", "建议低延迟", "标准直播"]),
            ("已询问发布方式", ["Web 控制台", "第三方系统", "发布方式"]),
            ("已说明 Web 控制台路径", ["Web 控制台显示后", "Web 可直接选", "直接选择"]),
            ("已说明第三方系统路径", ["直播平台管理", "勾选低延迟直播", "服务产品"]),
            ("已说明费用差异", ["费用", "略高", "页面为准"]),
            ("已拒绝优惠券承诺", ["优惠券我不能承诺", "不能承诺"]),
            ("已说明稍后再打", ["稍后再打", "注意安全"]),
            ("已结束通话", ["祝课程顺利", "后续可再联系"]),
        ]
    else:
        checks = [
            ("已说明外呼目的", ["外呼", "沟通", "说明"]),
            ("已推进下一步", ["下一步", "继续", "确认"]),
            ("已结束通话", ["后续", "再联系"]),
        ]
    for topic, keywords in checks:
        if _has_any(text, keywords):
            topics.append(topic)
    return topics


def _user_topics(task_type: str, text: str) -> List[str]:
    topics: List[str] = []
    if task_type == "rider_outbound":
        checks = [
            ("是否能不配送", ["不想跑", "不能配送", "不送", "跑不了", "不想配送"]),
            ("不完成有什么影响", ["没完成", "X 单", "会怎么样", "会怎样", "影响", "派单"]),
            ("天气太差怎么办", ["下雨", "雨天", "天气", "安全"]),
            ("怎么退出飞毛腿", ["退出", "取消", "怎么退"]),
            ("为什么排名不对", ["排名", "排不上", "报不上", "别人能报"]),
            ("合同是否生效/能否开始", ["合同", "生效", "开始配送", "能跑"]),
            ("已经接受", ["知道了", "明白", "尽量跑", "注意安全", "按要求"]),
        ]
    elif task_type == "course_platform_outbound":
        checks = [
            ("是否负责人", ["负责人", "前台", "不是负责人"]),
            ("标准直播和低延迟区别", ["区别", "差多少", "延迟", "互动"]),
            ("具体配置路径", ["路径", "哪里", "怎么配置", "第三方", "Web", "看不到", "选项"]),
            ("费用问题", ["费用", "价格", "贵"]),
            ("优惠券问题", ["优惠券", "折扣", "优惠"]),
            ("开车/忙碌", ["开车", "忙", "没时间"]),
            ("已经接受", ["知道了", "明白", "没问题", "让负责人看", "记下"]),
        ]
    else:
        checks = [
            ("追问下一步", ["下一步", "怎么做", "怎么办"]),
            ("已经接受", ["知道了", "明白", "没问题"]),
        ]
    for topic, keywords in checks:
        if _has_any(text, keywords):
            topics.append(topic)
    return topics


def _current_stage(task_type: str, last_user_message: str, case: Dict[str, Any]) -> str:
    text = " ".join(
        [
            str(case.get("name", "") or ""),
            str(case.get("user_profile", "") or ""),
            str(case.get("initial_message", "") or ""),
            last_user_message,
        ]
    )
    last = last_user_message
    if task_type == "rider_outbound":
        if _has_any(last, ["知道了", "明白", "尽量跑", "注意安全", "按要求"]):
            return "accepted"
        if _has_any(last, ["退出", "取消", "怎么退"]):
            return "exit"
        if _has_any(last, ["排名", "排不上", "报不上", "别人能报", "站长能调"]):
            return "rank"
        if _has_any(last, ["下雨", "雨天", "天气", "安全"]):
            return "weather"
        if _has_any(last, ["不想跑", "不想配送", "不跑", "跑不了", "不送", "不能配送", "无法配送"]):
            return "reject_delivery"
        if _has_any(last, ["没完成", "X 单", "X单", "会怎么样", "会怎样", "影响", "多少单"]):
            return "contract_impact"
        if _has_any(last, ["合同", "生效", "开始配送", "能跑"]):
            return "start_delivery"
        if _has_any(text, ["抱怨恶劣天气"]):
            return "weather"
        if _has_any(text, ["询问合同影响"]):
            return "contract_impact"
        return "opening"

    if task_type == "course_platform_outbound":
        if _has_any(last, ["知道了", "明白", "没问题", "让负责人看", "记下", "先这样"]):
            return "accepted"
        if _has_any(last, ["开车", "路上", "不方便说"]):
            return "driver"
        if _has_any(last, ["忙", "没时间", "说重点"]):
            return "busy"
        if _has_any(last, ["优惠券", "折扣", "优惠"]):
            return "coupon"
        if _has_any(last, ["费用", "价格", "贵"]):
            return "fee"
        if _has_any(last, ["第三方", "看不到"]):
            return "third_party_path"
        if _has_any(last, ["Web", "控制台"]):
            return "web_path"
        if _has_any(last, ["路径", "哪里", "怎么配置", "怎么选", "在哪里选", "选项"]):
            return "config_path"
        if _has_any(last, ["区别", "差多少", "延迟", "互动"]):
            return "live_difference"
        if _has_any(last, ["不是负责人", "非负责人", "前台", "转达"]):
            return "non_owner"
        if _has_any(last, ["我是负责人", "负责人"]):
            return "owner"
        if _has_any(text, ["追问直播区别"]):
            return "live_difference"
        if _has_any(text, ["商家说在开车"]):
            return "driver"
        return "opening"
    if _has_any(last_user_message, ["知道了", "明白", "没问题"]):
        return "accepted"
    return "opening"


def _answered_question(stage: str, assistant_text: str) -> bool:
    if not assistant_text:
        return False
    answers = {
        "start_delivery": ["合同已生效", "可以开始配送"],
        "contract_impact": ["X 单", "合同", "派单", "影响", "Y 单"],
        "reject_delivery": ["理解", "影响", "记录", "跑不了"],
        "weather": ["安全第一", "雨天", "单量", "资格", "能跑"],
        "exit": ["前一天", "App", "报名页", "取消"],
        "rank": ["按排名", "不是站长干预"],
        "non_owner": ["转达", "负责人", "发布页"],
        "owner": ["发布页", "两个选项"],
        "live_difference": ["5-10 秒", "1-2 秒", "互动课", "大班课"],
        "config_path": ["Web 控制台", "第三方系统", "发布页", "直播平台管理"],
        "web_path": ["Web 控制台", "直接选择"],
        "third_party_path": ["直播平台管理", "勾选低延迟直播"],
        "fee": ["费用", "略高"],
        "coupon": ["优惠券", "不能承诺", "页面为准"],
        "busy": ["1 分钟", "简短"],
        "driver": ["稍后再打", "注意安全"],
        "accepted": ["后续", "祝课程顺利", "注意安全"],
    }
    return _has_any(assistant_text, answers.get(stage, []))


def _should_close(stage: str, last_user_message: str, last_assistant_message: str) -> bool:
    if stage == "driver" and _has_any(last_assistant_message, ["稍后再打", "注意安全"]):
        return True
    if stage == "accepted":
        return True
    return _has_any(
        last_assistant_message,
        ["祝课程顺利", "后续可再联系", "后续有问题再联系", "先这样"],
    ) or _has_any(last_user_message, ["先这样", "不用继续"])


def _last_assistant(messages: List[Dict[str, Any]]) -> str:
    for item in reversed(messages):
        text = str(item.get("assistant_message", "") or "")
        if text:
            return text
    return ""


def _infer_task_type(task: Dict[str, Any], case: Dict[str, Any]) -> str:
    task_type = (task.get("task_type") or "").strip()
    if task_type:
        return task_type
    text = " ".join(
        str(value or "")
        for value in [
            task.get("instruction_text", ""),
            task.get("name", ""),
            task.get("target_scenario", ""),
            case.get("name", ""),
            case.get("initial_message", ""),
        ]
    )
    if _has_any(text, ["飞毛腿", "骑手", "配送", "派单"]):
        return "rider_outbound"
    if _has_any(text, ["课程", "直播", "低延迟", "机构", "负责人"]):
        return "course_platform_outbound"
    return "generic_outbound"


def _has_any(text: str, keywords: List[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)
