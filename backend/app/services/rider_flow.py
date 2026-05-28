from __future__ import annotations

from typing import Any, Iterable, List

from app.services.case_mode import normalize_case_mode


RIDER_FULL_FLOW_EXPECTED_STEPS: List[str] = [
    "确认身份",
    "告知今天飞毛腿合同已生效",
    "说明午晚高峰和单量要求",
    "询问是否可以开始配送",
    "根据骑手态度鼓励挽留或安抚",
    "提醒注意安全",
    "说明排名与保资格规则",
    "结束确认",
]

RIDER_CRITICAL_STEPS_BEFORE_STOP = {"提醒注意安全", "说明排名与保资格规则"}

_LEGACY_FULL_FLOW_MARKERS = {
    "告知合同签署并询问是否开跑",
    "说明连续配送和未完成影响",
    "挽留鼓励和安全提醒",
    "回答退出规则",
    "回答奖励规则",
    "处理超出职责问题",
}


def rider_full_flow_expected_steps(configured: Iterable[str], case_payload: dict[str, Any]) -> List[str]:
    configured_steps = [str(item).strip() for item in configured or [] if str(item).strip()]
    case_mode = normalize_case_mode(case_payload.get("case_mode"), case_payload)
    if case_mode == "full_flow" or any(step in _LEGACY_FULL_FLOW_MARKERS for step in configured_steps):
        return list(RIDER_FULL_FLOW_EXPECTED_STEPS)
    return configured_steps or list(RIDER_FULL_FLOW_EXPECTED_STEPS)


def rider_rank_qualification_done(text: str) -> bool:
    content = str(text or "")
    return (
        _has_any(content, ["排名", "系统排名", "按排名"])
        and _has_any(
            content,
            [
                "不是站长",
                "非站长",
                "并非站长",
                "不是站长人工干预",
                "不是站长干预",
                "非站长干预",
                "站长不能干预",
                "站长不能调整",
                "不是人工干预",
                "非人工干预",
                "不是人为干预",
            ],
        )
        and _has_any(content, ["拒单", "取消", "超时"])
        and _has_any(content, ["资格", "保住资格", "名额"])
    )


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)
