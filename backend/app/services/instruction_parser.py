from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple


SECTION_ALIASES = {
    "role": "role_text",
    "角色": "role_text",
    "task": "task_text",
    "任务": "task_text",
    "constraints": "constraints",
    "约束": "constraints",
    "opening line": "opening_line",
    "开场白": "opening_line",
    "conversation flow": "conversation_flow",
    "call flow": "conversation_flow",
    "对话流程": "conversation_flow",
    "通话流程": "conversation_flow",
    "流程": "conversation_flow",
    "knowledge points": "knowledge_points",
    "faq": "knowledge_points",
    "参考知识": "knowledge_points",
    "知识点": "knowledge_points",
    "常见问题": "knowledge_points",
}


def parse_instruction(instruction_text: str) -> Dict[str, Any]:
    text = _normalize_newlines(instruction_text)
    sections = _parse_sections(text)
    conversation_flow = sections.get("conversation_flow", "")
    constraints_text = sections.get("constraints", "")
    return {
        "role_text": sections.get("role_text", ""),
        "task_text": sections.get("task_text", ""),
        "constraints": _parse_constraints(constraints_text),
        "opening_line": sections.get("opening_line", ""),
        "conversation_flow": conversation_flow,
        "knowledge_points": sections.get("knowledge_points", ""),
        "steps": _parse_steps(conversation_flow),
    }


def _parse_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {value: [] for value in set(SECTION_ALIASES.values())}
    current_key = ""

    for raw_line in text.split("\n"):
        heading = _section_heading(raw_line)
        if heading:
            key, inline = heading
            current_key = key
            if inline:
                sections[current_key].append(inline)
            continue
        if current_key:
            sections[current_key].append(raw_line.rstrip())

    return {key: _clean_lines(value) for key, value in sections.items()}


def _section_heading(line: str) -> Tuple[str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None

    for alias, key in SECTION_ALIASES.items():
        pattern = rf"^(?:#{{1,6}}\s*)?{re.escape(alias)}\s*(?:[:：]\s*(.*))?$"
        match = re.match(pattern, stripped, re.IGNORECASE)
        if match:
            return key, (match.group(1) or "").strip()
    return None


def _parse_constraints(text: str) -> List[str]:
    items: List[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*•]\s*", "", line)
        line = re.sub(r"^\d+[.)、]\s*", "", line)
        if line:
            items.append(line)
    if items:
        return items
    return [text.strip()] if text.strip() else []


def _parse_steps(conversation_flow: str) -> List[Dict[str, Any]]:
    explicit_steps = _parse_steps_with_mode(conversation_flow, include_numbered=False)
    if explicit_steps:
        return explicit_steps
    return _parse_steps_with_mode(conversation_flow, include_numbered=True)


def _parse_steps_with_mode(conversation_flow: str, include_numbered: bool) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    current_step: Dict[str, Any] | None = None
    current_sub_step: Dict[str, str] | None = None

    for raw_line in conversation_flow.split("\n"):
        line = raw_line.rstrip()
        step_heading = _step_heading(line, include_numbered=include_numbered)
        if step_heading:
            current_step = _new_step(step_heading)
            steps.append(current_step)
            current_sub_step = None
            continue

        sub_step_heading = _sub_step_heading(line)
        if sub_step_heading and current_step is not None:
            current_sub_step = _new_sub_step(sub_step_heading)
            current_step.setdefault("sub_steps", []).append(current_sub_step)
            _append_content(current_step, line)
            continue

        if current_sub_step is not None:
            _append_content(current_sub_step, line)
        if current_step is not None:
            _append_content(current_step, line)

    for step in steps:
        step["content"] = step.get("content", "").strip()
        for sub_step in step.get("sub_steps", []):
            sub_step["content"] = sub_step.get("content", "").strip()
        if not step.get("sub_steps"):
            step.pop("sub_steps", None)
    return steps


def _step_heading(line: str, include_numbered: bool = True) -> Tuple[str, str, str] | None:
    stripped = line.strip()
    patterns = [
        r"^(?:#{1,6}\s*)?Step\s*(\d+)\s*[:：.-]?\s*(.*)$",
        r"^(?:#{1,6}\s*)?第\s*(\d+)\s*步\s*[:：.-]?\s*(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, stripped, re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).strip(), ""
    if include_numbered:
        numbered_match = re.match(r"^(\d+)[.)、]\s+(.+)$", stripped)
        if numbered_match:
            content = numbered_match.group(2).strip()
            return numbered_match.group(1).strip(), content, content
    return None


def _sub_step_heading(line: str) -> Tuple[str, str] | None:
    stripped = line.strip()
    match = re.match(r"^(?:#{1,6}\s*)?(\d+\.\d+)\s*[:：.-]?\s*(.*)$", stripped, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _new_step(heading: Tuple[str, str, str]) -> Dict[str, Any]:
    step_no, title, initial_content = heading
    return {"step_no": step_no, "title": title, "content": initial_content, "sub_steps": []}


def _new_sub_step(heading: Tuple[str, str]) -> Dict[str, str]:
    sub_step_no, title = heading
    return {"sub_step_no": sub_step_no, "title": title, "content": ""}


def _append_content(target: Dict[str, Any], line: str) -> None:
    if not line.strip() and not target.get("content"):
        return
    target["content"] = (target.get("content", "") + "\n" + line).strip()


def _clean_lines(lines: Iterable[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def _normalize_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")
