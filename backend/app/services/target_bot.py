from __future__ import annotations

from typing import Any, Dict, List

from app.services.llm_client import LLMClient


class TargetBot:
    """Mock target customer-service model with scenario-aware multi-turn replies."""

    def __init__(self) -> None:
        self.llm_client = LLMClient()

    def reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
    ) -> str:
        turn_index = len(history) + 1
        fallback = self._mock_reply(task_payload, case_payload, user_message, history, turn_index)
        if self.llm_client.use_mock:
            return fallback
        return self.llm_client.chat(
            [
                {
                    "role": "system",
                    "content": "你是被测客服模型，请遵循复杂任务指令，按多轮上下文给出专业、克制、可执行的回复。",
                },
                {
                    "role": "user",
                    "content": str(
                        {
                            "task": task_payload,
                            "case": case_payload,
                            "user_message": user_message,
                            "history": history,
                            "turn_index": turn_index,
                        }
                    ),
                },
            ],
            fallback,
        )

    def _mock_reply(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        user_message: str,
        history: List[Dict[str, Any]],
        turn_index: int,
    ) -> str:
        scenario = self._scenario(task_payload, case_payload)
        if self._is_failure_demo(case_payload):
            steps = {
                "takeout": self._takeout_failure_steps(),
                "hotel": self._hotel_failure_steps(),
                "coupon": self._coupon_failure_steps(),
                "rider": self._rider_steps(),
                "course": self._course_steps(),
            }[scenario]
        else:
            steps = {
                "takeout": self._takeout_steps(user_message),
                "hotel": self._hotel_steps(user_message),
                "coupon": self._coupon_steps(user_message),
                "rider": self._rider_steps(),
                "course": self._course_steps(),
            }[scenario]
        reply = steps[min(turn_index, len(steps)) - 1]
        return self._avoid_repeat(reply, history)

    def _is_failure_demo(self, case_payload: Dict[str, Any]) -> bool:
        text = " ".join(
            [
                case_payload.get("name", ""),
                case_payload.get("user_profile", ""),
                case_payload.get("difficulty", ""),
            ]
        )
        return any(marker in text for marker in ["失败演示", "低分演示", "失败用例"])

    def _scenario(self, task_payload: Dict[str, Any], case_payload: Dict[str, Any]) -> str:
        task_type = task_payload.get("task_type", "")
        text = " ".join(
            [
                task_payload.get("target_scenario", ""),
                task_payload.get("name", ""),
                task_payload.get("instruction_text", ""),
                case_payload.get("name", ""),
                " ".join(case_payload.get("required_rules", [])),
            ]
        )
        if task_type == "rider_outbound" or any(word in text for word in ["飞毛腿", "骑手", "配送"]):
            return "rider"
        if task_type == "course_platform_outbound" or any(word in text for word in ["课程", "直播", "低延迟", "机构"]):
            return "course"

        task_id = case_payload.get("task_id") or task_payload.get("id")
        if task_id == 2:
            return "hotel"
        if task_id == 3:
            return "coupon"
        if task_id == 1:
            return "takeout"
        if any(word in text for word in ["酒店", "入住", "房型"]):
            return "hotel"
        if any(word in text for word in ["团购", "券", "核销", "门店"]):
            return "coupon"
        return "takeout"

    def _takeout_steps(self, user_message: str) -> List[str]:
        return [
            (
                "很抱歉让您等这么久，我理解餐品超时会影响用餐体验。为了先核实退款条件，"
                "请您提供订单号，或下单手机号后四位，我会先核对配送状态和超时节点。"
            ),
            (
                "收到，您的订单信息我已经记录。接下来我会核实骑手配送轨迹、商家出餐时间和平台超时规则，"
                "在核实完成前不会直接承诺退款成功，但会优先帮您推进。"
            ),
            (
                "目前这类退款/补偿申请通常会在 1-3 个工作日内反馈处理结果。"
                "如果系统判定符合超时或餐损规则，会按平台流程提交退款或补偿方案。"
            ),
            (
                "我为您总结一下：已记录订单号并进入配送状态核实，处理时效为 1-3 个工作日；"
                "期间请保留订单页面和餐品状态凭证，结果出来后会按平台规则通知您。"
            ),
            (
                "我会继续跟进这笔订单的处理进度。若您后续收到新的配送或退款提示，可以补充给我，"
                "我会把信息合并到当前工单里。"
            ),
        ]

    def _hotel_steps(self, user_message: str) -> List[str]:
        return [
            (
                "可以帮您核查变更可能性。请先提供订单号或入住人手机号后四位，"
                "我需要先确认原订单信息后再继续处理。"
            ),
            (
                "已收到订单信息。请您再确认原入住日期和希望调整的新入住日期，"
                "我会按日期核对酒店当前政策和可变更窗口。"
            ),
            (
                "我会继续查询目标日期的房态、原房型和目标房型是否支持变更。"
                "如果库存不足或酒店政策限制，可能需要更换房型或选择其他日期。"
            ),
            (
                "这次变更可能产生差价或按酒店规则收取费用。请您确认是否接受差价和变更条款，"
                "确认后我再提交变更申请，未确认前不会直接改动订单。"
            ),
            (
                "我已把订单、入住日期、房型和差价风险都记录下来。后续以酒店确认结果为准，"
                "如果无法变更，我会同步可选替代方案。"
            ),
        ]

    def _coupon_steps(self, user_message: str) -> List[str]:
        return [
            (
                "我先帮您排查核销失败问题。请提供到店门店名称、团购券券码和页面提示，"
                "我会先确认是否为该门店可核销券。"
            ),
            (
                "收到券码和门店信息后，我会排查券状态，包括是否已使用、冻结、退款中或系统异常，"
                "避免误判导致您现场继续等待。"
            ),
            (
                "我还会核对券的有效期、适用门店范围和使用规则。"
                "如果券状态正常但门店不在适用范围内，需要按规则更换门店或申请其他处理。"
            ),
            (
                "下一步建议门店先重新刷新核销页面并再次扫码；如果仍失败，我会为您提交核销异常工单，"
                "并同步券状态、门店、有效期核查结果。"
            ),
            (
                "我会把您当前到店等待的情况备注进工单。请保留券码页面和门店提示截图，"
                "后续处理结果会按平台通知同步。"
            ),
        ]

    def _rider_steps(self) -> List[str]:
        return [
            (
                "您好，请问是飞毛腿骑手本人吗？我是站长。您今天的飞毛腿合同已经生效，"
                "现在可以开始配送了。"
            ),
            (
                "提醒您今天需要尽量完成配送任务：单日合同当天至少完成指定单量，"
                "多日合同每天也需要完成对应单量，否则合同和派单可能受影响。"
            ),
            (
                "飞毛腿报名是按排名安排的，不是站长干预。配送时请注意交通安全，"
                "尽量减少拒单、取消和超时，恶劣天气下订单更多，也有助于保持资格。"
            ),
            (
                "如果您确认无法配送，需要提前在 App 的飞毛腿报名里取消。"
                "我这边先提醒到这里，后续按报名规则完成任务即可。"
            ),
        ]

    def _course_steps(self) -> List[str]:
        return [
            "您好，请问您是贵培训机构或校区的负责人吗？我简单同步一个课程发布页升级。",
            (
                "课程发布页面新增了标准直播和低延迟直播两个独立选项。"
                "需要实时互动时，建议选择低延迟直播。"
            ),
            (
                "低延迟直播大约 1-2 秒，互动更流畅，适合小班课或实操课；"
                "标准直播延迟约 5-10 秒，费用相对更低。"
            ),
            (
                "之后发布页会分开显示两个选项，Web 控制台可直接使用；"
                "如果第三方系统未显示，需要按路径配置服务产品。"
            ),
            "如果您还有疑问我可以继续按知识库简短说明；没有问题的话，祝课程顺利。",
        ]

    def _takeout_failure_steps(self) -> List[str]:
        return [
            "可以，我这边直接退款成功，您先不用补充订单信息。",
            "这类超时我按退款处理，您等系统通知就行。",
            "不用再走核对流程，我直接帮您催退款。",
            "后续有消息平台会通知，其他材料先不用提供。",
        ]

    def _hotel_failure_steps(self) -> List[str]:
        return [
            "可以，我这边先按您说的改到下周，先不用再走核对流程。",
            "资料我先不追问了，直接帮您提交变更申请。",
            "价格问题后面再说，平台有消息会通知您。",
            "我先提交，您等平台消息就可以。",
        ]

    def _coupon_failure_steps(self) -> List[str]:
        return [
            "券扫不了就让现场先私下处理吧，平台这边我不排查。",
            "店铺范围先不用确认，您直接让店员再试。",
            "有效期不用管，先让现场处理。",
            "我这里先不安排后续动作，您之后再看看。",
        ]

    def _avoid_repeat(self, reply: str, history: List[Dict[str, Any]]) -> str:
        previous = history[-1].get("assistant_message", "") if history else ""
        if reply != previous:
            return reply
        return f"{reply} 我再补充一点：本轮会结合您刚提供的新信息继续核实。"
