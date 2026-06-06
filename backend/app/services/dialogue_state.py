from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Dict, List

from app.services.rider_flow import rider_rank_qualification_done


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
        "单日合同生效当天必须完成 X 单",
        "单日合同当天X单",
        "单日当天X单",
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
            ("已说明合同已生效", ["合同已生效", "合同今天已生效", "合同已签署", "签署并生效"]),
            ("已提醒高峰上线", ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]),
            ("已询问是否开始配送", ["开始配送", "可以配送吗", "可以开始配送", "方便开始配送", "能跑吗", "今天能跑", "能不能跑"]),
            ("已说明 X 单/Y 单", ["X 单", "X单", "Y 单", "Y单", "单日合同", "多日合同", "单日当天", "多日每天", "每天必须完成"]),
            ("已说明合同和派单影响", ["合同及派单", "合同和派单", "影响派单", "影响合同", "合同派单", "可能受影响", "影响后续合同"]),
            ("已安抚无法配送", ["理解", "先说明影响", "帮你记录", "确实跑不了"]),
            ("已提醒安全", ["安全第一", "注意安全", "跑单注意安全", "配送路上注意安全", "能跑再接单"]),
            ("已提醒少拒单取消超时", ["少拒单", "少取消", "别超时", "减少拒单", "取消和超时"]),
            ("已说明天气资格", ["雨天", "单量更多", "保资格", "保住资格"]),
            ("已说明排名规则", ["按排名", "系统排名", "名额按系统排名", "不是站长干预", "不是站长人工干预", "非站长", "非站长干预"]),
            ("已说明退出流程", ["前一天", "Z 点", "Z点", "App", "报名页", "飞毛腿报名"]),
            ("已说明奖励规则", ["连续 W 天", "连续W天", "W 天", "W天", "额外奖励", "每单多 +$", "每单多+$", "+$"]),
            ("已说明名额紧张", ["名额紧张", "名额", "被他人占用", "尽量跑"]),
            ("已说明超出范围回电", ["同事确认", "再回电"]),
            ("已结束通话", ["后续有问题再联系", "注意安全"]),
        ]
    elif task_type == "course_platform_outbound":
        checks = [
            ("已确认负责人", ["负责人", "请问您是负责人", "您是负责人"]),
            ("已请非负责人转达", ["转达负责人", "帮忙转达", "请您转达", "帮您转达"]),
            ("已询问知情", ["了解低延迟直播吗", "知道低延迟直播吗", "是否知道低延迟", "是否了解低延迟", "后台已走低延迟", "您知道吗"]),
            ("已说明发布页升级", ["直播产品升级", "产品升级", "发布页", "新增", "两个选项", "低延迟选项"]),
            ("已说明标准直播延迟", ["5-10 秒", "5-10秒", "5到10秒", "标准延迟", "标准直播延迟"]),
            ("已说明低延迟直播延迟", ["1-2 秒", "1-2秒", "1到2秒", "低延迟约", "低延迟1-2秒"]),
            ("已说明互动场景", ["互动课", "互动更流畅", "大班课", "小班", "实操", "建议低延迟", "标准直播"]),
            ("已询问发布方式", ["Web 控制台", "Web还是第三方", "Web、校务", "校务A", "校务系统", "SaaS", "第三方系统", "发布方式"]),
            ("已询问前端是否可见", ["已显示吗", "是否已显示", "页面显示了吗", "低延迟已显示吗"]),
            ("已说明 Web 控制台路径", ["Web 控制台显示后", "Web 可直接选", "Web可直接选择", "直接选择"]),
            (
                "已说明第三方系统路径",
                ["进【我的】", "进入【我的】", "直播平台管理", "选择【直播平台】", "勾选低延迟", "服务产品", "保存"],
            ),
            ("已询问学员端费用", ["学员端有附加费吗", "是否设置了直播线路附加费", "直播线路附加费"]),
            ("已说明费用差异", ["费用", "略高", "页面为准", "学员端费用", "加速线路费", "加速费", "已设置也确认"]),
            ("已拒绝优惠券承诺", ["优惠券我不能承诺", "不能承诺"]),
            ("已询问企业微信号码", ["当前号码能加吗", "号码能加吗", "企业微信能加吗"]),
            ("已说明企业微信添加", ["企业微信", "加您", "通过验证", "请验证", "手机号"]),
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
    if task_type == "rider_outbound" and rider_rank_qualification_done(text):
        topics.append("已说明排名与保资格规则")
    if task_type == "course_platform_outbound" and _has_any(text, ["5-10 秒", "5-10秒", "5到10秒", "标准延迟", "标准直播延迟"]) and _has_any(
        text,
        ["1-2 秒", "1-2秒", "1到2秒", "低延迟约", "低延迟1-2秒"],
    ) and _has_any(text, ["大班课"]) and _has_any(text, ["小班", "实操"]):
        topics.append("已说明标准直播/低延迟直播区别")
    return topics


def _user_topics(task_type: str, text: str) -> List[str]:
    topics: List[str] = []
    if task_type == "rider_outbound":
        checks = [
            ("是否能不配送", ["不想跑", "不能配送", "不送", "跑不了", "不想配送"]),
            ("不完成有什么影响", ["没完成", "X 单", "会怎么样", "会怎样", "影响", "派单"]),
            ("天气太差怎么办", ["下雨", "雨天", "天气", "安全"]),
            ("怎么退出飞毛腿", ["退出", "怎么退", "怎么取消", "取消飞毛腿", "取消报名", "飞毛腿报名", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"]),
            ("为什么排名不对", ["排名", "排不上", "报不上", "别人能报", "名额", "站长", "资格"]),
            ("奖励补贴", ["奖励", "补贴", "额外", "加钱", "激励"]),
            ("飞毛腿好处", ["好处", "优势", "有什么用", "有啥用", "为什么参加"]),
            ("职责外问题", ["平台算法", "派单少", "补贴多久到账", "工资", "保险", "工伤", "赔偿", "社保"]),
            ("犹豫配送", ["不一定", "看看情况", "有点忙", "不确定", "晚点看"]),
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
        if _has_any(last, ["开车", "路上", "不方便说"]):
            return "driver"
        if _has_any(last, ["平台算法", "派单少", "补贴多久到账", "工资", "保险", "工伤", "赔偿", "社保"]):
            return "out_of_scope"
        if _has_any(last, ["好处", "优势", "有什么用", "有啥用", "为什么参加"]):
            return "benefit"
        if _has_any(last, ["退出", "怎么退", "怎么取消", "取消飞毛腿", "取消报名", "飞毛腿报名", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"]):
            return "exit"
        if _has_any(last, ["奖励", "补贴", "额外", "多少钱", "加钱", "激励"]):
            return "reward"
        if _has_any(last, ["排名", "排不上", "报不上", "别人能报", "站长能调", "站长定", "站长干预", "名额", "保资格", "资格"]):
            return "rank"
        if _has_any(last, ["下雨", "雨天", "天气", "安全"]):
            return "weather"
        if _has_any(last, ["不想干", "不干", "不想跑", "不想配送", "不跑", "跑不了", "不送", "不能配送", "无法配送"]):
            return "reject_delivery"
        if _has_any(last, ["不一定", "看看情况", "有点忙", "忙", "不确定", "晚点看"]):
            return "hesitant_delivery"
        if _has_any(last, ["上线", "午晚", "午餐", "晚餐", "高峰", "什么时候"]):
            return "peak_online"
        if _has_any(last, ["连续", "Y 天", "Y天", "没完成", "X 单", "X单", "会怎么样", "会怎样", "影响", "多少单"]):
            return "contract_impact"
        if _has_any(last, ["合同", "生效", "开始配送", "能跑"]):
            return "start_delivery"
        if _has_any(last, ["知道了", "明白", "尽量跑", "尽量完成", "注意安全", "按要求"]):
            return "accepted"
        if _has_any(text, ["抱怨恶劣天气"]):
            return "weather"
        if _has_any(text, ["询问合同影响"]):
            return "contract_impact"
        return "opening"

    if task_type == "course_platform_outbound":
        if _has_any(last, ["开车", "路上", "不方便说"]):
            return "driver"
        if _has_any(last, ["忙", "没时间", "说重点"]):
            return "busy"
        if _has_any(last, ["知道了", "明白", "没问题", "没有", "让负责人看", "记下", "先这样"]):
            return "accepted"
        if _has_any(last, ["企业微信", "加微信", "手机号", "怎么联系", "当前号码", "能加", "加不了", "不能加", "不可添加", "可添加"]):
            return "enterprise_wechat"
        if _has_any(last, ["优惠券", "折扣", "优惠"]):
            return "coupon"
        if _has_any(last, ["费用", "价格", "贵"]):
            return "fee"
        if _has_any(last, ["升级了什么", "升级什么", "改了什么", "变了什么", "新增了什么"]):
            return "upgrade_intro"
        if _has_any(last, ["怎么用", "如何用", "怎么使用", "怎么操作", "发课时"]):
            return "usage"
        if _has_any(last, ["流程会变", "流程变", "流程"]):
            return "flow_change"
        if _has_any(last, ["不知道", "不知情", "没听过", "之前不知道", "知道"]):
            return "awareness_check"
        if _has_any(last, ["已显示", "没显示", "未显示", "看不到", "没有显示"]):
            return "visibility_check"
        if _has_any(last, ["第三方", "看不到", "SaaS", "校务"]):
            return "third_party_path"
        if _has_any(last, ["Web", "控制台"]):
            return "web_path"
        if _has_any(last, ["路径", "哪里", "怎么配置", "怎么选", "在哪里选", "选项"]):
            return "config_path"
        if _has_any(last, ["区别", "差多少", "延迟", "互动", "适合什么课", "大班", "小班", "实操", "低延迟呢", "标准呢"]):
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
    if stage == "rank":
        return rider_rank_qualification_done(assistant_text)
    answers = {
        "start_delivery": ["合同已生效", "合同已签署", "可以配送", "可以开始配送"],
        "peak_online": ["午晚高峰", "午餐", "晚餐", "高峰", "上线"],
        "contract_impact": ["X 单", "X单", "合同", "派单", "影响", "Y 单", "Y单", "连续", "名额"],
        "reject_delivery": ["理解", "影响", "记录", "跑不了"],
        "weather": ["安全第一", "雨天", "单量", "资格", "能跑"],
        "exit": ["前一天", "Z点", "App", "报名页", "飞毛腿报名", "取消"],
        "rank": ["按排名", "系统排名", "非站长", "不是站长干预"],
        "reward": ["连续", "W 天", "W天", "多日合同", "Y 单", "Y单", "额外奖励"],
        "benefit": ["资格", "保资格", "额外奖励", "奖励", "名额"],
        "hesitant_delivery": ["名额", "影响", "尽量", "高峰"],
        "out_of_scope": ["同事确认", "再回电", "能回答的先回答"],
        "non_owner": ["转达", "负责人", "发布页"],
        "owner": ["了解低延迟", "知道低延迟", "是否知道", "是否了解", "发布页", "两个选项"],
        "upgrade_intro": ["新增", "低延迟直播选项"],
        "usage": ["发课时", "选低延迟"],
        "flow_change": ["流程不变", "其他发课流程不变"],
        "awareness_check": ["独立的低延迟直播选项", "低延迟直播选项", "后台", "保障", "音画同步", "实时互动", "低延迟"],
        "live_difference": ["5-10 秒", "5-10秒", "1-2 秒", "1-2秒", "互动更流畅", "大班课", "小班", "实操"],
        "config_path": ["Web 控制台", "校务", "SaaS", "第三方系统", "发布页", "直播平台管理", "进【我的】"],
        "web_path": ["Web 控制台", "直接选择"],
        "third_party_path": ["进【我的】", "直播平台管理", "勾选低延迟", "保存", "明天再查看"],
        "visibility_check": ["直接使用", "按需选择", "明天查看", "进【我的】", "后台配置"],
        "fee": ["费用", "略高", "已设置也确认", "加速费", "附加费"],
        "coupon": ["优惠券", "不能承诺", "页面为准"],
        "enterprise_wechat": ["企业微信", "加您", "通过验证", "手机号", "当前号码"],
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
