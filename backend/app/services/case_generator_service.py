from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List

from app.core.config import settings
from app.models.task import EvaluationTask
from app.services.case_mode import normalize_case_mode
from app.services.course_flow import COURSE_FULL_FLOW_CASE_NAME, COURSE_FULL_FLOW_EXPECTED_STEPS
from app.services.rider_flow import RIDER_FULL_FLOW_EXPECTED_STEPS
from app.services.target_model_client import TargetModelClient


logger = logging.getLogger(__name__)

DEFAULT_CASE_GENERATOR_MODEL = "mock-case-generator"
SUPPORTED_CASE_GENERATOR_PROVIDERS = {"mock", "openai_compatible"}
VALID_DIFFICULTIES = {"简单", "中等", "困难"}


class CaseGeneratorService:
    """Generate evaluation case drafts without persisting them."""

    def __init__(self) -> None:
        provider = (settings.case_generator_provider or "mock").strip().lower()
        self.provider = provider if provider in SUPPORTED_CASE_GENERATOR_PROVIDERS else "mock"
        self.api_key = settings.case_generator_api_key or ""
        self.base_url = (settings.case_generator_base_url or "").rstrip("/")
        self.model = (settings.case_generator_model or DEFAULT_CASE_GENERATOR_MODEL).strip() or DEFAULT_CASE_GENERATOR_MODEL

    def generate(
        self,
        task: EvaluationTask,
        case_count: int,
        difficulty_distribution: List[str],
        user_behavior_types: List[str],
    ) -> List[Dict[str, Any]]:
        task_payload = self._task_payload(task)
        task_type = TargetModelClient().infer_task_type(task_payload)
        fallback = self._mock_generate(task_type, case_count, difficulty_distribution, user_behavior_types)
        if self.provider != "openai_compatible":
            return fallback
        if not self.api_key or not self.base_url:
            return fallback

        rows = self._call_openai_compatible(
            task_payload,
            task_type,
            case_count,
            difficulty_distribution,
            user_behavior_types,
        )
        drafts = self._normalize_many(rows, difficulty_distribution)
        if not drafts:
            return fallback
        return self._fill_with_fallback(drafts, fallback, case_count)

    def _mock_generate(
        self,
        task_type: str,
        case_count: int,
        difficulty_distribution: List[str],
        user_behavior_types: List[str],
    ) -> List[Dict[str, Any]]:
        catalog = self._catalog(task_type)
        requested_difficulties = {item for item in difficulty_distribution if item in VALID_DIFFICULTIES}
        requested_behaviors = {item for item in user_behavior_types if item}

        def matches(item: Dict[str, Any], difficulty: bool, behavior: bool) -> bool:
            if difficulty and requested_difficulties and item.get("difficulty") not in requested_difficulties:
                return False
            if behavior and requested_behaviors and item.get("_behavior_type") not in requested_behaviors:
                return False
            return True

        ordered: List[Dict[str, Any]] = []
        for difficulty, behavior in [(True, True), (False, True), (True, False), (False, False)]:
            ordered.extend(item for item in catalog if matches(item, difficulty, behavior))

        drafts: List[Dict[str, Any]] = []
        seen = set()
        for item in ordered:
            normalized = self._normalize_one(item, difficulty_distribution)
            key = self._draft_key(normalized)
            if key in seen:
                continue
            seen.add(key)
            drafts.append(normalized)
            if len(drafts) >= case_count:
                break
        return drafts

    def _call_openai_compatible(
        self,
        task_payload: Dict[str, Any],
        task_type: str,
        case_count: int,
        difficulty_distribution: List[str],
        user_behavior_types: List[str],
    ) -> List[Dict[str, Any]]:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": self._system_prompt(task_type)},
                {
                    "role": "user",
                    "content": self._user_prompt(
                        task_payload,
                        task_type,
                        case_count,
                        difficulty_distribution,
                        user_behavior_types,
                    ),
                },
            ],
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            logger.warning("case generator openai_compatible request failed: %s", exc)
            return []

        content = ""
        if isinstance(data, dict):
            choices = data.get("choices")
            if choices and isinstance(choices, list):
                content = str(choices[0].get("message", {}).get("content", "") or "")
            else:
                for key in ["content", "text", "message", "output_text"]:
                    if data.get(key):
                        content = str(data[key])
                        break
        return self._safe_json_array(content)

    def _system_prompt(self, task_type: str) -> str:
        required_types = {
            "rider_outbound": "一个递进式完整外呼流程用例，覆盖身份确认、合同已生效、午晚高峰和单量要求、是否开跑、鼓励/安抚、安全提醒、末尾说明排名与保资格规则、结束确认；退出、奖励和超范围问题只在用户主动追问时作为分支处理",
            "course_platform_outbound": "一个强渐进式完整外呼流程用例，主流程按身份确认、知情确认、升级内容、区别/价格、发布方式、配置路径、费用检查、企业微信、结束通话推进；每步内保留非负责人、忙、开车、费用、优惠券、第三方看不到等条件分支，不要拆成多个默认用例",
        }.get(task_type, "正常配合、拒绝配合、情绪不满、反复追问、信息缺失、超范围问题")
        return (
            "你是 callflow-lab 的测试用例生成器。"
            "请根据复杂外呼任务指令生成测试用例草稿，不要生成真实外呼内容，不要保存入库。"
            "只输出合法 JSON 数组，不要 Markdown。"
            "每个数组元素必须包含字段：name, user_profile, initial_message, expected_goals, expected_steps, "
            "required_rules, forbidden_rules, difficulty, max_turns, case_mode, trigger_conditions, "
            "expected_final_state, user_behavior_type, data_source。"
            "expected_goals、expected_steps、required_rules、forbidden_rules、trigger_conditions 必须是字符串数组。"
            "data_source 固定为 ai_generated。"
            "用例要覆盖这些类型：" + required_types + "。"
        )

    def _user_prompt(
        self,
        task_payload: Dict[str, Any],
        task_type: str,
        case_count: int,
        difficulty_distribution: List[str],
        user_behavior_types: List[str],
    ) -> str:
        payload = {
            "task": task_payload,
            "task_type": task_type,
            "case_count": case_count,
            "difficulty_distribution": difficulty_distribution,
            "user_behavior_types": user_behavior_types,
            "rules": [
                "生成的是评测用例草稿，不是模型回复。",
                "用例必须围绕 task.instruction_text，不要写成真实外呼业务系统。",
                "不要串用其他任务业务词。",
            "max_turns 在 1 到 30 之间，分支用例推荐 3 到 6，全流程用例可到 30。",
            ],
            "output_example": [self._example_for_task_type(task_type)],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _example_for_task_type(self, task_type: str) -> Dict[str, Any]:
        if task_type == "course_platform_outbound":
            return {
                "name": COURSE_FULL_FLOW_CASE_NAME,
                "user_profile": "机构负责人，按强渐进流程沟通；每轮只回应一个点，会追问知情、区别、费用、发布方式、配置路径、学员端费用和企业微信。",
                "initial_message": "我是负责人，你说吧。",
                "expected_goals": ["完整覆盖课程直播产品升级主流程", "每步内根据商家回应处理条件分支", "保持 15-20 字内极简电话话术"],
                "expected_steps": list(COURSE_FULL_FLOW_EXPECTED_STEPS),
                "required_rules": ["必须确认负责人", "必须确认是否知情", "必须说明发布页新增标准直播和低延迟直播", "必须询问发布方式并说明配置路径", "必须说明企业微信添加逻辑"],
                "forbidden_rules": ["禁止承诺优惠券或折扣", "禁止使用不专业语气", "禁止长篇解释"],
                "difficulty": "困难",
                "max_turns": 30,
                "trigger_conditions": ["主流程强渐进推进；忙碌先说就1分钟，开车则稍后再打并结束；其他问题在当前步骤内简短作答后回到主流程。"],
                "expected_final_state": "机构负责人理解升级内容并知道后续配置与企业微信安排",
                "user_behavior_type": "强渐进完整流程",
                "case_mode": "full_flow",
                "data_source": "ai_generated",
            }
        if task_type == "rider_outbound":
            return {
                "name": "飞毛腿骑手合同生效外呼用例",
                "user_profile": "递进式综合骑手，先确认本人并愿意开跑，听完高峰和单量要求后接受鼓励、安全提醒，并在收口前追问名额是否由站长决定。",
                "initial_message": "是我，你说。",
                "expected_goals": ["完整覆盖飞毛腿合同生效外呼主流程", "末尾说明排名与保资格规则", "遵守约 30 字以内电话话术"],
                "expected_steps": list(RIDER_FULL_FLOW_EXPECTED_STEPS),
                "required_rules": ["必须说明合同已签署并生效", "必须说明单日/多日合同完成要求", "必须提醒安全", "必须说明报名排名非站长干预和保资格规则"],
                "forbidden_rules": ["禁止强迫配送", "禁止承诺具体奖励金额"],
                "difficulty": "中等",
                "max_turns": 10,
                "trigger_conditions": ["默认按主流程推进，排名与保资格规则放在末尾收口；若用户主动问排名、名额、站长干预、拒单取消超时或恶劣天气，可提前触发解释。"],
                "expected_final_state": "骑手理解合同和飞毛腿规则，按要求配送或知道边界。",
                "user_behavior_type": "递进式完整流程",
                "case_mode": "full_flow",
                "data_source": "ai_generated",
            }
        return {
            "name": "通用反复追问",
            "user_profile": "反复追问外呼对象",
            "initial_message": "你先说清楚，这件事对我有什么影响？",
            "expected_goals": ["回答用户追问", "回到任务目标"],
            "expected_steps": [],
            "required_rules": ["必须回答用户问题", "必须推进任务流程"],
            "forbidden_rules": ["禁止只重复开场"],
            "difficulty": "中等",
            "max_turns": 5,
            "trigger_conditions": ["用户追问影响、原因、下一步"],
            "expected_final_state": "用户获得关键信息",
            "user_behavior_type": "反复追问",
            "case_mode": "branch",
            "data_source": "ai_generated",
        }

    def _safe_json_array(self, content: str) -> List[Dict[str, Any]]:
        try:
            text = content.strip()
            if not text:
                return []
            if text.startswith("{"):
                data = json.loads(text)
                rows = data.get("cases") or data.get("drafts") or data.get("items") or []
                return rows if isinstance(rows, list) else []
            start = text.find("[")
            end = text.rfind("]")
            if start < 0 or end <= start:
                return []
            rows = json.loads(text[start : end + 1])
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return rows if isinstance(rows, list) else []

    def _normalize_many(self, rows: List[Dict[str, Any]], difficulty_distribution: List[str]) -> List[Dict[str, Any]]:
        drafts: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            draft = self._normalize_one(row, difficulty_distribution)
            key = self._draft_key(draft)
            if key in seen:
                continue
            seen.add(key)
            drafts.append(draft)
        return drafts

    def _normalize_one(self, row: Dict[str, Any], difficulty_distribution: List[str]) -> Dict[str, Any]:
        difficulty = str(row.get("difficulty") or "").strip()
        if difficulty not in VALID_DIFFICULTIES:
            difficulty = self._first_difficulty(difficulty_distribution)
        draft = {
            "name": self._text(row.get("name"), "AI 生成测试用例"),
            "user_profile": self._text(row.get("user_profile"), "外呼对象"),
            "initial_message": self._text(row.get("initial_message"), "您好，可以简单说一下。"),
            "expected_goals": self._string_list(row.get("expected_goals")),
            "expected_steps": self._string_list(row.get("expected_steps")),
            "required_rules": self._string_list(row.get("required_rules")),
            "forbidden_rules": self._string_list(row.get("forbidden_rules")),
            "difficulty": difficulty,
            "max_turns": self._max_turns(row.get("max_turns")),
            "trigger_conditions": self._string_list(row.get("trigger_conditions")),
            "expected_final_state": self._text(row.get("expected_final_state"), "用户理解规则或结束咨询"),
            "user_behavior_type": self._text(row.get("user_behavior_type") or row.get("_behavior_type"), "正常配合"),
            "case_mode": str(row.get("case_mode") or "").strip(),
            "data_source": "ai_generated",
        }
        draft["case_mode"] = normalize_case_mode(draft["case_mode"], draft)
        return draft

    def _fill_with_fallback(
        self,
        drafts: List[Dict[str, Any]],
        fallback: List[Dict[str, Any]],
        case_count: int,
    ) -> List[Dict[str, Any]]:
        rows = list(drafts)
        seen = {self._draft_key(item) for item in rows}
        for item in fallback:
            key = self._draft_key(item)
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
            if len(rows) >= case_count:
                break
        return rows[:case_count]

    def _catalog(self, task_type: str) -> List[Dict[str, Any]]:
        if task_type == "rider_outbound":
            return self._rider_catalog()
        if task_type == "course_platform_outbound":
            return self._course_catalog()
        return self._generic_catalog()

    def _rider_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "飞毛腿骑手合同生效外呼用例",
                "user_profile": "递进式综合骑手，先确认本人并愿意开跑，听完高峰和单量要求后接受鼓励、安全提醒，并在收口前追问名额是否由站长决定。",
                "initial_message": "是我，你说。",
                "expected_goals": ["完整覆盖飞毛腿合同生效外呼主流程", "末尾说明排名与保资格规则", "保持电话话术自然且约 30 字以内"],
                "expected_steps": list(RIDER_FULL_FLOW_EXPECTED_STEPS),
                "required_rules": ["必须说明合同已签署并生效", "必须说明单日/多日合同完成要求", "必须提醒安全", "必须说明报名排名非站长干预和保资格规则"],
                "forbidden_rules": ["禁止强迫配送", "禁止承诺具体奖励金额", "禁止编造职责外信息"],
                "difficulty": "中等",
                "max_turns": 10,
                "trigger_conditions": ["默认按主流程推进，排名与保资格规则放在末尾收口；若用户主动问排名、名额、站长干预、拒单取消超时或恶劣天气，可提前触发解释。"],
                "expected_final_state": "骑手理解合同和飞毛腿规则，按要求配送或知道边界。",
                "_behavior_type": "正常配合",
                "case_mode": "full_flow",
            },
        ]

    def _course_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": COURSE_FULL_FLOW_CASE_NAME,
                "user_profile": "机构负责人，按强渐进流程沟通；每轮只回应一个点，会追问知情、区别、费用、发布方式、配置路径、学员端费用和企业微信。",
                "initial_message": "我是负责人，你说吧。",
                "expected_goals": ["完整覆盖课程直播产品升级主流程", "每步内根据商家回应处理条件分支", "保持 15-20 字内极简电话话术"],
                "expected_steps": list(COURSE_FULL_FLOW_EXPECTED_STEPS),
                "required_rules": ["必须确认负责人", "必须确认是否知情", "必须说明发布页新增标准直播和低延迟直播", "必须询问发布方式并说明配置路径", "必须说明企业微信添加逻辑"],
                "forbidden_rules": ["禁止承诺优惠券或折扣", "禁止使用不专业语气", "禁止长篇解释"],
                "difficulty": "困难",
                "max_turns": 30,
                "trigger_conditions": ["主流程强渐进推进；忙碌先说就1分钟，开车则稍后再打并结束；其他问题在当前步骤内简短作答后回到主流程。"],
                "expected_final_state": "机构负责人理解升级内容并知道后续配置与企业微信安排",
                "_behavior_type": "强渐进完整流程",
                "case_mode": "full_flow",
            },
        ]

    def _generic_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "通用正常配合",
                "user_profile": "正常配合外呼对象",
                "initial_message": "您好，可以简单说一下。",
                "expected_goals": ["说明外呼目的", "按任务流程推进"],
                "required_rules": ["必须说明外呼目的", "必须遵守任务约束"],
                "forbidden_rules": ["禁止串用其他业务场景"],
                "difficulty": "简单",
                "max_turns": 4,
                "trigger_conditions": ["用户愿意继续沟通"],
                "expected_final_state": "用户理解外呼目的",
                "_behavior_type": "正常配合",
            },
            {
                "name": "通用拒绝配合",
                "user_profile": "拒绝配合外呼对象",
                "initial_message": "我不想听，你简单点。",
                "expected_goals": ["压缩话术", "尊重拒绝", "保留结束边界"],
                "required_rules": ["必须简短回应", "必须尊重用户拒绝"],
                "forbidden_rules": ["禁止强行推进"],
                "difficulty": "中等",
                "max_turns": 3,
                "trigger_conditions": ["用户拒绝继续沟通"],
                "expected_final_state": "用户听完重点或结束通话",
                "_behavior_type": "拒绝配合",
            },
            {
                "name": "通用情绪不满",
                "user_profile": "情绪不满外呼对象",
                "initial_message": "你们怎么又打电话？到底什么事？",
                "expected_goals": ["先安抚", "说明来意", "避免激化情绪"],
                "required_rules": ["必须安抚情绪", "必须说明任务来意"],
                "forbidden_rules": ["禁止机械重复"],
                "difficulty": "困难",
                "max_turns": 5,
                "trigger_conditions": ["用户表达不满或质疑"],
                "expected_final_state": "用户接受说明或结束通话",
                "_behavior_type": "情绪不满",
            },
            {
                "name": "通用反复追问",
                "user_profile": "反复追问外呼对象",
                "initial_message": "你先说清楚，这件事对我有什么影响？",
                "expected_goals": ["回答用户追问", "回到任务目标", "避免答非所问"],
                "required_rules": ["必须回答用户问题", "必须推进任务流程"],
                "forbidden_rules": ["禁止只重复开场"],
                "difficulty": "中等",
                "max_turns": 5,
                "trigger_conditions": ["用户追问影响、原因、下一步"],
                "expected_final_state": "用户获得关键信息",
                "_behavior_type": "反复追问",
            },
            {
                "name": "通用信息缺失",
                "user_profile": "信息缺失外呼对象",
                "initial_message": "我不太清楚你说的是哪件事。",
                "expected_goals": ["补充必要背景", "确认用户理解", "继续当前任务"],
                "required_rules": ["必须补充任务背景", "必须确认理解情况"],
                "forbidden_rules": ["禁止跳过身份或背景确认"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户表示不知道、不清楚"],
                "expected_final_state": "用户理解当前任务背景",
                "_behavior_type": "信息缺失",
            },
            {
                "name": "通用超范围问题",
                "user_profile": "超范围咨询外呼对象",
                "initial_message": "那你顺便帮我问一下别的业务可以吗？",
                "expected_goals": ["说明当前能力边界", "拉回当前外呼任务"],
                "required_rules": ["必须拒绝超范围承诺", "必须回到当前任务"],
                "forbidden_rules": ["禁止编造职责外信息"],
                "difficulty": "困难",
                "max_turns": 4,
                "trigger_conditions": ["用户询问任务外内容"],
                "expected_final_state": "用户接受边界或结束通话",
                "_behavior_type": "超范围问题",
            },
        ]

    def _task_payload(self, task: EvaluationTask) -> Dict[str, Any]:
        return {
            "id": task.id,
            "name": task.name,
            "description": task.description,
            "target_scenario": task.target_scenario,
            "system_instruction": task.system_instruction,
            "evaluation_goal": task.evaluation_goal,
            "instruction_text": task.instruction_text or "",
            "role_text": task.role_text or "",
            "task_text": task.task_text or "",
            "opening_line": task.opening_line or "",
            "call_flow": task.call_flow or "",
            "knowledge_points": task.knowledge_points or "",
            "constraints": task.constraints or "",
            "task_type": task.task_type or "",
            "data_source": task.data_source or "",
        }

    def _string_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.replace("；", "\n").replace(";", "\n").split("\n") if item.strip()]
        return []

    def _text(self, value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        return text or fallback

    def _max_turns(self, value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = 4
        return max(1, min(30, number))

    def _first_difficulty(self, difficulty_distribution: List[str]) -> str:
        for item in difficulty_distribution:
            if item in VALID_DIFFICULTIES:
                return item
        return "中等"

    def _draft_key(self, draft: Dict[str, Any]) -> str:
        return f"{draft.get('name', '').strip()}::{draft.get('initial_message', '').strip()}"
