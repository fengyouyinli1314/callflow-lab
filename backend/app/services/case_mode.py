from __future__ import annotations

from typing import Any, Dict


VALID_CASE_MODES = {"branch", "full_flow", "abnormal_exit"}


def normalize_case_mode(value: Any, case_payload: Dict[str, Any] | None = None) -> str:
    text = str(value or "").strip()
    if text in VALID_CASE_MODES:
        return text
    return infer_case_mode(case_payload or {})


def infer_case_mode(case_payload: Dict[str, Any]) -> str:
    text = _joined(
        case_payload.get("name", ""),
        case_payload.get("user_profile", ""),
        case_payload.get("initial_message", ""),
        case_payload.get("expected_goals", []),
        case_payload.get("required_rules", []),
        case_payload.get("trigger_conditions", []),
        case_payload.get("user_behavior_type", ""),
    )
    if _has_any(text, ["开车", "坚持无法配送", "拒绝配合", "先挂", "不方便听", "不方便说"]):
        return "abnormal_exit"
    if _has_any(text, ["负责人正常沟通", "正常愿意配送", "正常配合", "全流程", "完整流程"]):
        return "full_flow"
    return "branch"


def _joined(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif isinstance(value, dict):
            parts.append(str(value))
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts)


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)
