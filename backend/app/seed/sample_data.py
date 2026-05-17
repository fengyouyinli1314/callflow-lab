from sqlmodel import Session, select

from app.core.database import engine
from app.models.case import EvaluationCase
from app.models.task import EvaluationTask
from app.seed.import_instruction_excel import seed_instructions_from_excel
from app.services.case_registry import get_or_create_case


TASK_SPECS = [
    {
        "name": "飞毛腿骑手合同生效外呼评测",
        "description": "评测模型是否能围绕骑手合同生效、完成要求、派单影响和安全提醒完成外呼。",
        "target_scenario": "飞毛腿骑手外呼",
        "system_instruction": "站长需告知飞毛腿合同已生效，确认是否开始配送，并说明完成要求、影响和安全规则。",
        "evaluation_goal": "评测被测模型在飞毛腿骑手合同生效外呼中的任务遵循、安抚和边界控制能力。",
        "instruction_text": "飞毛腿骑手合同已生效，需确认骑手是否开始配送，并说明单日 X 单、多日每天 Y 单、未完成影响和安全要求。",
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
            "expected_goals": ["说明报名按排名进行", "说明不是站长干预"],
            "required_rules": ["必须说明报名排名非站长干预"],
            "forbidden_rules": ["禁止串用旧客服流程"],
            "difficulty": "中等",
        },
    ],
    "课程直播产品升级外呼评测": [
        {
            "name": "非负责人转达",
            "user_profile": "非负责人。",
            "initial_message": "我不是负责人，我只是前台。",
            "max_turns": 4,
            "expected_goals": ["请对方转达", "简短说明升级内容"],
            "required_rules": ["必须请对方转达", "必须简短说明升级内容"],
            "forbidden_rules": ["禁止强行继续推销"],
            "difficulty": "中等",
        },
        {
            "name": "负责人正常沟通",
            "user_profile": "机构负责人，愿意了解。",
            "initial_message": "我是负责人，你说吧。",
            "max_turns": 5,
            "expected_goals": ["说明标准直播和低延迟直播", "说明低延迟适合实时互动", "询问当前发布方式"],
            "required_rules": ["必须说明新增标准直播和低延迟直播", "必须说明低延迟适合实时互动", "必须询问当前发布方式"],
            "forbidden_rules": ["禁止承诺优惠券", "禁止使用不专业语气"],
            "difficulty": "简单",
        },
        {
            "name": "第三方系统看不到选项",
            "user_profile": "技术不熟悉商家。",
            "initial_message": "我第三方系统里看不到低延迟直播选项。",
            "max_turns": 5,
            "expected_goals": ["按流程引导进入对应路径", "说明发布方式配置"],
            "required_rules": ["必须按流程引导进入对应路径"],
            "forbidden_rules": ["禁止长篇大论"],
            "difficulty": "困难",
        },
    ],
    "通用复杂外呼任务评测": [
        {
            "name": "通用外呼确认",
            "user_profile": "普通外呼对象，愿意配合但会追问关键信息。",
            "initial_message": "您好，可以简单说一下。",
            "max_turns": 4,
            "expected_goals": ["完成开场", "推进流程", "遵守约束"],
            "required_rules": ["必须说明外呼目的", "必须按流程推进", "必须遵守外呼约束"],
            "forbidden_rules": ["禁止超出知识库答复"],
            "difficulty": "中等",
        }
    ],
}


LEGACY_TASK_NAMES = {
    "\u5916\u5356\u9000\u6b3e\u5ba2\u670d\u6d41\u7a0b\u8bc4\u6d4b",
    "\u9152\u5e97\u9884\u8ba2\u53d8\u66f4\u6d41\u7a0b\u8bc4\u6d4b",
    "\u5230\u5e97\u56e2\u8d2d\u5238\u6838\u9500\u6d41\u7a0b\u8bc4\u6d4b",
}


def seed_sample_data() -> None:
    with Session(engine) as session:
        if seed_instructions_from_excel(session):
            _remove_legacy_mock_tasks(session)
            return

        task_by_name: dict[str, EvaluationTask] = {}
        for spec in TASK_SPECS:
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
            for case_spec in case_specs:
                get_or_create_case(session, {"task_id": task.id, **case_spec})

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
