from __future__ import annotations

import re
from typing import Any, Dict, List


KnowledgeChunk = Dict[str, Any]


RIDER_RULES = [
    ("退出飞毛腿流程", ["退出", "取消", "报名", "不参加", "不想参加", "哪里取消", "在哪取消", "在哪里取消"], "faq"),
    ("恶劣天气与安全", ["下雨", "雨天", "天气", "危险", "安全"], "faq"),
    ("报名排名规则", ["排名", "名额", "报不上", "排不上", "站长", "拒单", "取消", "超时", "资格", "保住"], "flow"),
    ("合同完成要求", ["单日", "多日", "X单", "X 单", "Y单", "Y 单", "没完成", "影响", "合同", "派单", "单量", "几单", "多少单", "怎么算", "要求"], "faq"),
    ("连续完成激励", ["奖励", "补贴", "激励", "连续", "W 天", "W天"], "faq"),
    ("不想配送挽留", ["不想干", "不干", "不想跑", "不想配送", "不跑", "跑不了", "无法配送", "不一定"], "flow"),
    ("愿意配送鼓励", ["能跑", "可以跑", "开始配送", "今天能跑", "上线"], "flow"),
    ("额外奖励规则", ["奖励", "补贴"], "constraint"),
]

COURSE_RULES = [
    ("标准直播与低延迟直播区别", ["标准直播", "低延迟", "区别", "差多少", "延迟"], "faq"),
    ("价格与费用说明", ["费用", "价格", "便宜", "优惠", "优惠券", "折扣"], "faq"),
    ("发布方式与配置路径", ["Web", "控制台", "第三方", "配置", "设置", "路径", "在哪", "哪里"], "flow"),
    ("企业微信添加逻辑", ["企业微信", "加微信", "手机号", "联系方式"], "faq"),
    ("开车场景处理约束", ["开车", "路上"], "constraint"),
    ("忙碌商家处理约束", ["忙", "没时间", "说重点"], "constraint"),
]

DEFAULT_CHUNKS = {
    "rider_outbound": [
        {
            "chunk_type": "faq",
            "title": "合同完成要求",
            "content": "飞毛腿合同已生效后需确认是否开始配送；单日合同生效当天必须完成 X 单，否则合同及派单可能受到影响；多日合同每天必须完成 Y 单，否则后续合同及派单可能受到影响。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "faq",
            "title": "退出飞毛腿流程",
            "content": "需前一天 Z 点前在 App 的飞毛腿报名中取消，次日生效。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "faq",
            "title": "恶劣天气与安全",
            "content": "遇到下雨、天气危险等情况应先安抚并提醒安全；雨天订单更多，完成有助于保住资格，不能强迫冒险配送。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "flow",
            "title": "不想配送挽留",
            "content": "骑手不想配送或不想干时应先理解安抚并尽量挽留，再说明目前许多骑手正在申请飞毛腿；如果无法连续配送 Y 天，名额可能会被他人占用。还需说明单日/多日未完成会影响合同及派单，并可用连续完成激励挽留；若坚持无法配送，应记录并结束，不强迫。",
            "source": "Conversation Flow",
        },
        {
            "chunk_type": "flow",
            "title": "愿意配送鼓励",
            "content": "骑手表示能配送时应鼓励午晚高峰上线，提醒少拒单、少取消、别超时，并注意交通和餐品安全。",
            "source": "Conversation Flow",
        },
        {
            "chunk_type": "flow",
            "title": "报名排名规则",
            "content": "飞毛腿报名按系统排名，不是站长人工干预；尽量减少拒单、取消、超时，恶劣天气订单更多，有助于保住飞毛腿资格。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "faq",
            "title": "连续完成激励",
            "content": "连续完成 W 天多日合同，且每天完成 Y 单，将获得额外奖励；例如与单日合同相比每单多 +$ 元，具体以平台规则为准。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "constraint",
            "title": "额外奖励规则",
            "content": "可说明脱敏指令中的连续完成 W 天、每天 Y 单、每单多 +$ 元激励；不能承诺知识库外额外奖励、补贴或真实金额。",
            "source": "Constraints",
        },
    ],
    "course_platform_outbound": [
        {
            "chunk_type": "faq",
            "title": "标准直播与低延迟直播区别",
            "content": "标准直播费用较低，延迟约 5-10 秒；低延迟直播延迟约 1-2 秒，互动更流畅。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "faq",
            "title": "价格与费用说明",
            "content": "低延迟直播可能费用更高，具体费用以页面展示为准，不能承诺优惠券或折扣。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "flow",
            "title": "发布方式与配置路径",
            "content": "需先确认使用 Web 控制台还是第三方系统；Web 控制台可在直播发布页直接选择，第三方系统需进入直播平台管理并勾选低延迟直播。",
            "source": "Conversation Flow",
        },
        {
            "chunk_type": "faq",
            "title": "企业微信添加逻辑",
            "content": "企业微信添加应按平台或机构既有规则处理，不泄露个人手机号，不承诺私下添加。",
            "source": "Knowledge Points",
        },
        {
            "chunk_type": "constraint",
            "title": "开车场景处理约束",
            "content": "用户正在开车时应说明稍后再打并结束通话，不继续推销。",
            "source": "Constraints",
        },
        {
            "chunk_type": "constraint",
            "title": "忙碌商家处理约束",
            "content": "用户忙或没时间时应简短挽留，例如说明只占 1 分钟，重点说明后给对方发言机会。",
            "source": "Constraints",
        },
    ],
}


def build_knowledge_chunks(task: Any) -> List[KnowledgeChunk]:
    """Build lightweight task knowledge chunks from instruction fields."""

    task_type = _task_type(task)
    task_id = _get(task, "id", None)
    chunks: List[KnowledgeChunk] = []

    for template in DEFAULT_CHUNKS.get(task_type, []):
        chunks.append({"task_id": task_id, **template})

    field_specs = [
        ("opening", "Opening Line", _get(task, "opening_line", "")),
        ("flow", "Conversation Flow", _get(task, "call_flow", "")),
        ("faq", "Knowledge Points", _get(task, "knowledge_points", "")),
        ("constraint", "Constraints", _get(task, "constraints", "")),
        ("flow", "Instruction Text", _get(task, "instruction_text", "")),
    ]
    for chunk_type, source, value in field_specs:
        for content in _split_source_text(value):
            title = _title_for_content(task_type, content, source)
            chunks.append(
                {
                    "task_id": task_id,
                    "chunk_type": chunk_type,
                    "title": title,
                    "content": content,
                    "source": source,
                }
            )

    return _dedupe_chunks(chunks)


def retrieve_knowledge(task: Any, user_message: str, top_k: int = 3) -> List[KnowledgeChunk]:
    chunks = build_knowledge_chunks(task)
    if not chunks:
        return []

    query = _normalize_text(user_message)
    task_type = _task_type(task)
    scored: List[tuple[int, int, KnowledgeChunk]] = []
    for index, chunk in enumerate(chunks):
        if chunk.get("chunk_type") == "opening":
            continue
        score = _keyword_score(task_type, query, chunk)
        score += _text_overlap_score(query, chunk)
        if score > 0:
            scored.append((score, -index, chunk))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [dict(chunk) for _, _, chunk in scored[: max(1, int(top_k or 3))]]


def _keyword_score(task_type: str, query: str, chunk: KnowledgeChunk) -> int:
    title = str(chunk.get("title", ""))
    rules = RIDER_RULES if task_type == "rider_outbound" else COURSE_RULES if task_type == "course_platform_outbound" else []
    score = 0
    for target_title, keywords, _ in rules:
        if title != target_title:
            continue
        for keyword in keywords:
            if _contains(query, keyword):
                score += 80
    return score


def _text_overlap_score(query: str, chunk: KnowledgeChunk) -> int:
    if not query:
        return 0
    searchable = _normalize_text(f"{chunk.get('title', '')} {chunk.get('content', '')}")
    score = 0
    for token in _query_tokens(query):
        if token and token in searchable:
            score += 8
    return min(score, 40)


def _title_for_content(task_type: str, content: str, source: str) -> str:
    text = _normalize_text(content)
    if source == "Opening Line":
        return "开场白"
    rules = RIDER_RULES if task_type == "rider_outbound" else COURSE_RULES if task_type == "course_platform_outbound" else []
    for title, keywords, _ in rules:
        if any(_contains(text, keyword) for keyword in keywords):
            return title
    if source == "Conversation Flow":
        return _line_title(content, "流程片段")
    if source == "Knowledge Points":
        return _line_title(content, "知识点")
    if source == "Constraints":
        return _line_title(content, "约束规则")
    return _line_title(content, "任务指令片段")


def _split_source_text(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    lines = [
        _clean_line(line)
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    lines = [line for line in lines if line]
    if len(lines) <= 1:
        return [text]
    chunks: List[str] = []
    buffer: List[str] = []
    for line in lines:
        if _looks_like_heading(line) and buffer:
            chunks.append(" ".join(buffer))
            buffer = [line]
        elif len(" ".join(buffer + [line])) > 260 and buffer:
            chunks.append(" ".join(buffer))
            buffer = [line]
        else:
            buffer.append(line)
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks


def _dedupe_chunks(chunks: List[KnowledgeChunk]) -> List[KnowledgeChunk]:
    result: List[KnowledgeChunk] = []
    by_title: Dict[str, int] = {}
    for chunk in chunks:
        title = str(chunk.get("title", "")).strip()
        content = str(chunk.get("content", "")).strip()
        if not title or not content:
            continue
        chunk = {**chunk, "title": title, "content": content}
        if title in by_title:
            continue
        by_title[title] = len(result)
        result.append(chunk)
    return result


def _task_type(task: Any) -> str:
    task_type = str(_get(task, "task_type", "") or "").strip()
    if task_type:
        return task_type
    text = _normalize_text(
        " ".join(
            str(_get(task, key, "") or "")
            for key in ["name", "instruction_text", "task_text", "call_flow", "knowledge_points", "constraints"]
        )
    )
    if any(keyword in text for keyword in ["飞毛腿", "骑手", "配送", "派单"]):
        return "rider_outbound"
    if any(keyword in text for keyword in ["课程", "直播", "低延迟", "机构", "负责人"]):
        return "course_platform_outbound"
    return "generic_outbound"


def _get(task: Any, key: str, default: Any = "") -> Any:
    if isinstance(task, dict):
        return task.get(key, default)
    return getattr(task, key, default)


def _query_tokens(text: str) -> List[str]:
    raw = re.split(r"[\s,，。；;：:、？?！!（）()\[\]【】\"']+", text)
    tokens = [item.strip() for item in raw if len(item.strip()) >= 2]
    known = [
        "退出",
        "取消",
        "报名",
        "下雨",
        "天气",
        "排名",
        "影响",
        "奖励",
        "激励",
        "补贴",
        "标准直播",
        "低延迟",
        "费用",
        "优惠券",
        "Web",
        "控制台",
        "第三方",
        "企业微信",
        "开车",
        "没时间",
    ]
    tokens.extend([item for item in known if _contains(text, item)])
    return list(dict.fromkeys(tokens))


def _normalize_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _contains(text: str, keyword: str) -> bool:
    if keyword in text:
        return True
    compact_text = re.sub(r"\s+", "", text).lower()
    compact_keyword = re.sub(r"\s+", "", keyword).lower()
    return bool(compact_keyword and compact_keyword in compact_text)


def _clean_line(line: str) -> str:
    return re.sub(r"^\s*[-*•\d.、）)]+\s*", "", str(line or "").strip())


def _looks_like_heading(line: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+", line)) or ("：" in line and len(line.split("：", 1)[0]) <= 18)


def _line_title(content: str, fallback: str) -> str:
    text = _clean_line(content)
    for separator in ["：", ":"]:
        if separator in text:
            title = text.split(separator, 1)[0].strip(" #")
            if 2 <= len(title) <= 24:
                return title
    return text[:20].strip(" #") or fallback


def filter_relevant_knowledge(knowledge: List[KnowledgeChunk], assistant_message: str, min_matches: int = 1) -> List[KnowledgeChunk]:
    """Only keep knowledge chunks whose keywords appear in the model's actual reply."""
    if not assistant_message:
        return []
    reply = _normalize_text(assistant_message)
    result: List[KnowledgeChunk] = []
    for chunk in knowledge:
        content = str(chunk.get("content", ""))
        title = str(chunk.get("title", ""))
        searchable = _normalize_text(f"{title} {content}")
        tokens = [t for t in _query_tokens(searchable) if len(t) >= 2]
        matches = sum(1 for t in tokens if t in reply)
        if matches >= min_matches:
            result.append(dict(chunk))
    return result
