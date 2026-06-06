import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.case import EvaluationCase
from app.models.run import EvaluationRun, RunMessage
from app.models.task import EvaluationTask
from app.schemas.run import (
    MessageRead,
    QuickCheckRequest,
    QuickCheckResponse,
    RunRead,
    RunStartRequest,
    RunStartResponse,
)
from app.services.evaluation_service import EvaluationService
from app.services.memory_service import load_memory
from app.services.rule_judge import RuleJudge
from app.services.target_model_client import TargetModelClient, TargetModelError


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("/start", response_model=RunStartResponse)
def start_run(payload: RunStartRequest, session: Session = Depends(get_session)) -> dict:
    return EvaluationService(session).start_evaluation(
        payload.task_id,
        payload.case_id,
        payload.model_provider,
        payload.model_name,
    )


@router.post("/stream")
def stream_run(payload: RunStartRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    events = EvaluationService(session).stream_evaluation_events(
        payload.task_id,
        payload.case_id,
        payload.model_provider,
        payload.model_name,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/quick-check", response_model=QuickCheckResponse)
def quick_check(payload: QuickCheckRequest, session: Session = Depends(get_session)) -> Dict[str, Any]:
    task = session.get(EvaluationTask, payload.task_id)
    case = session.get(EvaluationCase, payload.case_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if not case or case.task_id != task.id:
        raise HTTPException(status_code=404, detail="case not found for task")

    user_messages = [text.strip() for text in payload.user_messages if str(text or "").strip()]
    if not user_messages:
        raise HTTPException(status_code=400, detail="请至少输入一句用户发言")
    if len(user_messages) > 12:
        raise HTTPException(status_code=400, detail="快速检测最多支持 12 句用户发言")

    service = EvaluationService(session)
    task_payload = service._task_payload(task)
    case_payload = service._case_payload(case)
    target_model = TargetModelClient(payload.model_provider, payload.model_name)
    rule_judge = RuleJudge()
    task_type = target_model.infer_task_type(task_payload, case_payload)
    model_info = target_model.model_info()
    opening_history: List[Dict[str, Any]] = []
    turns: List[Dict[str, Any]] = []
    fallback_used = False
    memory_state: Dict[str, Any] = {
        "quick_check": True,
        "task_id": task.id,
        "case_id": case.id,
        "planned_max_turns": len(user_messages),
    }

    if payload.include_opening and service._should_start_with_opening(task_payload, case_payload, task_type):
        started = time.perf_counter()
        try:
            opening_result = target_model.generate_opening_reply(task_payload, case_payload, opening_history, memory_state)
        except TargetModelError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        opening_score = service._score_opening_turn(task_payload, case_payload, opening_result.content, latency_ms)
        fallback_used = fallback_used or opening_result.fallback_used
        opening_item = {
            "turn_index": 0,
            "user_message": "",
            "assistant_message": opening_result.content,
            "latency_ms": latency_ms,
            "rule_score": opening_score["score"],
            "matched_rules": opening_score["matched_rules"],
            "missed_rules": opening_score["missed_rules"],
            "violated_rules": opening_score["violated_rules"],
            "detail": {
                "reason": opening_score["reason"],
                "active_rules": opening_score.get("active_rules", {}),
                "pending_rules": opening_score.get("pending_rules", []),
                "untriggered_rules": opening_score.get("untriggered_rules", []),
                "current_stage": opening_score.get("current_stage", ""),
                "retrieved_knowledge": opening_result.retrieved_knowledge,
            },
        }
        opening_history.append(opening_item)
        turns.append(_quick_turn(opening_item, opening_result.fallback_used))

    for index, user_message in enumerate(user_messages, start=1):
        turn_history = list(opening_history)
        started = time.perf_counter()
        try:
            target_result = target_model.generate_reply(
                task_payload,
                case_payload,
                user_message,
                turn_history,
                memory_state,
            )
        except TargetModelError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        turn_item = {
            "turn_index": index,
            "user_message": user_message,
            "assistant_message": target_result.content,
            "latency_ms": latency_ms,
        }
        turn_score = rule_judge.score_turn(case_payload, turn_history + [turn_item], latency_ms, task_payload)
        turn_score = _quick_single_turn_score(task_type, user_message, target_result.content, turn_score)
        fallback_used = fallback_used or target_result.fallback_used
        turn_item.update(
            {
                "rule_score": turn_score["score"],
                "matched_rules": turn_score["matched_rules"],
                "missed_rules": turn_score["missed_rules"],
                "violated_rules": turn_score["violated_rules"],
                "detail": {
                    "reason": turn_score["reason"],
                    "active_rules": turn_score.get("active_rules", {}),
                    "pending_rules": turn_score.get("pending_rules", []),
                    "untriggered_rules": turn_score.get("untriggered_rules", []),
                    "current_stage": turn_score.get("current_stage", ""),
                    "retrieved_knowledge": target_result.retrieved_knowledge,
                },
            }
        )
        turns.append(_quick_turn(turn_item, target_result.fallback_used))

    scored_turns = [turn for turn in turns if turn.get("user_message")]
    total_score = round(
        sum(float(turn.get("rule_score", 0)) for turn in scored_turns) / max(len(scored_turns), 1),
        2,
    )
    return {
        "success": True,
        "task_id": task.id,
        "case_id": case.id,
        "task_type": task_type,
        "provider_used": model_info["model_provider"],
        "model_name": model_info["model_name"],
        "fallback_used": fallback_used,
        "total_score": total_score,
        "matched_rules": _dedupe_quick_rules(turns, "matched_rules"),
        "failed_rules": _dedupe_quick_rules(turns, "missed_rules") + _dedupe_quick_rules(turns, "violated_rules"),
        "pending_rules": _dedupe_quick_rules(turns, "pending_rules"),
        "turns": turns,
        "message": "quick check finished",
    }


def _quick_single_turn_score(
    task_type: str,
    user_message: str,
    assistant_message: str,
    turn_score: Dict[str, Any],
) -> Dict[str, Any]:
    fact_checks = _quick_required_facts(task_type, user_message, assistant_message)
    if not fact_checks:
        return turn_score

    matched = [label for label, passed in fact_checks if passed]
    missed = [label for label, passed in fact_checks if not passed]
    violated = list(turn_score.get("violated_rules") or [])
    score = 100 * len(matched) / max(len(fact_checks), 1) - 25 * len(violated)
    quick_score = dict(turn_score)
    quick_score["score"] = round(max(0, min(100, score)), 2)
    quick_score["matched_rules"] = matched
    quick_score["missed_rules"] = missed
    quick_score["violated_rules"] = violated
    quick_score["failed_rules"] = missed + violated
    quick_score["reason"] = (
        f"单条问答检测：必要事实命中 {len(matched)}/{len(fact_checks)}，"
        f"违规 {len(violated)} 条。"
    )
    return quick_score


def _quick_required_facts(task_type: str, user_message: str, assistant_message: str) -> List[tuple[str, bool]]:
    user = str(user_message or "")
    assistant = str(assistant_message or "")
    if task_type == "rider_outbound":
        if _has_any(user, ["开车", "路上", "不方便说"]):
            return [
                ("说明稍后再联系", _has_any(assistant, ["稍后", "再打", "再联系", "方便时", "不打扰"])),
                ("不继续推进配送", not _has_any(assistant, ["合同已生效", "开始配送", "配送吗", "X 单", "Y 单", "高峰"])),
            ]
        if _has_any(user, ["退出", "取消", "不参加", "怎么退"]):
            return [
                ("说明前一天 Z 点前取消", _has_all(assistant, ["前一天", "Z"])),
                ("说明在 App 的飞毛腿报名中取消", _has_any(assistant, ["App", "应用"]) and _has_any(assistant, ["飞毛腿报名", "报名"])),
                ("说明次日生效", _has_any(assistant, ["次日生效", "第二天生效", "明天生效"])),
            ]
        if _has_any(user, ["排名", "名额", "排不上", "报不上"]):
            return [
                ("说明按系统排名", _has_any(assistant, ["系统排名", "按排名", "系统排"])),
                ("说明不是站长决定", _has_any(assistant, ["不是站长", "非站长", "站长不能"])),
                ("说明少拒单取消超时有助保资格", _has_any(assistant, ["拒单", "取消", "超时"]) and _has_any(assistant, ["资格", "保"])),
            ]
        if _has_any(user, ["奖励", "补贴", "额外", "加钱"]):
            return [
                ("说明连续完成可能有额外奖励", _has_any(assistant, ["连续", "额外奖励", "奖励"])),
                ("不编造具体金额", not _has_any(assistant, ["100", "200", "具体金额", "一定给"])),
            ]
        if _has_any(user, ["好处", "优势", "有什么用", "有啥用", "为什么参加"]):
            return [
                ("说明完成有助保资格", _has_any(assistant, ["资格", "保资格", "保住"])),
                ("说明连续达标可能有额外奖励", _has_any(assistant, ["连续", "达标", "奖励", "额外"])),
                ("不回到主流程开场", not _has_any(assistant, ["合同已生效", "开始配送吗"])),
            ]
        if _has_any(user, ["下雨", "天气", "危险", "安全"]):
            return [
                ("先安抚安全", _has_any(assistant, ["安全", "注意", "理解"])),
                ("不强迫冒险配送", not _has_any(assistant, ["必须跑", "一定要跑", "强制"])),
            ]
    if task_type == "course_platform_outbound":
        if _has_any(user, ["区别", "标准", "低延迟", "差在哪"]):
            return [
                ("说明标准直播延迟 5-10 秒", _has_any(assistant, ["5-10秒", "5 到 10 秒", "5至10秒"])),
                ("说明低延迟 1-2 秒", _has_any(assistant, ["1-2秒", "1 到 2 秒", "1至2秒"])),
                ("说明低延迟互动更流畅", _has_any(assistant, ["互动", "流畅", "实时"])),
            ]
        if _has_any(user, ["费用", "贵", "价格", "优惠"]):
            return [
                ("说明低延迟费用可能更高", _has_any(assistant, ["费用", "价格"]) and _has_any(assistant, ["高", "贵"])),
                ("不承诺优惠券或折扣", not _has_any(assistant, ["优惠券", "折扣", "打折"])),
            ]
        if _has_any(user, ["怎么联系", "企业微信", "加微信"]):
            return [
                ("说明企业微信添加或验证", _has_any(assistant, ["企业微信", "验证", "加您", "添加"])),
            ]
        if _has_any(user, ["开车", "不方便"]):
            return [
                ("说明稍后再联系", _has_any(assistant, ["稍后", "再打", "方便时"])),
                ("不继续推销", not _has_any(assistant, ["升级", "低延迟", "费用"])),
            ]
    return []


def _has_any(text: str, keywords: List[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def _has_all(text: str, keywords: List[str]) -> bool:
    return all(keyword and keyword in text for keyword in keywords)


def _dedupe_quick_rules(turns: List[Dict[str, Any]], key: str) -> List[str]:
    items: List[str] = []
    for turn in turns:
        items.extend(turn.get(key) or [])
    return list(dict.fromkeys(items))


def _quick_turn(item: Dict[str, Any], fallback_used: bool) -> Dict[str, Any]:
    detail = item.get("detail") or {}
    return {
        "turn_index": item.get("turn_index", 0),
        "user_message": item.get("user_message", ""),
        "assistant_message": item.get("assistant_message", ""),
        "latency_ms": item.get("latency_ms", 0),
        "rule_score": item.get("rule_score", 0),
        "matched_rules": item.get("matched_rules", []),
        "missed_rules": item.get("missed_rules", []),
        "violated_rules": item.get("violated_rules", []),
        "active_rules": detail.get("active_rules", {}),
        "pending_rules": detail.get("pending_rules", []),
        "untriggered_rules": detail.get("untriggered_rules", []),
        "current_stage": detail.get("current_stage", ""),
        "reason": detail.get("reason", ""),
        "retrieved_knowledge": detail.get("retrieved_knowledge", []),
        "fallback_used": fallback_used,
    }


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: int, session: Session = Depends(get_session)) -> EvaluationRun:
    run = session.get(EvaluationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if not run.memory_state:
        run.memory_state = load_memory(run)
    return run


@router.get("/{run_id}/messages", response_model=List[MessageRead])
def get_run_messages(run_id: int, session: Session = Depends(get_session)) -> List[RunMessage]:
    if not session.get(EvaluationRun, run_id):
        raise HTTPException(status_code=404, detail="run not found")
    statement = select(RunMessage).where(RunMessage.run_id == run_id).order_by(RunMessage.turn_index)
    return list(session.exec(statement).all())
