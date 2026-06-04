from __future__ import annotations

from typing import Any, Iterable, List

from app.services.case_mode import normalize_case_mode


COURSE_FULL_FLOW_CASE_NAME = "课程直播产品升级外呼用例"

COURSE_FULL_FLOW_EXPECTED_STEPS: List[str] = [
    "身份确认",
    "确认是否知情",
    "传达升级内容",
    "说明标准直播和低延迟直播区别",
    "说明价格差异",
    "询问发布方式",
    "确认前端是否可见并说明配置路径",
    "检查学员端费用/加速线路费",
    "企业微信添加",
    "结束确认",
]

COURSE_CRITICAL_STEPS_BEFORE_STOP = {
    "确认是否知情",
    "传达升级内容",
    "询问发布方式",
    "确认前端是否可见并说明配置路径",
    "企业微信添加",
}

_LEGACY_FULL_FLOW_MARKERS = {
    "产品升级说明",
    "根据发布方式给配置路径",
    "负责人正常沟通",
    "说明标准直播和低延迟直播区别",
}


def course_full_flow_expected_steps(configured: Iterable[str], case_payload: dict[str, Any]) -> List[str]:
    configured_steps = [str(item).strip() for item in configured or [] if str(item).strip()]
    case_mode = normalize_case_mode(case_payload.get("case_mode"), case_payload)
    if case_mode == "full_flow" or any(step in _LEGACY_FULL_FLOW_MARKERS for step in configured_steps):
        return list(COURSE_FULL_FLOW_EXPECTED_STEPS)
    return configured_steps or list(COURSE_FULL_FLOW_EXPECTED_STEPS)


def course_full_flow_step_done(step: str, user_text: str, assistant_text: str, said: set[str] | None = None) -> bool:
    said = said or set()
    combined = f"{user_text}\n{assistant_text}"
    checks = {
        "身份确认": _has_any(combined, ["负责人", "转达"]),
        "产品升级说明": _has_any(assistant_text, ["直播产品升级", "产品升级", "发布页", "新增", "两个选项", "升级"]),
        "确认是否知情": _has_any(user_text, ["知道", "已知情", "不知情", "不知道", "没听过", "之前不知道"]),
        "传达升级内容": _has_any(assistant_text, ["低延迟直播选项", "新增低延迟", "标准直播和低延迟直播", "两个选项"])
        and _has_any(assistant_text, ["低延迟"]),
        "说明标准直播和低延迟直播区别": (
            "已说明标准直播/低延迟直播区别" in said
            or (
                _has_any(assistant_text, ["5-10 秒", "5-10秒", "5到10秒", "标准直播延迟", "标准费用低", "标准直播费用低"])
                and _has_any(assistant_text, ["1-2 秒", "1-2秒", "1到2秒", "低延迟约", "低延迟1-2秒"])
                and _has_any(assistant_text, ["大班课"])
                and _has_any(assistant_text, ["小班", "实操"])
            )
        ),
        "说明直播区别": (
            "已说明标准直播/低延迟直播区别" in said
            or (
                _has_any(assistant_text, ["5-10 秒", "5-10秒", "5到10秒"])
                and _has_any(assistant_text, ["1-2 秒", "1-2秒", "1到2秒"])
                and _has_any(assistant_text, ["大班课"])
                and _has_any(assistant_text, ["小班", "实操"])
            )
        ),
        "说明价格差异": _has_any(assistant_text, ["标准更便宜", "费用略高", "费用可能更高", "费用较低", "略高"]),
        "询问发布方式": _has_any(assistant_text, ["Web", "控制台", "校务系统", "SaaS", "发布方式", "第三方系统", "Web还是第三方"]),
        "根据发布方式给配置路径": _has_any(
            assistant_text,
            ["进【我的】", "直播平台管理", "勾选低延迟", "Web 控制台可直接", "直接选择", "明天再查看", "后台可能未配置"],
        ),
        "确认前端是否可见并说明配置路径": _has_any(
            assistant_text,
            [
                "直接使用",
                "按需选择",
                "Web 可直接",
                "Web可直接",
                "Web 控制台可直接",
                "勾选低延迟",
                "保存",
                "明天再查看",
                "明天查看",
                "后台可能未配置",
            ],
        ),
        "检查费用/加速线路费": _has_any(user_text, ["已设置费用", "没设置费用", "未设置费用", "不会配置", "附加费"])
        or _has_any(assistant_text, ["适用该费用", "教务/财务设置", "收费规则"]),
        "检查学员端费用/加速线路费": _has_any(user_text, ["已设置费用", "没设置费用", "未设置费用", "不会配置", "附加费"])
        or _has_any(assistant_text, ["适用该费用", "教务/财务设置", "收费规则"]),
        "企业微信添加": _has_any(user_text, ["当前号码能加", "这个号加不了", "可添加手机号"])
        or _has_any(assistant_text, ["企业微信加", "通过验证", "请验证", "请提供可添加手机号"]),
        "结束确认": _has_any(combined, ["没问题", "还有问题", "是否还有", "祝课程顺利", "后续可再联系", "先这样", "招生满满"]),
    }
    return bool(checks.get(step, False))


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)
