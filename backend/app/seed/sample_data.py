import json

from sqlmodel import Session, select

from app.core.database import engine
from app.models.case import EvaluationCase
from app.models.task import EvaluationTask
from app.seed.import_instruction_excel import _course_platform_cases, _rider_cases, seed_instructions_from_excel
from app.services.case_registry import sync_task_cases_to_catalog
from app.services.policy_generator import generate_executable_policy


TASK_SPECS = [
    {
        "name": "飞毛腿骑手合同生效外呼评测",
        "description": "评测模型是否能围绕骑手合同生效、完成要求、安全提醒和报名保资格规则完成外呼。",
        "target_scenario": "飞毛腿骑手外呼",
        "system_instruction": "站长需告知飞毛腿合同已生效，确认是否开始配送，并说明完成要求、安全规则和报名保资格规则。",
        "evaluation_goal": "评测被测模型在飞毛腿骑手合同生效外呼中的任务遵循、安抚和边界控制能力。",
        "instruction_text": "飞毛腿骑手合同已生效，需确认骑手是否开始配送，并说明单日 X 单、多日每天 Y 单、安全要求，以及报名按系统排名、不是站长人工干预，减少拒单取消超时有助于保住资格。",
        "task_type": "rider_outbound",
        "data_source": "mock_sample",
    },
    {
        "name": "课程直播产品升级外呼评测",
        "description": "评测模型是否能围绕课程直播发布页升级、负责人转达、发布方式和费用差异完成外呼。",
        "target_scenario": "课程直播产品升级外呼",
        "system_instruction": "外呼需确认是否负责人，说明标准直播和低延迟直播，并根据发布方式给出简短引导。",
        "evaluation_goal": "评测被测模型在课程直播产品升级外呼中的信息传达、分支处理和边界控制能力。",
        "instruction_text": "课程直播发布页升级，需确认负责人，说明标准直播、低延迟直播、Web 控制台、第三方系统和费用差异。",
        "task_type": "course_platform_outbound",
        "data_source": "mock_sample",
    },
    {
        "name": "通用复杂外呼任务评测",
        "description": "用于没有专属任务类型时的通用复杂外呼评测 fallback。",
        "target_scenario": "通用复杂外呼",
        "system_instruction": "外呼时应说明目的、按流程推进、遵守任务约束，并避免串用其他业务场景。",
        "evaluation_goal": "评测被测模型在通用复杂外呼任务中的流程推进和约束遵守能力。",
        "instruction_text": "根据当前任务指令完成通用复杂外呼，保持简短、清晰、可执行。",
        "task_type": "generic_outbound",
        "data_source": "mock_sample",
    },
]


CASE_SPECS = {
    "飞毛腿骑手合同生效外呼评测": [
        {
            "name": "询问合同影响",
            "user_profile": "反复追问骑手。",
            "initial_message": "如果我今天没完成 X 单会怎么样？",
            "max_turns": 4,
            "case_mode": "branch",
            "expected_goals": ["回答合同完成要求", "说明可能影响合同和派单", "不夸大处罚"],
            "required_rules": ["必须说明单日/多日完成要求", "必须说明未完成影响"],
            "forbidden_rules": ["禁止串用旧客服流程"],
            "difficulty": "中等",
        },
        {
            "name": "抱怨恶劣天气",
            "user_profile": "情绪不满骑手。",
            "initial_message": "今天下雨这么大，怎么还让我跑？",
            "max_turns": 5,
            "case_mode": "branch",
            "expected_goals": ["先安抚", "提醒安全", "说明雨天完成有助于保住资格", "不强迫骑手冒险"],
            "required_rules": ["必须安抚拒绝或情绪不满骑手", "必须提醒安全"],
            "forbidden_rules": ["禁止强迫恶劣天气配送", "禁止串用旧客服流程"],
            "difficulty": "困难",
        },
        {
            "name": "询问如何退出飞毛腿",
            "user_profile": "信息咨询骑手。",
            "initial_message": "我想退出飞毛腿，怎么取消？",
            "max_turns": 4,
            "case_mode": "branch",
            "expected_goals": ["告知需要在前一天指定时间前在 App 报名页取消"],
            "required_rules": ["必须正确说明退出流程"],
            "forbidden_rules": ["禁止串用旧客服流程"],
            "difficulty": "中等",
        },
        {
            "name": "质疑报名排名",
            "user_profile": "质疑规则骑手。",
            "initial_message": "为什么别人能报上，我不行？",
            "max_turns": 4,
            "case_mode": "branch",
            "expected_goals": ["说明报名按排名进行", "说明不是站长干预"],
            "required_rules": ["必须说明报名排名非站长干预"],
            "forbidden_rules": ["禁止串用旧客服流程"],
            "difficulty": "中等",
        },
    ],
    "课程直播产品升级外呼评测": _course_platform_cases(),
    "通用复杂外呼任务评测": [
        {
            "name": "通用外呼确认",
            "user_profile": "普通外呼对象，愿意配合但会追问关键信息。",
            "initial_message": "您好，可以简单说一下。",
            "max_turns": 4,
            "case_mode": "branch",
            "expected_goals": ["完成开场", "推进流程", "遵守约束"],
            "required_rules": ["必须说明外呼目的", "必须按流程推进", "必须遵守外呼约束"],
            "forbidden_rules": ["禁止超出知识库答复"],
            "difficulty": "中等",
        }
    ],
}

CASE_SPECS["飞毛腿骑手合同生效外呼评测"] = _rider_cases()
CASE_SPECS["课程直播产品升级外呼评测"] = _course_platform_cases()


LEGACY_TASK_NAMES = {
    "\u5916\u5356\u9000\u6b3e\u5ba2\u670d\u6d41\u7a0b\u8bc4\u6d4b",
    "\u9152\u5e97\u9884\u8ba2\u53d8\u66f4\u6d41\u7a0b\u8bc4\u6d4b",
    "\u5230\u5e97\u56e2\u8d2d\u5238\u6838\u9500\u6d41\u7a0b\u8bc4\u6d4b",
}


def seed_sample_data() -> None:
    with Session(engine) as session:
        if seed_instructions_from_excel(session):
            _backfill_existing_mock_tasks(session)
            _remove_legacy_mock_tasks(session)
            return

        task_by_name: dict[str, EvaluationTask] = {}
        for spec in TASK_SPECS:
            spec = _enrich_task_spec(spec)
            task = _existing_task(session, spec["name"], spec["task_type"])
            if not task:
                task = EvaluationTask(**spec)
                session.add(task)
            else:
                for key, value in spec.items():
                    setattr(task, key, value)
                session.add(task)
            task_by_name[spec["name"]] = task

        session.commit()
        for task in task_by_name.values():
            session.refresh(task)

        for task_name, case_specs in CASE_SPECS.items():
            task = task_by_name[task_name]
            sync_task_cases_to_catalog(session, int(task.id or 0), case_specs, task.data_source or "mock_sample")

        _remove_legacy_mock_tasks(session)
        session.commit()


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


def _enrich_task_spec(spec: dict) -> dict:
    payload = dict(spec)
    payload.update(_structured_fallback_fields(payload.get("task_type") or "generic_outbound"))
    policy = generate_executable_policy(payload)
    payload["executable_policy"] = json.dumps(policy, ensure_ascii=False)
    return payload


def _backfill_existing_mock_tasks(session: Session) -> None:
    mock_tasks = list(
        session.exec(select(EvaluationTask).where(EvaluationTask.data_source == "mock_sample")).all()
    )
    if not mock_tasks:
        return

    spec_by_type = {spec["task_type"]: _enrich_task_spec(spec) for spec in TASK_SPECS}
    for task in mock_tasks:
        enriched = spec_by_type.get(task.task_type or "generic_outbound")
        if not enriched:
            continue
        for key in [
            "role_text",
            "task_text",
            "opening_line",
            "call_flow",
            "knowledge_points",
            "constraints",
            "steps",
            "executable_policy",
        ]:
            setattr(task, key, enriched.get(key, ""))
        session.add(task)
    session.commit()


def _structured_fallback_fields(task_type: str) -> dict:
    if task_type == "rider_outbound":
        steps = [
            {"step_no": "1", "title": "身份确认与合同生效", "content": "确认骑手本人，告知今天飞毛腿合同已生效。"},
            {"step_no": "2", "title": "确认能否配送", "content": "询问骑手今天是否可以开始配送。"},
            {"step_no": "3", "title": "完成要求", "content": "说明单日 X 单、多日每天 Y 单，以及未完成可能影响合同和派单。"},
            {"step_no": "4", "title": "安抚与安全提醒", "content": "根据骑手态度鼓励、挽留或安抚，并提醒安全第一。"},
            {"step_no": "5", "title": "报名排名与保资格", "content": "说明报名按系统排名，并提醒减少拒单、取消和超时。"},
        ]
        constraints = ["回复约30字以内", "自然简短", "不强迫恶劣天气配送", "不编造职责外信息"]
        return {
            "role_text": "飞毛腿骑手外呼通知专员",
            "task_text": "告知骑手合同已生效，确认是否可以开始配送，并说明完成要求、安全提醒和报名保资格规则。",
            "opening_line": "您好，是飞毛腿骑手本人吗？",
            "call_flow": "\n".join(f"{item['step_no']}. {item['content']}" for item in steps),
            "knowledge_points": "退出飞毛腿需在前一天指定时间前，在 App 飞毛腿报名页取消；报名按系统排名，不是站长人工干预。",
            "constraints": json.dumps(constraints, ensure_ascii=False),
            "steps": json.dumps(steps, ensure_ascii=False),
        }

    if task_type == "course_platform_outbound":
        steps = [
            {"step_no": "1", "title": "身份确认", "content": "确认对方是否为机构负责人。"},
            {"step_no": "2", "title": "确认是否知情", "content": "询问对方是否了解低延迟直播。"},
            {"step_no": "3", "title": "传达升级内容", "content": "说明课程发布页会显示标准直播和低延迟直播两个独立选项。"},
            {"step_no": "4", "title": "确认发布方式", "content": "询问使用 Web 控制台还是第三方系统发课。"},
            {"step_no": "5", "title": "费用设置", "content": "确认是否需要配置低延迟直播相关费用。"},
            {"step_no": "6", "title": "企业微信", "content": "确认企业微信添加或手机号补充方式。"},
            {"step_no": "7", "title": "结束通话", "content": "确认无其他问题后礼貌结束。"},
        ]
        constraints = ["每次回复极简——最多15-20个字", "给出信息后暂停等待商家回应", "不承诺优惠券或折扣"]
        return {
            "role_text": "Customer Support Specialist for Course Publishing Platform",
            "task_text": "告知机构客户，课程发布页面将新增标准直播和低延迟直播两个独立选项，并按发布方式做简短引导。",
            "opening_line": "您好，请问您是贵培训机构/校区的负责人吗？",
            "call_flow": "\n\n".join(f"## Step {item['step_no']}: {item['title']}\n{item['content']}" for item in steps),
            "knowledge_points": "标准直播费用较低，延迟约5-10秒，适合大班课；低延迟直播约1-2秒，互动更流畅，适合小班课/实操课。",
            "constraints": json.dumps(constraints, ensure_ascii=False),
            "steps": json.dumps(steps, ensure_ascii=False),
        }

    steps = [
        {"step_no": "1", "title": "说明目的", "content": "简短说明本次外呼目的。"},
        {"step_no": "2", "title": "处理问题", "content": "根据用户问题简短回应。"},
        {"step_no": "3", "title": "确认结束", "content": "确认无其他问题后结束。"},
    ]
    constraints = ["保持简短清晰", "按任务指令推进", "禁止串用其他业务场景"]
    return {
        "role_text": "通用复杂外呼评测助手",
        "task_text": "根据当前任务指令完成通用复杂外呼，保持简短、清晰、可执行。",
        "opening_line": "您好，可以简单沟通一下吗？",
        "call_flow": "\n".join(f"{item['step_no']}. {item['content']}" for item in steps),
        "knowledge_points": "遇到超出范围的问题，应说明需要确认后再回复，不编造信息。",
        "constraints": json.dumps(constraints, ensure_ascii=False),
        "steps": json.dumps(steps, ensure_ascii=False),
    }


def _remove_legacy_mock_tasks(session: Session) -> None:
    legacy_tasks = list(
        session.exec(select(EvaluationTask).where(EvaluationTask.name.in_(LEGACY_TASK_NAMES))).all()
    )
    if not legacy_tasks:
        return

    legacy_task_ids = [task.id for task in legacy_tasks if task.id is not None]
    if legacy_task_ids:
        legacy_cases = list(
            session.exec(select(EvaluationCase).where(EvaluationCase.task_id.in_(legacy_task_ids))).all()
        )
        for case in legacy_cases:
            session.delete(case)

    for task in legacy_tasks:
        session.delete(task)
    session.commit()
