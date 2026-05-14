from sqlmodel import Session, select

from app.core.database import engine
from app.models.case import EvaluationCase
from app.models.task import EvaluationTask


def seed_sample_data() -> None:
    with Session(engine) as session:
        existing = session.exec(select(EvaluationTask)).first()
        if existing:
            return

        tasks = [
            EvaluationTask(
                name="外卖退款客服流程评测",
                description="用户投诉外卖超时并要求退款，评测客服是否先核实订单、安抚情绪并说明处理时效。",
                target_scenario="外卖退款",
                system_instruction="客服必须核实订单号，不能直接承诺退款成功，需要告知处理时效，并安抚用户情绪。",
                evaluation_goal="评测被测模型在退款投诉场景中的流程完整性、合规承诺和情绪处理能力。",
            ),
            EvaluationTask(
                name="酒店预订变更流程评测",
                description="用户希望修改入住日期，评测客服是否确认订单、日期、房型和差价。",
                target_scenario="酒店订单变更",
                system_instruction="客服需要确认订单信息、入住日期、房型是否可变更，并提醒可能产生差价。",
                evaluation_goal="评测被测模型在酒店订单变更中的信息核实、限制说明和风险提示能力。",
            ),
            EvaluationTask(
                name="到店团购券核销流程评测",
                description="用户到店后团购券无法核销，评测客服是否排查券状态、门店范围和有效期。",
                target_scenario="团购券核销",
                system_instruction="客服需要排查券状态、门店适用范围、有效期，并给出下一步处理建议。",
                evaluation_goal="评测被测模型在核销异常场景中的排查路径、规则解释和处理建议能力。",
            ),
        ]
        session.add_all(tasks)
        session.commit()
        for task in tasks:
            session.refresh(task)

        cases = [
            EvaluationCase(
                task_id=tasks[0].id,
                name="普通用户退款诉求",
                user_profile="普通用户，表达清楚，希望尽快退款。",
                initial_message="我的外卖迟到了快一个小时，饭都凉了，我想申请退款。",
                max_turns=4,
                expected_goals=["完成退款受理前置核实", "说明处理时效", "安抚用户情绪"],
                required_rules=["必须核实订单号", "必须告知处理时效", "必须安抚用户情绪"],
                forbidden_rules=["禁止直接承诺退款成功", "禁止跳过核实"],
                difficulty="简单",
            ),
            EvaluationCase(
                task_id=tasks[0].id,
                name="情绪激动用户投诉",
                user_profile="情绪激动用户，对配送超时非常不满，要求马上给说法。",
                initial_message="你们配送太离谱了，我等了这么久，必须马上给我处理退款！",
                max_turns=5,
                expected_goals=["识别情绪", "核实订单", "按规则说明退款路径"],
                required_rules=["必须核实订单号", "必须告知处理时效", "必须安抚用户情绪"],
                forbidden_rules=["禁止直接承诺退款成功", "禁止跳过核实"],
                difficulty="困难",
            ),
            EvaluationCase(
                task_id=tasks[0].id,
                name="信息缺失退款咨询",
                user_profile="信息缺失用户，暂时找不到订单号，需要客服引导。",
                initial_message="我想退一个超时外卖，但我现在找不到订单号怎么办？",
                max_turns=4,
                expected_goals=["引导查找订单信息", "不越权承诺", "说明处理时效"],
                required_rules=["必须核实订单号", "必须告知处理时效", "必须安抚用户情绪"],
                forbidden_rules=["禁止直接承诺退款成功", "禁止跳过核实"],
                difficulty="中等",
            ),
            EvaluationCase(
                task_id=tasks[1].id,
                name="普通用户修改入住日期",
                user_profile="普通用户，计划变更，希望了解是否能修改入住日期。",
                initial_message="我预订的酒店想把入住日期往后改一天，可以帮我改吗？",
                max_turns=4,
                expected_goals=["确认订单信息", "确认新入住日期", "提醒差价"],
                required_rules=["必须确认订单信息", "必须确认入住日期", "必须确认房型", "必须提醒可能产生差价"],
                forbidden_rules=["禁止承诺免费变更", "禁止跳过核实"],
                difficulty="简单",
            ),
            EvaluationCase(
                task_id=tasks[1].id,
                name="需求变更用户改房型",
                user_profile="需求变更用户，先改日期又想顺便升级房型。",
                initial_message="我酒店订单要改入住日期，可能还想把大床房换成双床房。",
                max_turns=5,
                expected_goals=["确认订单", "确认日期与房型", "说明库存和差价"],
                required_rules=["必须确认订单信息", "必须确认入住日期", "必须确认房型", "必须提醒可能产生差价"],
                forbidden_rules=["禁止承诺免费变更", "禁止跳过核实"],
                difficulty="困难",
            ),
            EvaluationCase(
                task_id=tasks[1].id,
                name="反复追问变更限制",
                user_profile="反复追问用户，持续询问是否一定可以变更。",
                initial_message="我这个酒店订单是不是肯定能改日期？你帮我确认一下。",
                max_turns=4,
                expected_goals=["明确变更条件", "提醒酒店政策", "给出下一步"],
                required_rules=["必须确认订单信息", "必须确认入住日期", "必须确认房型", "必须提醒可能产生差价"],
                forbidden_rules=["禁止承诺免费变更", "禁止跳过核实"],
                difficulty="中等",
            ),
            EvaluationCase(
                task_id=tasks[2].id,
                name="普通用户券无法核销",
                user_profile="普通用户，到店后发现团购券扫不出来。",
                initial_message="我到店消费，团购券一直核销失败，店员也不知道怎么办。",
                max_turns=4,
                expected_goals=["排查券状态", "核对门店适用范围", "核对有效期", "给出处理建议"],
                required_rules=["必须排查券状态", "必须核对门店适用范围", "必须核对有效期", "必须给出下一步处理建议"],
                forbidden_rules=["禁止绕过平台私下处理", "禁止忽视有效期"],
                difficulty="简单",
            ),
            EvaluationCase(
                task_id=tasks[2].id,
                name="情绪激动到店核销失败",
                user_profile="情绪激动用户，已经到店等待，要求立即解决。",
                initial_message="我人就在店里，券核销不了，太耽误时间了，你们马上解决！",
                max_turns=5,
                expected_goals=["安抚现场情绪", "排查券码与门店", "给出异常工单方案"],
                required_rules=["必须排查券状态", "必须核对门店适用范围", "必须核对有效期", "必须给出下一步处理建议"],
                forbidden_rules=["禁止绕过平台私下处理", "禁止忽视有效期"],
                difficulty="困难",
            ),
            EvaluationCase(
                task_id=tasks[2].id,
                name="信息缺失核销咨询",
                user_profile="信息缺失用户，只知道券不能用，但没有截图和券码。",
                initial_message="我的团购券用不了，但我不知道要给你什么信息。",
                max_turns=4,
                expected_goals=["引导提供券码", "说明排查维度", "输出下一步动作"],
                required_rules=["必须排查券状态", "必须核对门店适用范围", "必须核对有效期", "必须给出下一步处理建议"],
                forbidden_rules=["禁止绕过平台私下处理", "禁止忽视有效期"],
                difficulty="中等",
            ),
        ]
        session.add_all(cases)
        session.commit()
