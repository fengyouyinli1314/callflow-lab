from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List

from app.core.config import settings
from app.models.task import EvaluationTask
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
            "rider_outbound": "正常愿意配送、不想配送、询问合同影响、询问如何退出飞毛腿、抱怨恶劣天气、质疑报名排名、追问额外奖励、超范围咨询",
            "course_platform_outbound": "负责人正常沟通、非负责人转达、商家说忙、商家说在开车、追问标准直播和低延迟直播区别、询问费用差异、要求优惠券、第三方系统看不到选项、企业微信添加问题、结束前继续追问",
        }.get(task_type, "正常配合、拒绝配合、情绪不满、反复追问、信息缺失、超范围问题")
        return (
            "你是 callflow-lab 的测试用例生成器。"
            "请根据复杂外呼任务指令生成测试用例草稿，不要生成真实外呼内容，不要保存入库。"
            "只输出合法 JSON 数组，不要 Markdown。"
            "每个数组元素必须包含字段：name, user_profile, initial_message, expected_goals, "
            "required_rules, forbidden_rules, difficulty, max_turns, trigger_conditions, "
            "expected_final_state, user_behavior_type, data_source。"
            "expected_goals、required_rules、forbidden_rules、trigger_conditions 必须是字符串数组。"
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
                "max_turns 在 1 到 12 之间，推荐 3 到 6。",
            ],
            "output_example": [self._example_for_task_type(task_type)],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _example_for_task_type(self, task_type: str) -> Dict[str, Any]:
        if task_type == "course_platform_outbound":
            return {
                "name": "课程追问直播区别",
                "user_profile": "反复追问负责人",
                "initial_message": "标准直播和低延迟直播到底有什么区别？",
                "expected_goals": ["说明延迟差异", "说明适用场景"],
                "required_rules": ["必须说明标准直播和低延迟直播区别", "必须说明低延迟适合互动"],
                "forbidden_rules": ["禁止答非所问"],
                "difficulty": "中等",
                "max_turns": 5,
                "trigger_conditions": ["用户追问区别、延迟、适用场景"],
                "expected_final_state": "用户理解直播类型差异",
                "user_behavior_type": "反复追问",
                "data_source": "ai_generated",
            }
        if task_type == "rider_outbound":
            return {
                "name": "骑手质疑报名排名",
                "user_profile": "情绪不满骑手",
                "initial_message": "为什么别人能报上，我报不上？",
                "expected_goals": ["说明报名按排名", "说明不是站长干预"],
                "required_rules": ["必须说明报名按排名", "必须说明不是站长干预"],
                "forbidden_rules": ["禁止承诺一定获得资格"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户提到排名、名额、报不上"],
                "expected_final_state": "用户理解规则或结束咨询",
                "user_behavior_type": "情绪不满",
                "data_source": "ai_generated",
            }
        return {
            "name": "通用反复追问",
            "user_profile": "反复追问外呼对象",
            "initial_message": "你先说清楚，这件事对我有什么影响？",
            "expected_goals": ["回答用户追问", "回到任务目标"],
            "required_rules": ["必须回答用户问题", "必须推进任务流程"],
            "forbidden_rules": ["禁止只重复开场"],
            "difficulty": "中等",
            "max_turns": 5,
            "trigger_conditions": ["用户追问影响、原因、下一步"],
            "expected_final_state": "用户获得关键信息",
            "user_behavior_type": "反复追问",
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
        return {
            "name": self._text(row.get("name"), "AI 生成测试用例"),
            "user_profile": self._text(row.get("user_profile"), "外呼对象"),
            "initial_message": self._text(row.get("initial_message"), "您好，可以简单说一下。"),
            "expected_goals": self._string_list(row.get("expected_goals")),
            "required_rules": self._string_list(row.get("required_rules")),
            "forbidden_rules": self._string_list(row.get("forbidden_rules")),
            "difficulty": difficulty,
            "max_turns": self._max_turns(row.get("max_turns")),
            "trigger_conditions": self._string_list(row.get("trigger_conditions")),
            "expected_final_state": self._text(row.get("expected_final_state"), "用户理解规则或结束咨询"),
            "user_behavior_type": self._text(row.get("user_behavior_type") or row.get("_behavior_type"), "正常配合"),
            "data_source": "ai_generated",
        }

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
                "name": "骑手正常愿意配送",
                "user_profile": "正常配合骑手",
                "initial_message": "合同生效了是吗？那我今天可以开始跑吗？",
                "expected_goals": ["确认合同已生效", "说明可以开始配送", "提示完成要求"],
                "required_rules": ["必须说明合同已生效", "必须说明可以开始配送"],
                "forbidden_rules": ["禁止承诺一定获得更多派单"],
                "difficulty": "简单",
                "max_turns": 3,
                "trigger_conditions": ["用户表示愿意配送、询问能否开始"],
                "expected_final_state": "用户确认开始配送",
                "_behavior_type": "正常配合",
            },
            {
                "name": "骑手暂时不想配送",
                "user_profile": "拒绝配合骑手",
                "initial_message": "我今天不想跑了，可以不配送吗？",
                "expected_goals": ["先理解拒绝原因", "说明未完成可能影响合同和派单", "避免强迫配送"],
                "required_rules": ["必须说明未完成影响", "必须保留安全和自愿边界"],
                "forbidden_rules": ["禁止强迫骑手配送", "禁止威胁或夸大后果"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户明确表示不想配送"],
                "expected_final_state": "用户了解影响后自行决定",
                "_behavior_type": "拒绝配合",
            },
            {
                "name": "骑手询问合同影响",
                "user_profile": "反复追问骑手",
                "initial_message": "如果今天没完成 X 单，会影响合同和派单吗？",
                "expected_goals": ["说明单日 X 单要求", "说明合同和派单可能受影响"],
                "required_rules": ["必须说明 X 单要求", "必须说明合同和派单影响"],
                "forbidden_rules": ["禁止给出职责外承诺"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户提到 X 单、合同、派单影响"],
                "expected_final_state": "用户理解完成要求",
                "_behavior_type": "反复追问",
            },
            {
                "name": "骑手询问退出飞毛腿",
                "user_profile": "信息咨询骑手",
                "initial_message": "我想退出飞毛腿，应该在哪里取消？",
                "expected_goals": ["说明前一天 Z 点前取消", "说明在 App 报名页操作"],
                "required_rules": ["必须说明退出时间要求", "必须说明 App 报名页路径"],
                "forbidden_rules": ["禁止代替用户取消", "禁止承诺一定取消成功"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户提到退出、取消、不参加"],
                "expected_final_state": "用户知道退出路径",
                "_behavior_type": "信息缺失",
            },
            {
                "name": "骑手抱怨恶劣天气",
                "user_profile": "情绪不满骑手",
                "initial_message": "外面雨太大了，非要我现在接单吗？",
                "expected_goals": ["先安抚情绪", "提醒安全第一", "说明能跑再接单"],
                "required_rules": ["必须提醒安全", "必须避免强迫恶劣天气配送"],
                "forbidden_rules": ["禁止强迫冒险配送", "禁止忽视用户情绪"],
                "difficulty": "困难",
                "max_turns": 5,
                "trigger_conditions": ["用户提到下雨、恶劣天气、危险"],
                "expected_final_state": "用户接受安全优先或结束通话",
                "_behavior_type": "情绪不满",
            },
            {
                "name": "骑手质疑报名排名",
                "user_profile": "情绪不满骑手",
                "initial_message": "为什么别人能报上，我报不上？",
                "expected_goals": ["说明报名按排名", "说明不是站长干预"],
                "required_rules": ["必须说明报名按排名", "必须说明不是站长干预"],
                "forbidden_rules": ["禁止承诺一定获得资格"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户提到排名、名额、报不上"],
                "expected_final_state": "用户理解规则或结束咨询",
                "_behavior_type": "情绪不满",
            },
            {
                "name": "骑手追问额外奖励",
                "user_profile": "反复追问骑手",
                "initial_message": "完成 X 单之外还有额外奖励吗？你能保证吗？",
                "expected_goals": ["只说明当前任务已知要求", "不承诺额外奖励", "引导以页面规则为准"],
                "required_rules": ["必须避免编造额外奖励", "必须说明以当前规则为准"],
                "forbidden_rules": ["禁止承诺额外奖励", "禁止编造未给出的政策"],
                "difficulty": "困难",
                "max_turns": 5,
                "trigger_conditions": ["用户追问奖励、补贴、保证"],
                "expected_final_state": "用户知道未承诺额外奖励",
                "_behavior_type": "反复追问",
            },
            {
                "name": "骑手超范围咨询",
                "user_profile": "超范围咨询骑手",
                "initial_message": "我还想问一下其他平台活动规则，你能一起解释吗？",
                "expected_goals": ["说明只能处理当前飞毛腿任务", "回到合同生效和配送要求"],
                "required_rules": ["必须拒绝超范围解释", "必须拉回当前任务"],
                "forbidden_rules": ["禁止编造其他平台规则"],
                "difficulty": "困难",
                "max_turns": 4,
                "trigger_conditions": ["用户询问当前任务外的平台规则"],
                "expected_final_state": "用户接受边界或结束咨询",
                "_behavior_type": "超范围问题",
            },
        ]

    def _course_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "课程负责人正常沟通",
                "user_profile": "正常配合负责人",
                "initial_message": "我是负责人，你说吧。",
                "expected_goals": ["确认负责人身份", "说明发布页升级", "说明标准直播和低延迟直播"],
                "required_rules": ["必须确认负责人", "必须说明直播发布页升级"],
                "forbidden_rules": ["禁止长篇介绍"],
                "difficulty": "简单",
                "max_turns": 5,
                "trigger_conditions": ["用户确认自己是负责人"],
                "expected_final_state": "负责人理解升级内容",
                "_behavior_type": "正常配合",
            },
            {
                "name": "课程非负责人转达",
                "user_profile": "非负责人前台",
                "initial_message": "我不是负责人，我只是前台。",
                "expected_goals": ["请对方转达负责人", "简短说明发布页升级"],
                "required_rules": ["必须请对方转达", "必须简短说明升级内容"],
                "forbidden_rules": ["禁止强行继续推销"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户说明不是负责人"],
                "expected_final_state": "用户愿意转达或结束通话",
                "_behavior_type": "信息缺失",
            },
            {
                "name": "课程商家说忙",
                "user_profile": "时间紧张商家",
                "initial_message": "我现在很忙，能不能别说太久？",
                "expected_goals": ["压缩话术", "说明只需一分钟", "优先传达升级重点"],
                "required_rules": ["必须简短回应", "必须尊重用户忙碌状态"],
                "forbidden_rules": ["禁止继续长篇介绍"],
                "difficulty": "中等",
                "max_turns": 3,
                "trigger_conditions": ["用户说忙、没时间"],
                "expected_final_state": "用户听完重点或约定稍后",
                "_behavior_type": "拒绝配合",
            },
            {
                "name": "课程商家开车场景",
                "user_profile": "正在开车商家",
                "initial_message": "我在开车，不方便听。",
                "expected_goals": ["立即停止介绍", "提醒安全", "约定稍后再打"],
                "required_rules": ["必须安全结束", "必须避免继续推销"],
                "forbidden_rules": ["禁止在开车场景继续介绍"],
                "difficulty": "困难",
                "max_turns": 2,
                "trigger_conditions": ["用户说在开车、不方便听"],
                "expected_final_state": "安全结束通话",
                "_behavior_type": "拒绝配合",
            },
            {
                "name": "课程追问直播区别",
                "user_profile": "反复追问负责人",
                "initial_message": "标准直播和低延迟直播到底有什么区别？",
                "expected_goals": ["说明延迟差异", "说明适用场景", "避免过度展开"],
                "required_rules": ["必须说明标准直播和低延迟直播区别", "必须说明低延迟适合互动"],
                "forbidden_rules": ["禁止答非所问"],
                "difficulty": "中等",
                "max_turns": 5,
                "trigger_conditions": ["用户追问区别、延迟、适用场景"],
                "expected_final_state": "用户理解直播类型差异",
                "_behavior_type": "反复追问",
            },
            {
                "name": "课程询问费用差异",
                "user_profile": "关注成本负责人",
                "initial_message": "低延迟直播会不会更贵？费用怎么算？",
                "expected_goals": ["说明费用可能有差异", "以页面或配置为准", "避免承诺具体价格"],
                "required_rules": ["必须说明费用差异边界", "必须避免编造价格"],
                "forbidden_rules": ["禁止承诺具体费用不变"],
                "difficulty": "困难",
                "max_turns": 5,
                "trigger_conditions": ["用户询问费用、价格、计费"],
                "expected_final_state": "用户知道费用以页面为准",
                "_behavior_type": "反复追问",
            },
            {
                "name": "课程要求优惠券",
                "user_profile": "索要优惠商家",
                "initial_message": "那你们能不能给我优惠券？",
                "expected_goals": ["说明不能承诺优惠券", "回到升级说明和配置路径"],
                "required_rules": ["必须拒绝承诺优惠券", "必须说明以页面规则为准"],
                "forbidden_rules": ["禁止承诺发放优惠券"],
                "difficulty": "困难",
                "max_turns": 4,
                "trigger_conditions": ["用户要求优惠券、优惠、减免"],
                "expected_final_state": "用户理解不能承诺优惠",
                "_behavior_type": "超范围问题",
            },
            {
                "name": "课程第三方系统看不到选项",
                "user_profile": "技术不熟悉商家",
                "initial_message": "我第三方系统里看不到低延迟直播选项。",
                "expected_goals": ["确认第三方系统路径", "引导进入直播平台管理", "说明选项显示边界"],
                "required_rules": ["必须按第三方系统路径引导", "必须避免让用户误走 Web 控制台"],
                "forbidden_rules": ["禁止给出不确定配置承诺"],
                "difficulty": "困难",
                "max_turns": 6,
                "trigger_conditions": ["用户提到第三方系统、看不到选项"],
                "expected_final_state": "用户知道下一步查看路径",
                "_behavior_type": "信息缺失",
            },
            {
                "name": "课程企业微信添加问题",
                "user_profile": "需要后续对接商家",
                "initial_message": "这个问题后面要加企业微信吗？加谁？",
                "expected_goals": ["说明企业微信添加边界", "确认后续对接方式", "避免泄露或编造联系人"],
                "required_rules": ["必须说明按任务要求添加或转达", "必须避免编造联系人"],
                "forbidden_rules": ["禁止编造企业微信账号"],
                "difficulty": "中等",
                "max_turns": 4,
                "trigger_conditions": ["用户提到企业微信、加谁、后续联系"],
                "expected_final_state": "用户知道后续联系边界",
                "_behavior_type": "信息缺失",
            },
            {
                "name": "课程结束前继续追问",
                "user_profile": "结束前继续追问负责人",
                "initial_message": "等等，最后再问一下在哪里配置？",
                "expected_goals": ["承接继续追问", "询问 Web 控制台或第三方系统", "给出对应路径"],
                "required_rules": ["必须回答配置位置", "必须根据发布方式区分路径"],
                "forbidden_rules": ["禁止直接结束忽略追问"],
                "difficulty": "困难",
                "max_turns": 5,
                "trigger_conditions": ["用户在结束前继续追问配置位置"],
                "expected_final_state": "用户获得配置路径后结束",
                "_behavior_type": "反复追问",
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
        return max(1, min(12, number))

    def _first_difficulty(self, difficulty_distribution: List[str]) -> str:
        for item in difficulty_distribution:
            if item in VALID_DIFFICULTIES:
                return item
        return "中等"

    def _draft_key(self, draft: Dict[str, Any]) -> str:
        return f"{draft.get('name', '').strip()}::{draft.get('initial_message', '').strip()}"
