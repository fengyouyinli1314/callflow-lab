from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree as ET

from sqlmodel import Session, select

from app.models.case import EvaluationCase
from app.models.task import EvaluationTask


DATA_SOURCE = "excel_desensitized"
DEFAULT_EXCEL_PATH = Path(__file__).resolve().parents[2] / "data" / "instructions.xlsx"
XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def seed_instructions_from_excel(
    session: Session,
    excel_path: Path | None = None,
) -> int:
    records = load_instruction_records(excel_path or DEFAULT_EXCEL_PATH)
    if not records:
        return 0

    imported = 0
    for record in records:
        payload = _task_payload(record)
        task = session.exec(select(EvaluationTask).where(EvaluationTask.name == payload["name"])).first()
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
    try:
        rows = _read_xlsx_rows(excel_path)
    except Exception:
        return []

    if not rows:
        return []

    header = rows[0]
    instruction_index = _find_column(header, ["任务指令示例", "instruction", "指令"])
    id_index = _find_column(header, ["id", "编号"])
    if instruction_index < 0:
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

        sections = parse_instruction_sections(instruction_text)
        record = {
            "source_id": _cell(row, id_index).strip() if id_index >= 0 else "",
            "instruction_text": instruction_text,
            "role_text": sections.get("role", ""),
            "task_text": sections.get("task", ""),
            "opening_line": sections.get("opening_line", ""),
            "call_flow": sections.get("call_flow", ""),
            "knowledge_points": sections.get("knowledge_points", ""),
            "constraints": sections.get("constraints", ""),
        }
        record["task_type"] = classify_task_type(instruction_text)
        record["name"] = generate_task_name(instruction_text)
        record["data_source"] = DATA_SOURCE
        records.append(record)

    return records


def parse_instruction_sections(instruction_text: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {
        "role": [],
        "task": [],
        "opening_line": [],
        "call_flow": [],
        "knowledge_points": [],
        "constraints": [],
    }
    current_key = ""
    heading_pattern = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")

    for raw_line in instruction_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        match = heading_pattern.match(line)
        if match:
            heading_text = match.group(1).strip()
            heading_name, inline_text = _split_heading(heading_text)
            key = _section_key(heading_name)
            if key:
                current_key = key
                if inline_text:
                    sections[current_key].append(inline_text)
                continue
        if current_key:
            sections[current_key].append(raw_line.rstrip())

    return {key: _clean_section(value) for key, value in sections.items()}


def classify_task_type(instruction_text: str) -> str:
    if any(keyword in instruction_text for keyword in ["飞毛腿", "骑手", "配送"]):
        return "rider_outbound"
    if any(keyword in instruction_text for keyword in ["课程", "直播", "低延迟直播", "机构"]):
        return "course_platform_outbound"
    return "generic_outbound"


def generate_task_name(instruction_text: str) -> str:
    if any(keyword in instruction_text for keyword in ["飞毛腿", "骑手", "配送"]):
        return "飞毛腿骑手合同生效外呼评测"
    if any(keyword in instruction_text for keyword in ["课程", "直播", "低延迟直播", "机构"]):
        return "课程直播产品升级外呼评测"
    return "复杂外呼任务指令评测"


def _task_payload(record: Dict[str, Any]) -> Dict[str, Any]:
    name = record["name"]
    task_type = record["task_type"]
    task_text = record.get("task_text") or "基于脱敏 Excel 导入的复杂外呼任务指令进行评测。"
    call_flow = record.get("call_flow") or "按导入指令中的流程完成外呼。"
    return {
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
        "task_type": task_type,
        "data_source": DATA_SOURCE,
    }


def _ensure_task_cases(session: Session, task: EvaluationTask, record: Dict[str, Any]) -> None:
    for payload in _case_payloads(record):
        existing_case = session.exec(
            select(EvaluationCase).where(
                EvaluationCase.task_id == task.id,
                EvaluationCase.name == payload["name"],
            )
        ).first()
        if existing_case:
            for key, value in payload.items():
                setattr(existing_case, key, value)
            session.add(existing_case)
            continue
        session.add(EvaluationCase(task_id=task.id, **payload))


def _case_payloads(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    task_type = record["task_type"]
    if task_type == "rider_outbound":
        return _rider_cases()
    if task_type == "course_platform_outbound":
        return _course_platform_cases()
    return [_generic_case()]


def _rider_cases() -> List[Dict[str, Any]]:
    forbidden = ["禁止承诺额外奖励", "禁止强迫配送", "禁止超出知识库答复"]
    return [
        {
            "name": "正常愿意配送",
            "user_profile": "普通骑手，愿意配合。",
            "initial_message": "可以，我今天能跑。",
            "max_turns": 4,
            "expected_goals": ["站长确认合同已生效", "询问是否开始配送", "说明单日/多日合同完成要求", "提醒配送安全"],
            "required_rules": ["必须确认合同已生效", "必须询问是否开始配送", "必须说明单日多日合同完成要求", "必须提醒配送安全"],
            "forbidden_rules": forbidden,
            "difficulty": "简单",
        },
        {
            "name": "不想配送",
            "user_profile": "拒绝配合骑手。",
            "initial_message": "我今天不想跑了，能不能不送？",
            "max_turns": 4,
            "expected_goals": ["站长需要挽留", "说明不完成配送可能影响合同和派单", "如果骑手坚持无法配送，需要安慰并结束通话"],
            "required_rules": ["必须进行挽留", "必须说明不完成配送可能影响合同和派单", "必须在坚持无法配送时安慰并结束通话"],
            "forbidden_rules": forbidden,
            "difficulty": "困难",
        },
        {
            "name": "询问合同影响",
            "user_profile": "反复追问骑手。",
            "initial_message": "如果我今天没完成 X 单会怎么样？",
            "max_turns": 4,
            "expected_goals": ["回答合同完成要求", "说明可能影响合同和派单", "不夸大处罚"],
            "required_rules": ["必须回答合同完成要求", "必须说明可能影响合同和派单", "必须不夸大处罚"],
            "forbidden_rules": forbidden + ["禁止夸大处罚"],
            "difficulty": "中等",
        },
        {
            "name": "询问如何退出飞毛腿",
            "user_profile": "信息咨询骑手。",
            "initial_message": "我想退出飞毛腿，怎么取消？",
            "max_turns": 4,
            "expected_goals": ["告知需要在前一天指定时间前在 App 飞毛腿报名中取消", "不编造其他退出方式"],
            "required_rules": ["必须说明前一天指定时间前在 App 飞毛腿报名中取消", "必须不编造其他退出方式"],
            "forbidden_rules": forbidden + ["禁止编造退出方式"],
            "difficulty": "中等",
        },
        {
            "name": "抱怨恶劣天气",
            "user_profile": "情绪不满骑手。",
            "initial_message": "今天下雨这么大，怎么还让我跑？",
            "max_turns": 5,
            "expected_goals": ["先安抚", "提醒安全", "说明恶劣天气下订单更多，完成有助于保住资格", "不强迫骑手冒险"],
            "required_rules": ["必须先安抚", "必须提醒安全", "必须说明恶劣天气订单更多且完成有助于保住资格", "必须不强迫骑手冒险"],
            "forbidden_rules": forbidden + ["禁止强迫冒险"],
            "difficulty": "困难",
        },
        {
            "name": "质疑报名排名",
            "user_profile": "质疑规则骑手。",
            "initial_message": "为什么别人能报上，我排不上？",
            "max_turns": 4,
            "expected_goals": ["说明报名按排名进行", "说明不是站长干预", "不承诺一定获得资格"],
            "required_rules": ["必须说明报名按排名进行", "必须说明不是站长干预", "必须不承诺一定获得资格"],
            "forbidden_rules": forbidden + ["禁止承诺一定获得资格"],
            "difficulty": "中等",
        },
    ]


def _course_platform_cases() -> List[Dict[str, Any]]:
    forbidden = ["禁止承诺优惠券", "禁止使用不专业语气", "禁止超出知识库答复"]
    return [
        {
            "name": "负责人正常沟通",
            "user_profile": "机构负责人，愿意了解。",
            "initial_message": "我是负责人，你说吧。",
            "max_turns": 5,
            "expected_goals": ["说明新增标准直播和低延迟直播", "说明低延迟适合实时互动", "询问当前发布方式", "说明后续配置路径"],
            "required_rules": ["必须说明新增标准直播和低延迟直播", "必须说明低延迟适合实时互动", "必须询问当前发布方式", "必须说明后续配置路径"],
            "forbidden_rules": forbidden,
            "difficulty": "简单",
        },
        {
            "name": "非负责人转达",
            "user_profile": "非负责人。",
            "initial_message": "我不是负责人，我只是前台。",
            "max_turns": 4,
            "expected_goals": ["请对方转达", "简短说明升级内容", "不强行继续推销"],
            "required_rules": ["必须请对方转达", "必须简短说明升级内容", "必须不强行继续推销"],
            "forbidden_rules": forbidden + ["禁止强行继续推销"],
            "difficulty": "中等",
        },
        {
            "name": "商家说忙",
            "user_profile": "忙碌商家。",
            "initial_message": "我现在很忙，没时间听。",
            "max_turns": 4,
            "expected_goals": ["用“就1分钟，保证简短”挽留", "简短说明重点", "给商家发言机会"],
            "required_rules": ["必须用就1分钟保证简短挽留", "必须简短说明重点", "必须给商家发言机会"],
            "forbidden_rules": forbidden,
            "difficulty": "中等",
        },
        {
            "name": "商家说在开车",
            "user_profile": "正在开车的商家。",
            "initial_message": "我在开车，不方便说。",
            "max_turns": 3,
            "expected_goals": ["礼貌说明稍后再打", "立即结束通话", "不继续推销"],
            "required_rules": ["必须礼貌说明稍后再打", "必须立即结束通话", "必须不继续推销"],
            "forbidden_rules": forbidden + ["禁止继续推销"],
            "difficulty": "困难",
        },
        {
            "name": "追问直播区别",
            "user_profile": "反复追问商家。",
            "initial_message": "标准直播和低延迟直播有什么区别？",
            "max_turns": 5,
            "expected_goals": ["说明标准直播费用低、延迟约 5-10 秒", "说明低延迟直播延迟约 1-2 秒，互动更流畅", "不长篇大论"],
            "required_rules": ["必须说明标准直播费用低且延迟约5-10秒", "必须说明低延迟直播约1-2秒且互动更流畅", "必须不长篇大论"],
            "forbidden_rules": forbidden + ["禁止长篇大论"],
            "difficulty": "中等",
        },
        {
            "name": "要求优惠券",
            "user_profile": "价格敏感商家。",
            "initial_message": "你们能不能给我优惠券？",
            "max_turns": 4,
            "expected_goals": ["明确不能承诺优惠券", "引导继续完成配置或说明费用规则"],
            "required_rules": ["必须明确不能承诺优惠券", "必须引导继续完成配置或说明费用规则"],
            "forbidden_rules": forbidden,
            "difficulty": "困难",
        },
        {
            "name": "第三方系统看不到选项",
            "user_profile": "技术不熟悉商家。",
            "initial_message": "我第三方系统里看不到低延迟直播选项。",
            "max_turns": 6,
            "expected_goals": ["按流程引导进入对应路径", "如果仍看不到，说明后台可能未配置，请明天再查看"],
            "required_rules": ["必须按流程引导进入对应路径", "必须说明仍看不到时后台可能未配置并请明天再查看"],
            "forbidden_rules": forbidden,
            "difficulty": "困难",
        },
    ]


def _generic_case() -> Dict[str, Any]:
    return {
        "name": "复杂外呼任务指令用例",
        "user_profile": "普通外呼对象，愿意配合但会追问关键信息。",
        "initial_message": "您好，可以简单说一下。",
        "max_turns": 4,
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
