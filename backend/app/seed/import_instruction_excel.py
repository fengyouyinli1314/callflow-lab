from __future__ import annotations

import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree as ET

from sqlmodel import Session, select

from app.models.task import EvaluationTask
from app.services.case_registry import sync_task_cases_to_catalog
from app.services.course_flow import COURSE_FULL_FLOW_CASE_NAME, COURSE_FULL_FLOW_EXPECTED_STEPS
from app.services.instruction_parser import parse_instruction
from app.services.policy_generator import generate_executable_policy
from app.services.rider_flow import RIDER_FULL_FLOW_EXPECTED_STEPS


logger = logging.getLogger(__name__)
DATA_SOURCE = "excel_desensitized"
DEFAULT_EXCEL_PATH = Path(__file__).resolve().parents[2] / "data" / "instructions.xlsx"
XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def seed_instructions_from_excel(
    session: Session,
    excel_path: Path | None = None,
) -> int:
    source_path = excel_path or DEFAULT_EXCEL_PATH
    records = load_instruction_records(source_path)
    if not records:
        logger.warning("Excel instruction import skipped: no valid rows from %s", source_path)
        return 0

    logger.info("Excel instruction import found %s valid row(s) from %s", len(records), source_path)
    imported = 0
    for record in records:
        payload = _task_payload(record)
        _log_import_record(payload)
        task = _existing_task(session, payload["name"], payload["task_type"])
        if task:
            for key, value in payload.items():
                setattr(task, key, value)
            task.updated_at = datetime.utcnow()
        else:
            task = EvaluationTask(**payload)
            session.add(task)
        session.commit()
        session.refresh(task)
        _ensure_task_cases(session, task, record)
        imported += 1

    session.commit()
    return imported


def load_instruction_records(excel_path: Path = DEFAULT_EXCEL_PATH) -> List[Dict[str, Any]]:
    if not excel_path.exists():
        logger.warning("Excel instruction file not found: %s", excel_path)
        return []

    try:
        rows = _read_xlsx_rows(excel_path)
    except Exception as exc:
        logger.warning("failed to read Excel instruction file %s: %s", excel_path, exc)
        return []

    if not rows:
        logger.warning("Excel instruction file has no readable rows: %s", excel_path)
        return []

    header = rows[0]
    instruction_index = _find_column(header, ["任务指令示例", "instruction", "指令"])
    id_index = _find_column(header, ["id", "编号"])
    if instruction_index < 0:
        logger.warning("Excel instruction column not found in header: %s", header)
        return []

    records: List[Dict[str, Any]] = []
    seen_signatures: set[str] = set()
    for row in rows[1:]:
        instruction_text = _cell(row, instruction_index).strip()
        if not instruction_text:
            continue
        signature = _normalize_signature(instruction_text)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        parsed = _safe_parse_instruction(instruction_text)
        record = {
            "source_id": _cell(row, id_index).strip() if id_index >= 0 else "",
            "instruction_text": instruction_text,
            "role_text": parsed.get("role_text", ""),
            "task_text": parsed.get("task_text", ""),
            "opening_line": parsed.get("opening_line", ""),
            "conversation_flow": parsed.get("conversation_flow", ""),
            "knowledge_points": parsed.get("knowledge_points", ""),
            "constraints": _json_text(parsed.get("constraints", [])),
            "steps": _json_text(parsed.get("steps", [])),
        }
        record["task_type"] = classify_task_type(instruction_text)
        record["name"] = generate_task_name(instruction_text)
        record["data_source"] = DATA_SOURCE
        records.append(record)

    logger.info("Excel instruction valid row count: %s", len(records))
    return records


def parse_instruction_sections(instruction_text: str) -> Dict[str, str]:
    parsed = _safe_parse_instruction(instruction_text)
    return {
        "role": parsed.get("role_text", ""),
        "task": parsed.get("task_text", ""),
        "opening_line": parsed.get("opening_line", ""),
        "call_flow": parsed.get("conversation_flow", ""),
        "knowledge_points": parsed.get("knowledge_points", ""),
        "constraints": "\n".join(parsed.get("constraints", []) or []),
    }


def _safe_parse_instruction(instruction_text: str) -> Dict[str, Any]:
    try:
        return parse_instruction(instruction_text)
    except Exception as exc:
        logger.warning("failed to parse instruction text: %s", exc)
        return {
            "role_text": "",
            "task_text": "",
            "constraints": [],
            "opening_line": "",
            "conversation_flow": "",
            "knowledge_points": "",
            "steps": [],
        }


def _json_text(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def classify_task_type(instruction_text: str) -> str:
    if any(keyword in instruction_text for keyword in ["飞毛腿", "骑手", "配送", "派单"]):
        return "rider_outbound"
    if any(keyword in instruction_text for keyword in ["课程", "直播", "低延迟", "机构", "负责人"]):
        return "course_platform_outbound"
    return "generic_outbound"


def generate_task_name(instruction_text: str) -> str:
    if any(keyword in instruction_text for keyword in ["飞毛腿", "骑手", "配送", "派单"]):
        return "飞毛腿骑手合同生效外呼评测"
    if any(keyword in instruction_text for keyword in ["课程", "直播", "低延迟", "机构", "负责人"]):
        return "课程直播产品升级外呼评测"
    return "复杂外呼任务指令评测"


def _task_payload(record: Dict[str, Any]) -> Dict[str, Any]:
    name = record["name"]
    task_type = record["task_type"]
    task_text = record.get("task_text") or "基于脱敏 Excel 导入的复杂外呼任务指令进行评测。"
    call_flow = record.get("conversation_flow") or record.get("call_flow") or "按导入指令中的流程完成外呼。"
    payload = {
        "name": name,
        "description": task_text[:600],
        "target_scenario": _target_scenario(task_type),
        "system_instruction": record["instruction_text"],
        "evaluation_goal": f"评测模型是否能遵循“{name}”中的角色、开场白、流程、知识点和约束完成外呼。",
        "instruction_text": record["instruction_text"],
        "role_text": record.get("role_text", ""),
        "task_text": task_text,
        "opening_line": record.get("opening_line", ""),
        "call_flow": call_flow,
        "knowledge_points": record.get("knowledge_points", ""),
        "constraints": record.get("constraints", ""),
        "steps": record.get("steps", ""),
        "task_type": task_type,
        "data_source": DATA_SOURCE,
    }
    payload["executable_policy"] = _json_text(_safe_generate_policy(payload))
    return payload


def _safe_generate_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return generate_executable_policy(payload)
    except Exception as exc:
        logger.warning("failed to generate executable policy: %s", exc)
        return {
            "reply_rules": {
                "max_chars_per_reply": 20,
                "hard_limit_chars": 25,
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
        }


def _log_import_record(payload: Dict[str, Any]) -> None:
    constraints = _json_list(payload.get("constraints"))
    steps = _json_list(payload.get("steps"))
    policy = _json_dict(payload.get("executable_policy"))
    logger.info(
        "Excel task import: name=%s task_type=%s instruction_head=%r role=%s task=%s "
        "opening=%s constraints=%s steps=%s policy=%s",
        payload.get("name"),
        payload.get("task_type"),
        str(payload.get("instruction_text") or "")[:100],
        bool(payload.get("role_text")),
        bool(payload.get("task_text")),
        bool(payload.get("opening_line")),
        len(constraints),
        len(steps),
        bool(policy),
    )


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ensure_task_cases(session: Session, task: EvaluationTask, record: Dict[str, Any]) -> None:
    sync_task_cases_to_catalog(
        session,
        int(task.id or 0),
        _case_payloads(record),
        DATA_SOURCE,
    )


def _existing_task(session: Session, name: str, task_type: str) -> EvaluationTask | None:
    task = session.exec(
        select(EvaluationTask).where(
            EvaluationTask.name == name,
            EvaluationTask.task_type == task_type,
        )
    ).first()
    if task:
        return task
    return session.exec(select(EvaluationTask).where(EvaluationTask.name == name)).first()


def _case_payloads(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    task_type = record["task_type"]
    if task_type == "rider_outbound":
        return _rider_cases()
    if task_type == "course_platform_outbound":
        return _course_platform_cases()
    return [_generic_case()]


def _rider_cases() -> List[Dict[str, Any]]:
    return [
        {
            "name": "飞毛腿骑手合同生效外呼用例",
            "user_profile": "递进式综合骑手：先确认本人并表示可以开跑，听完高峰和单量要求后接受鼓励、安全提醒，并在收口前追问名额是否由站长决定。",
            "initial_message": "是我，你说。",
            "max_turns": 10,
            "case_mode": "full_flow",
            "expected_goals": [
                "确认骑手身份",
                "告知今天飞毛腿合同已签署并生效",
                "说明午晚高峰上线、单日 X 单、多日每天 Y 单",
                "询问骑手是否可以开始配送",
                "根据骑手态度进行鼓励、挽留或安抚并提醒安全",
                "末尾说明排名与保资格规则",
            ],
            "expected_steps": list(RIDER_FULL_FLOW_EXPECTED_STEPS),
            "required_rules": [
                "是否确认骑手身份",
                "是否告知飞毛腿合同已签署并生效",
                "是否询问是否可以开始配送",
                "是否说明单日/多日合同完成要求",
                "是否根据骑手态度鼓励挽留或安抚",
                "是否提醒安全",
                "是否说明报名按排名进行且不是站长人工干预",
                "是否提醒减少拒单取消超时有助于保住资格",
                "是否回复自然简短",
            ],
            "forbidden_rules": ["禁止强迫配送", "禁止编造职责外信息", "禁止承诺具体奖励金额", "禁止说站长可以手动调整排名"],
            "trigger_conditions": ["默认按主流程推进，排名与保资格规则放在末尾收口；若用户主动问排名、名额、站长干预、拒单取消超时或恶劣天气，可提前触发解释。"],
            "difficulty": "中等",
        },
    ]


def _course_platform_cases() -> List[Dict[str, Any]]:
    return [
        {
            "name": COURSE_FULL_FLOW_CASE_NAME,
            "user_profile": "机构负责人，按强渐进流程沟通；每轮只回应一个点，会追问知情、区别、费用、发布方式、配置路径、学员端费用和企业微信。",
            "initial_message": "我是负责人，你说吧。",
            "max_turns": 30,
            "case_mode": "full_flow",
            "expected_goals": [
                "按身份确认、知情确认、升级内容、区别/价格、发布方式、配置路径、费用检查、企业微信和结束通话逐步推进",
                "每次回复 15-20 字内，并频繁等待商家回应",
                "忙碌时先说就1分钟，开车时稍后再打并结束",
            ],
            "expected_steps": list(COURSE_FULL_FLOW_EXPECTED_STEPS),
            "required_rules": [
                "是否确认对方是否负责人",
                "是否询问对方是否知道低延迟直播",
                "是否说明发布页分开显示标准直播和低延迟直播",
                "是否说明标准直播和低延迟直播区别",
                "是否询问 Web 控制台 / 校务系统A / SaaS系统B",
                "是否说明配置路径",
                "是否说明企业微信添加逻辑",
                "是否给商家发言机会",
            ],
            "forbidden_rules": ["禁止承诺优惠券或折扣", "禁止长篇解释", "禁止使用不专业语气"],
            "difficulty": "困难",
            "trigger_conditions": ["默认主流程按步骤推进；每步内根据商家回应处理负责人/非负责人、忙、开车、区别、费用、配置路径、企业微信等条件分支。"],
        },
    ]


def _generic_case() -> Dict[str, Any]:
    return {
        "name": "复杂外呼任务指令用例",
        "user_profile": "普通外呼对象，愿意配合但会追问关键信息。",
        "initial_message": "您好，可以简单说一下。",
        "max_turns": 4,
        "case_mode": "branch",
        "expected_goals": ["完成开场", "推进流程", "遵守约束"],
        "required_rules": ["必须说明外呼目的", "必须按流程推进", "必须遵守外呼约束"],
        "forbidden_rules": ["禁止超出知识库答复"],
        "difficulty": "中等",
    }


def _read_xlsx_rows(excel_path: Path) -> List[List[str]]:
    if not excel_path.exists():
        return []

    with zipfile.ZipFile(excel_path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_name = _first_sheet_path(archive)
        sheet_xml = ET.fromstring(archive.read(sheet_name))

    rows: List[List[str]] = []
    for row in sheet_xml.findall(".//x:sheetData/x:row", XLSX_NS):
        values: Dict[int, str] = {}
        for cell in row.findall("x:c", XLSX_NS):
            column_index = _column_index(cell.attrib.get("r", "A1"))
            values[column_index] = _cell_value(cell, shared_strings)
        if values:
            max_index = max(values)
            rows.append([values.get(index, "") for index in range(max_index + 1)])
    return rows


def _read_shared_strings(archive: zipfile.ZipFile) -> List[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: List[str] = []
    for item in root.findall("x:si", XLSX_NS):
        values.append("".join(text.text or "" for text in item.findall(".//x:t", XLSX_NS)))
    return values


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationship_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rels = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationship_root.findall(
            "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
        )
    }
    first_sheet = workbook.find("x:sheets/x:sheet", XLSX_NS)
    if first_sheet is None:
        return "xl/worksheets/sheet1.xml"
    rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    target = rels.get(rel_id or "", "worksheets/sheet1.xml")
    return "xl/" + target.lstrip("/")


def _cell_value(cell: ET.Element, shared_strings: List[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//x:t", XLSX_NS)).strip()

    value = cell.find("x:v", XLSX_NS)
    if value is None or value.text is None:
        return ""
    raw = value.text
    if cell_type == "s":
        index = int(raw)
        return shared_strings[index].strip() if index < len(shared_strings) else ""
    return raw.strip()


def _find_column(header: List[str], aliases: List[str]) -> int:
    normalized_aliases = {_normalize_header(alias) for alias in aliases}
    for index, value in enumerate(header):
        if _normalize_header(value) in normalized_aliases:
            return index
    return -1


def _cell(row: List[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index] or ""


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - ord("A") + 1
    return max(index - 1, 0)


def _section_key(raw_heading: str) -> str:
    heading = re.sub(r"\s+", " ", raw_heading.strip().lower())
    if heading.startswith("role"):
        return "role"
    if heading.startswith("task"):
        return "task"
    if heading.startswith("opening line"):
        return "opening_line"
    if heading.startswith("call flow") or heading.startswith("conversation flow"):
        return "call_flow"
    if heading.startswith("knowledge points") or heading.startswith("faq"):
        return "knowledge_points"
    if heading.startswith("constraints"):
        return "constraints"
    return ""


def _split_heading(heading_text: str) -> tuple[str, str]:
    for separator in [":", "："]:
        if separator in heading_text:
            name, inline_text = heading_text.split(separator, 1)
            return name.strip(), inline_text.strip()
    return heading_text.strip(), ""


def _clean_section(lines: List[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def _normalize_header(value: str) -> str:
    return re.sub(r"[\s_]+", "", value.strip().lower())


def _normalize_signature(value: str) -> str:
    return re.sub(r"\s+", "", value)[:200]


def _target_scenario(task_type: str) -> str:
    if task_type == "rider_outbound":
        return "飞毛腿骑手外呼"
    if task_type == "course_platform_outbound":
        return "课程直播产品升级外呼"
    return "复杂外呼"


def _case_name(task_type: str) -> str:
    if task_type == "rider_outbound":
        return "飞毛腿骑手合同生效外呼用例"
    if task_type == "course_platform_outbound":
        return "课程直播产品升级外呼用例"
    return "复杂外呼任务指令用例"
