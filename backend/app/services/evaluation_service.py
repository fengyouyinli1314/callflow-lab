from __future__ import annotations

import time
import logging
import json
from datetime import datetime
from typing import Any, Dict, Iterator

from fastapi import HTTPException
from sqlmodel import Session

from app.models.case import EvaluationCase
from app.models.run import EvaluationRun, RunMessage
from app.models.task import EvaluationTask
from app.services.case_mode import normalize_case_mode
from app.services.agents.evaluator_agent import EvaluatorAgent
from app.services.conversation_memory import initialize_memory_state, update_memory_state
from app.services.course_flow import (
    COURSE_CRITICAL_STEPS_BEFORE_STOP,
    course_full_flow_expected_steps,
    course_full_flow_step_done,
)
from app.services.report_service import ReportService
from app.services.rule_judge import RuleJudge
from app.services.memory_service import (
    load_memory,
    reset_memory_for_new_run,
    save_memory,
    update_after_model,
    update_after_user,
)
from app.services.rider_flow import (
    RIDER_CRITICAL_STEPS_BEFORE_STOP,
    rider_full_flow_expected_steps,
    rider_rank_qualification_done,
)
from app.services.target_model_client import TargetModelClient, TargetModelError, normalize_target_provider
from app.services.knowledge_base import filter_relevant_knowledge
from app.services.user_simulator import UserSimulator


logger = logging.getLogger(__name__)


class EvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.user_simulator = UserSimulator()
        self.target_model = TargetModelClient()
        self.rule_judge = RuleJudge()
        self.evaluator_agent = EvaluatorAgent()

    def start_evaluation(
        self,
        task_id: int,
        case_id: int,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> Dict[str, Any]:
        task = self.session.get(EvaluationTask, task_id)
        case = self.session.get(EvaluationCase, case_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        if not case or case.task_id != task_id:
            raise HTTPException(status_code=404, detail="case not found for task")

        self.target_model = TargetModelClient(model_provider, model_name)
        model_info = self.target_model.model_info()
        provider_requested = normalize_target_provider(model_provider) if model_provider else model_info["model_provider"]
        run = EvaluationRun(
            task_id=task_id,
            case_id=case_id,
            status="running",
            model_provider=model_info["model_provider"],
            model_name=model_info["model_name"],
            memory_state=reset_memory_for_new_run(task, case),
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        run_memory = self._attach_run_context(run)

        task_payload = self._task_payload(task)
        case_payload = self._case_payload(case)
        task_type = self.target_model.infer_task_type(task_payload, case_payload)
        logger.info(
            "callflow trace: POST /api/runs/start -> EvaluationService.start_evaluation -> TargetModelClient.generate_reply task_id=%s case_id=%s task_type=%s",
            task_id,
            case_id,
            task_type,
        )
        history: list[dict[str, Any]] = []
        fallback_used = False
        planned_max_turns = self._planned_max_turns(case_payload, task_type)
        memory_state = initialize_memory_state(task_payload, case_payload, task_type, planned_max_turns, run.id)
        memory_state["run_context"] = run_memory.get("run_context", {})
        if self._should_start_with_opening(task_payload, case_payload, task_type):
            started = time.perf_counter()
            try:
                opening_result = self.target_model.generate_opening_reply(
                    task_payload,
                    case_payload,
                    history,
                    memory_state=memory_state,
                )
            except TargetModelError as exc:
                return self._target_error_response(run, provider_requested, model_info, task_type, exc)
            fallback_used = fallback_used or bool(opening_result.fallback_used)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            opening_score = self._score_opening_turn(task_payload, case_payload, opening_result.content, latency_ms)
            memory_state = update_memory_state(
                memory_state,
                task_payload,
                case_payload,
                [
                    {
                        "turn_index": 0,
                        "user_message": "",
                        "assistant_message": opening_result.content,
                        "latency_ms": latency_ms,
                    }
                ],
                turn_index=0,
                planned_max_turns=planned_max_turns,
                turn_score=opening_score,
                target_result=opening_result,
            )
            run_memory = update_after_model(load_memory(run), opening_result.content, opening_score)
            save_memory(self.session, run, run_memory)
            opening_message = self._persist_opening_message(
                run=run,
                task_payload=task_payload,
                case_payload=case_payload,
                opening_result=opening_result,
                opening_score=opening_score,
                latency_ms=latency_ms,
                planned_max_turns=planned_max_turns,
                memory_state=memory_state,
            )
            history.append(self._history_item(opening_message))

        for turn_index in range(1, planned_max_turns + 1):
            run_memory = load_memory(run)
            user_turn = self._normalize_user_turn(
                self.user_simulator.generate_message(
                    task_payload,
                    case_payload,
                    history,
                    turn_index,
                    memory_state=run_memory,
                ),
                case.initial_message,
            )
            user_message = user_turn["content"]
            run_memory = update_after_user(run_memory, user_message, user_turn.get("metadata", {}))
            run_memory = save_memory(self.session, run, run_memory)
            started = time.perf_counter()
            try:
                target_result = self.target_model.generate_reply(
                    task_payload,
                    case_payload,
                    user_message,
                    history,
                    memory_state=run_memory,
                )
            except TargetModelError as exc:
                run.status = "failed"
                run.finished_at = datetime.utcnow()
                self.session.add(run)
                self.session.commit()
                logger.error(
                    "evaluation failed target model error run_id=%s provider_requested=%s provider_used=%s error_code=%s",
                    run.id,
                    provider_requested,
                    model_info["model_provider"],
                    exc.code,
                )
                return self._target_error_response(run, provider_requested, model_info, task_type, exc, commit=False)
            assistant_message = target_result.content
            fallback_used = fallback_used or bool(target_result.fallback_used)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)

            turn_history = history + [
                {
                    "turn_index": turn_index,
                    "user_message": user_message,
                    "assistant_message": assistant_message,
                    "latency_ms": latency_ms,
                }
            ]
            turn_score = self.rule_judge.score_turn(case_payload, turn_history, latency_ms, task_payload)
            user_state = dict(user_turn.get("user_state", {}) or {})
            stop_decision = self._stop_decision(
                task_payload=task_payload,
                case_payload=case_payload,
                history=turn_history,
                turn_score=turn_score,
                user_turn=user_turn,
                target_should_close=target_result.should_close,
                turn_index=turn_index,
                planned_max_turns=planned_max_turns,
            )
            if stop_decision["should_stop"] and target_result.should_close and user_state.get("goal_progress") != "rejected":
                user_state["goal_progress"] = "accepted"
                user_state["current_intent"] = "接受并结束"
            if not stop_decision["should_stop"] and user_state.get("goal_progress") == "accepted":
                user_state["goal_progress"] = "in_progress"
                user_state["current_intent"] = "继续覆盖全流程"
            user_turn["user_state"] = user_state
            memory_state = update_memory_state(
                memory_state,
                task_payload,
                case_payload,
                turn_history,
                turn_index=turn_index,
                planned_max_turns=planned_max_turns,
                turn_score=turn_score,
                user_turn=user_turn,
                target_result=target_result,
                stop_decision=stop_decision,
            )
            run_memory = update_after_model(load_memory(run), assistant_message, turn_score)
            run_memory = save_memory(self.session, run, run_memory)
            message = RunMessage(
                run_id=run.id,
                turn_index=turn_index,
                user_message=user_message,
                assistant_message=assistant_message,
                latency_ms=latency_ms,
                rule_score=turn_score["score"],
                matched_rules=turn_score["matched_rules"],
                missed_rules=turn_score["missed_rules"],
                violated_rules=turn_score["violated_rules"],
                detail={
                    "reason": turn_score["reason"],
                    "active_rules": turn_score.get("active_rules", {}),
                    "pending_rules": turn_score.get("pending_rules", []),
                    "untriggered_rules": turn_score.get("untriggered_rules", []),
                    "not_applicable_rules": turn_score.get("not_applicable_rules", []),
                    "visible_business_rules": turn_score.get("visible_business_rules", {}),
                    "hidden_guardrail_rules": turn_score.get("hidden_guardrail_rules", {}),
                    "rule_lifecycle": turn_score.get("rule_lifecycle", {}),
                    "late_satisfied_rules": turn_score.get("late_satisfied_rules", []),
                    "case_focus": turn_score.get("case_focus", ""),
                    "active_rule_names": turn_score.get("active_rule_names", []),
                    "current_stage": turn_score.get("current_stage", ""),
                    "deduction_reason": turn_score.get("deduction_reason", ""),
                    "active_rules_explanation": turn_score.get("active_rules_explanation", ""),
                    "user_state": user_state,
                    "user_intent": user_turn.get("intent", ""),
                    "user_metadata": user_turn.get("metadata", {}),
                    "should_continue": user_turn.get("should_continue", True),
                    "model_provider": target_result.provider,
                    "model_name": target_result.model_name,
                    "target_fallback_used": target_result.fallback_used,
                    "task_type": target_result.task_type,
                    "target_call_chain": target_result.call_chain,
                    "target_should_close": target_result.should_close,
                    "dialogue_state": target_result.dialogue_state,
                    "retrieved_knowledge": target_result.retrieved_knowledge,
                    "case_mode": case_payload.get("case_mode", "branch"),
                    "expected_steps": case_payload.get("expected_steps", []),
                    "planned_max_turns": planned_max_turns,
                    "stop_decision": stop_decision,
                    "memory_state": memory_state,
                },
            )
            self.session.add(message)
            self.session.commit()
            self.session.refresh(message)
            history.append(
                {
                    "id": message.id,
                    "turn_index": turn_index,
                    "user_message": user_message,
                    "assistant_message": assistant_message,
                    "latency_ms": latency_ms,
                    "rule_score": turn_score["score"],
                    "matched_rules": turn_score["matched_rules"],
                    "missed_rules": turn_score["missed_rules"],
                    "violated_rules": turn_score["violated_rules"],
                    "detail": message.detail,
                }
            )
            if stop_decision["should_stop"]:
                logger.info(
                    "evaluation stopped run_id=%s turn=%s case_mode=%s reason=%s user_should_continue=%s target_should_close=%s",
                    run.id,
                    turn_index,
                    case_payload.get("case_mode", "branch"),
                    stop_decision["reason"],
                    user_turn.get("should_continue", True),
                    target_result.should_close,
                )
                break

        rule_result = self.rule_judge.evaluate_conversation(task_payload, case_payload, history)
        llm_result = self.evaluator_agent.evaluate(
            task_payload,
            case_payload,
            history,
            rule_result,
            retrieved_knowledge=self._conversation_retrieved_knowledge(history),
        )
        report = ReportService(self.session).create_report(
            run_id=run.id,
            task_id=task_id,
            case_id=case_id,
            rule_result=rule_result,
            llm_result=llm_result,
            messages=history,
        )
        run.status = "finished"
        run.total_score = report.total_score
        run.finished_at = datetime.utcnow()
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        return {
            "success": True,
            "run_id": run.id,
            "report_id": report.report_id,
            "total_score": report.total_score,
            "provider_requested": provider_requested,
            "provider_used": run.model_provider,
            "fallback_used": fallback_used,
            "model_provider": run.model_provider,
            "model_name": run.model_name,
            "task_type": task_type,
            "message": "evaluation finished",
            "error_code": None,
            "error_message": None,
        }

    def stream_evaluation_events(
        self,
        task_id: int,
        case_id: int,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> Iterator[str]:
        run: EvaluationRun | None = None
        provider_requested = normalize_target_provider(model_provider)
        try:
            yield self._sse_event({"event": "stage", "message": "正在初始化评测任务..."})
            task = self.session.get(EvaluationTask, task_id)
            case = self.session.get(EvaluationCase, case_id)
            if not task:
                yield self._sse_event({"event": "error", "message": "task not found"})
                return
            if not case or case.task_id != task_id:
                yield self._sse_event({"event": "error", "message": "case not found for task"})
                return

            self.target_model = TargetModelClient(model_provider, model_name)
            model_info = self.target_model.model_info()
            provider_requested = normalize_target_provider(model_provider) if model_provider else model_info["model_provider"]
            run = EvaluationRun(
                task_id=task_id,
                case_id=case_id,
                status="running",
                model_provider=model_info["model_provider"],
                model_name=model_info["model_name"],
                memory_state=reset_memory_for_new_run(task, case),
            )
            self.session.add(run)
            self.session.commit()
            self.session.refresh(run)
            run_memory = self._attach_run_context(run)

            task_payload = self._task_payload(task)
            case_payload = self._case_payload(case)
            task_type = self.target_model.infer_task_type(task_payload, case_payload)
            history: list[dict[str, Any]] = []
            fallback_used = False
            planned_max_turns = self._planned_max_turns(case_payload, task_type)
            memory_state = initialize_memory_state(task_payload, case_payload, task_type, planned_max_turns, run.id)
            memory_state["run_context"] = run_memory.get("run_context", {})
            if self._should_start_with_opening(task_payload, case_payload, task_type):
                yield self._sse_event({"event": "stage", "message": "正在召回知识库...", "turn_index": 0})
                yield self._sse_event({"event": "stage", "message": "正在调用被测模型开场...", "turn_index": 0})
                yield self._sse_event({"event": "assistant_start", "turn_index": 0, "message_phase": "opening"})
                started = time.perf_counter()
                try:
                    opening_result = self.target_model.generate_opening_reply(
                        task_payload,
                        case_payload,
                        history,
                        memory_state=memory_state,
                    )
                except TargetModelError as exc:
                    run.status = "failed"
                    run.finished_at = datetime.utcnow()
                    self.session.add(run)
                    self.session.commit()
                    yield self._sse_event(
                        {
                            "event": "error",
                            "message": exc.message,
                            "error_code": exc.code,
                            "run_id": run.id,
                            "provider_requested": provider_requested,
                            "provider_used": model_info["model_provider"],
                        }
                    )
                    return

                opening_message = opening_result.content
                fallback_used = fallback_used or bool(opening_result.fallback_used)
                yield from self._assistant_delta_events(0, opening_message, message_phase="opening")
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                opening_score = self._score_opening_turn(task_payload, case_payload, opening_message, latency_ms)
                memory_state = update_memory_state(
                    memory_state,
                    task_payload,
                    case_payload,
                    [
                        {
                            "turn_index": 0,
                            "user_message": "",
                            "assistant_message": opening_message,
                            "latency_ms": latency_ms,
                        }
                    ],
                    turn_index=0,
                    planned_max_turns=planned_max_turns,
                    turn_score=opening_score,
                    target_result=opening_result,
                )
                run_memory = update_after_model(load_memory(run), opening_message, opening_score)
                save_memory(self.session, run, run_memory)
                message = self._persist_opening_message(
                    run=run,
                    task_payload=task_payload,
                    case_payload=case_payload,
                    opening_result=opening_result,
                    opening_score=opening_score,
                    latency_ms=latency_ms,
                    planned_max_turns=planned_max_turns,
                    memory_state=memory_state,
                )
                yield self._sse_event(
                    {
                        "event": "rule_result",
                        "turn_index": 0,
                        "message_phase": "opening",
                        "matched_rules": opening_score.get("matched_rules", []),
                        "failed_rules": list(opening_score.get("missed_rules", []))
                        + list(opening_score.get("violated_rules", [])),
                        "retrieved_knowledge": opening_result.retrieved_knowledge,
                        "deduction_reason": opening_score.get("deduction_reason", ""),
                        "current_stage": opening_score.get("current_stage", "opening"),
                        "memory_state": memory_state,
                        "score": opening_score.get("score", 0),
                        "latency_ms": latency_ms,
                        "summary": "本轮评分完成",
                    }
                )
                history.append(self._history_item(message))

            for turn_index in range(1, planned_max_turns + 1):
                yield self._sse_event(
                    {
                        "event": "stage",
                        "message": "用户模拟器 Agent 正在生成用户发言...",
                        "turn_index": turn_index,
                    }
                )
                run_memory = load_memory(run)
                user_turn = self._normalize_user_turn(
                    self.user_simulator.generate_message(
                        task_payload,
                        case_payload,
                        history,
                        turn_index,
                        memory_state=run_memory,
                    ),
                    case.initial_message,
                )
                user_message = user_turn["content"]
                run_memory = update_after_user(run_memory, user_message, user_turn.get("metadata", {}))
                run_memory = save_memory(self.session, run, run_memory)
                yield self._sse_event(
                    {
                        "event": "user_message",
                        "turn_index": turn_index,
                        "content": user_message,
                    }
                )
                yield self._sse_event(
                    {
                        "event": "stage",
                        "message": "正在召回知识库...",
                        "turn_index": turn_index,
                    }
                )
                yield self._sse_event(
                    {
                        "event": "stage",
                        "message": "正在调用被测模型...",
                        "turn_index": turn_index,
                    }
                )
                yield self._sse_event({"event": "assistant_start", "turn_index": turn_index})
                started = time.perf_counter()
                try:
                    target_result = self.target_model.generate_reply(
                        task_payload,
                        case_payload,
                        user_message,
                        history,
                        memory_state=run_memory,
                    )
                except TargetModelError as exc:
                    run.status = "failed"
                    run.finished_at = datetime.utcnow()
                    self.session.add(run)
                    self.session.commit()
                    yield self._sse_event(
                        {
                            "event": "error",
                            "message": exc.message,
                            "error_code": exc.code,
                            "run_id": run.id,
                            "provider_requested": provider_requested,
                            "provider_used": model_info["model_provider"],
                        }
                    )
                    return

                assistant_message = target_result.content
                fallback_used = fallback_used or bool(target_result.fallback_used)
                yield from self._assistant_delta_events(turn_index, assistant_message)

                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                turn_history = history + [
                    {
                        "turn_index": turn_index,
                        "user_message": user_message,
                        "assistant_message": assistant_message,
                        "latency_ms": latency_ms,
                    }
                ]
                yield self._sse_event(
                    {
                        "event": "stage",
                        "message": "正在进行规则评分...",
                        "turn_index": turn_index,
                    }
                )
                turn_score = self.rule_judge.score_turn(case_payload, turn_history, latency_ms, task_payload)
                user_state = dict(user_turn.get("user_state", {}) or {})
                stop_decision = self._stop_decision(
                    task_payload=task_payload,
                    case_payload=case_payload,
                    history=turn_history,
                    turn_score=turn_score,
                    user_turn=user_turn,
                    target_should_close=target_result.should_close,
                    turn_index=turn_index,
                    planned_max_turns=planned_max_turns,
                )
                if stop_decision["should_stop"] and target_result.should_close and user_state.get("goal_progress") != "rejected":
                    user_state["goal_progress"] = "accepted"
                    user_state["current_intent"] = "接受并结束"
                if not stop_decision["should_stop"] and user_state.get("goal_progress") == "accepted":
                    user_state["goal_progress"] = "in_progress"
                    user_state["current_intent"] = "继续覆盖全流程"
                user_turn["user_state"] = user_state
                memory_state = update_memory_state(
                    memory_state,
                    task_payload,
                    case_payload,
                    turn_history,
                    turn_index=turn_index,
                    planned_max_turns=planned_max_turns,
                    turn_score=turn_score,
                    user_turn=user_turn,
                    target_result=target_result,
                    stop_decision=stop_decision,
                )
                run_memory = update_after_model(load_memory(run), assistant_message, turn_score)
                run_memory = save_memory(self.session, run, run_memory)

                message = RunMessage(
                    run_id=run.id,
                    turn_index=turn_index,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    latency_ms=latency_ms,
                    rule_score=turn_score["score"],
                    matched_rules=turn_score["matched_rules"],
                    missed_rules=turn_score["missed_rules"],
                    violated_rules=turn_score["violated_rules"],
                    detail={
                        "reason": turn_score["reason"],
                        "active_rules": turn_score.get("active_rules", {}),
                        "pending_rules": turn_score.get("pending_rules", []),
                        "untriggered_rules": turn_score.get("untriggered_rules", []),
                        "not_applicable_rules": turn_score.get("not_applicable_rules", []),
                        "visible_business_rules": turn_score.get("visible_business_rules", {}),
                        "hidden_guardrail_rules": turn_score.get("hidden_guardrail_rules", {}),
                        "rule_lifecycle": turn_score.get("rule_lifecycle", {}),
                        "late_satisfied_rules": turn_score.get("late_satisfied_rules", []),
                        "case_focus": turn_score.get("case_focus", ""),
                        "active_rule_names": turn_score.get("active_rule_names", []),
                        "current_stage": turn_score.get("current_stage", ""),
                        "deduction_reason": turn_score.get("deduction_reason", ""),
                        "active_rules_explanation": turn_score.get("active_rules_explanation", ""),
                        "user_state": user_state,
                        "user_intent": user_turn.get("intent", ""),
                        "user_metadata": user_turn.get("metadata", {}),
                        "should_continue": user_turn.get("should_continue", True),
                        "model_provider": target_result.provider,
                        "model_name": target_result.model_name,
                        "target_fallback_used": target_result.fallback_used,
                        "task_type": target_result.task_type,
                        "target_call_chain": target_result.call_chain,
                        "target_should_close": target_result.should_close,
                        "dialogue_state": target_result.dialogue_state,
                        "retrieved_knowledge": filter_relevant_knowledge(target_result.retrieved_knowledge or [], assistant_message),
                        "case_mode": case_payload.get("case_mode", "branch"),
                        "expected_steps": case_payload.get("expected_steps", []),
                        "planned_max_turns": planned_max_turns,
                        "stop_decision": stop_decision,
                        "memory_state": memory_state,
                    },
                )
                self.session.add(message)
                self.session.commit()
                self.session.refresh(message)
                lifecycle_failed = turn_score.get("failed_rules", []) or list(turn_score.get("missed_rules", [])) + list(turn_score.get("violated_rules", []))
                yield self._sse_event(
                    {
                        "event": "rule_result",
                        "turn_index": turn_index,
                        "matched_rules": turn_score.get("matched_rules", []),
                        "failed_rules": lifecycle_failed,
                        "pending_rules": turn_score.get("pending_rules", []),
                        "untriggered_rules": turn_score.get("untriggered_rules", []),
                        "not_applicable_rules": turn_score.get("not_applicable_rules", []),
                        "rule_lifecycle": turn_score.get("rule_lifecycle", {}),
                        "retrieved_knowledge": filter_relevant_knowledge(target_result.retrieved_knowledge or [], assistant_message),
                        "deduction_reason": turn_score.get("deduction_reason", ""),
                        "current_stage": turn_score.get("current_stage", ""),
                        "memory_state": memory_state,
                        "score": turn_score.get("score", 0),
                        "latency_ms": latency_ms,
                        "summary": "本轮评分完成",
                    }
                )
                history.append(
                    {
                        "id": message.id,
                        "turn_index": turn_index,
                        "user_message": user_message,
                        "assistant_message": assistant_message,
                        "latency_ms": latency_ms,
                        "rule_score": turn_score["score"],
                        "matched_rules": turn_score["matched_rules"],
                        "missed_rules": turn_score["missed_rules"],
                        "violated_rules": turn_score["violated_rules"],
                        "detail": message.detail,
                    }
                )
                if stop_decision["should_stop"]:
                    break

            yield self._sse_event({"event": "report_generating", "message": "报告生成中..."})
            yield self._sse_event({"event": "report_generating", "message": "LLM Judge 正在生成评分解释..."})
            rule_result = self.rule_judge.evaluate_conversation(task_payload, case_payload, history)
            llm_result = self.evaluator_agent.evaluate(
                task_payload,
                case_payload,
                history,
                rule_result,
                retrieved_knowledge=self._conversation_retrieved_knowledge(history),
            )
            yield self._sse_event(
                {
                    "event": "judge_result",
                    "score": llm_result.get("score", rule_result.get("score", 0)),
                    "reason": llm_result.get("overall_reason") or rule_result.get("reason", ""),
                }
            )
            yield self._sse_event({"event": "report_generating", "message": "Report Agent 正在生成报告..."})
            report = ReportService(self.session).create_report(
                run_id=run.id,
                task_id=task_id,
                case_id=case_id,
                rule_result=rule_result,
                llm_result=llm_result,
                messages=history,
            )
            run.status = "finished"
            run.total_score = report.total_score
            run.finished_at = datetime.utcnow()
            self.session.add(run)
            self.session.commit()
            self.session.refresh(run)
            yield self._sse_event({"event": "report_generating", "message": "报告已生成"})
            yield self._sse_event(
                {
                    "event": "done",
                    "run_id": run.id,
                    "report_id": report.report_id,
                    "total_score": report.total_score,
                    "provider_requested": provider_requested,
                    "provider_used": run.model_provider,
                    "fallback_used": fallback_used,
                    "model_provider": run.model_provider,
                    "model_name": run.model_name,
                    "task_type": task_type,
                }
            )
        except Exception as exc:  # noqa: BLE001 - streaming endpoints must close with an error event
            logger.exception("stream evaluation failed task_id=%s case_id=%s", task_id, case_id)
            if run:
                run.status = "failed"
                run.finished_at = datetime.utcnow()
                self.session.add(run)
                self.session.commit()
            yield self._sse_event({"event": "error", "message": str(exc) or "stream evaluation failed"})

    def _target_error_response(
        self,
        run: EvaluationRun,
        provider_requested: str,
        model_info: Dict[str, str],
        task_type: str,
        exc: TargetModelError,
        commit: bool = True,
    ) -> Dict[str, Any]:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        self.session.add(run)
        if commit:
            self.session.commit()
        return {
            "success": False,
            "run_id": run.id,
            "report_id": None,
            "total_score": 0,
            "provider_requested": provider_requested,
            "provider_used": model_info["model_provider"],
            "fallback_used": False,
            "model_provider": run.model_provider,
            "model_name": run.model_name,
            "task_type": task_type,
            "message": "evaluation failed",
            "error_code": exc.code,
            "error_message": exc.message,
        }

    def _attach_run_context(self, run: EvaluationRun) -> Dict[str, Any]:
        memory = load_memory(run)
        seed = int(run.id or 0)
        memory["run_context"] = {
            "run_seed": seed,
            "variant_id": seed % 3,
        }
        return save_memory(self.session, run, memory)

    def _should_start_with_opening(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        task_type: str,
    ) -> bool:
        opening_line = self.target_model.opening_line_for_task(task_payload, case_payload)
        if not opening_line:
            return False
        return True

    def _persist_opening_message(
        self,
        run: EvaluationRun,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        opening_result: Any,
        opening_score: Dict[str, Any],
        latency_ms: float,
        planned_max_turns: int,
        memory_state: Dict[str, Any] | None = None,
    ) -> RunMessage:
        detail = {
            "message_phase": "opening",
            "reason": opening_score["reason"],
            "active_rules": opening_score.get("active_rules", {}),
            "pending_rules": [],
            "untriggered_rules": [],
            "not_applicable_rules": [],
            "visible_business_rules": opening_score.get("visible_business_rules", {}),
            "hidden_guardrail_rules": opening_score.get("hidden_guardrail_rules", {}),
            "case_focus": "opening_line",
            "active_rule_names": opening_score.get("active_rule_names", []),
            "current_stage": opening_score.get("current_stage", "opening"),
            "deduction_reason": opening_score.get("deduction_reason", ""),
            "active_rules_explanation": "Opening Line 阶段仅展示身份确认开场和任务角色；串场仅作为后台护栏检查。",
            "user_state": {},
            "user_intent": "",
            "should_continue": True,
            "model_provider": opening_result.provider,
            "model_name": opening_result.model_name,
            "target_fallback_used": opening_result.fallback_used,
            "task_type": opening_result.task_type,
            "target_call_chain": opening_result.call_chain,
            "target_should_close": opening_result.should_close,
            "dialogue_state": opening_result.dialogue_state,
            "retrieved_knowledge": opening_result.retrieved_knowledge,
            "case_mode": case_payload.get("case_mode", "branch"),
            "expected_steps": case_payload.get("expected_steps", []),
            "planned_max_turns": planned_max_turns,
            "case_initial_message_semantics": "用户在听到开场白后的第一句回应",
            "stop_decision": {
                "should_stop": False,
                "reason": "opening_line_only",
                "case_mode": case_payload.get("case_mode", "branch"),
            },
            "memory_state": memory_state or {},
        }
        message = RunMessage(
            run_id=run.id,
            turn_index=0,
            user_message="",
            assistant_message=opening_result.content,
            latency_ms=latency_ms,
            rule_score=opening_score["score"],
            matched_rules=opening_score["matched_rules"],
            missed_rules=opening_score["missed_rules"],
            violated_rules=opening_score["violated_rules"],
            detail=detail,
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _score_opening_turn(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        assistant_message: str,
        latency_ms: float,
    ) -> Dict[str, Any]:
        task_type = self.target_model.infer_task_type(task_payload, case_payload)
        text = str(assistant_message or "")
        matched_rules: list[str] = []
        missed_rules: list[str] = []
        violated_rules: list[str] = []

        if task_type == "course_platform_outbound":
            current_stage = "identity_check"
            identity_ok = self._has_any(text, ["负责人"])
            role_ok = self._has_any(text, ["您好", "请问", "负责人"])
        elif task_type == "rider_outbound":
            current_stage = "opening"
            identity_ok = self._has_any(text, ["本人", "请问是", "是你"])
            role_ok = self._has_any(text, ["站长"])
        else:
            current_stage = "opening"
            identity_ok = bool(text.strip())
            role_ok = bool(text.strip())

        if identity_ok:
            matched_rules.append("是否完成身份确认开场")
        else:
            missed_rules.append("是否完成身份确认开场")
        if role_ok:
            matched_rules.append("是否符合任务角色")
        else:
            missed_rules.append("是否符合任务角色")
        hidden_passed_rules: list[str] = []
        hidden_violated_rules: list[str] = []
        if self.target_model.validate_reply_by_task_type(text, task_type) == text:
            hidden_passed_rules.append("是否没有串场")
        else:
            hidden_violated_rules.append("是否没有串场")

        score = max(0, 100 - len(missed_rules) * 20 - len(hidden_violated_rules) * 50)
        failed = missed_rules + violated_rules + hidden_violated_rules
        return {
            "score": score,
            "matched_rules": matched_rules,
            "missed_rules": missed_rules,
            "violated_rules": violated_rules,
            "reason": "Opening Line 开场检查完成。" if not failed else "Opening Line 开场存在缺失或串场。",
            "deduction_reason": "；".join(failed),
            "current_stage": current_stage,
            "active_rule_names": matched_rules + failed,
            "active_rules": {
                "case_focus": "opening_line",
                "active_rule_names": matched_rules + failed,
                "global_rules": [],
                "stage_rules": matched_rules + failed,
                "case_rules": [],
                "triggered_rules": [],
                "pending_rules": [],
                "untriggered_rules": [],
                "not_applicable_rules": [],
            },
            "visible_business_rules": {
                "matched": matched_rules,
                "missed": missed_rules,
                "violated": violated_rules,
            },
            "hidden_guardrail_rules": {"matched": hidden_passed_rules, "violated": hidden_violated_rules},
            "latency_ms": latency_ms,
        }

    def _history_item(self, message: RunMessage) -> Dict[str, Any]:
        return {
            "id": message.id,
            "turn_index": message.turn_index,
            "user_message": message.user_message,
            "assistant_message": message.assistant_message,
            "latency_ms": message.latency_ms,
            "rule_score": message.rule_score,
            "matched_rules": message.matched_rules,
            "missed_rules": message.missed_rules,
            "violated_rules": message.violated_rules,
            "detail": message.detail,
        }

    def _sse_event(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _assistant_delta_events(self, turn_index: int, content: str, message_phase: str = "") -> Iterator[str]:
        done_payload: Dict[str, Any] = {
            "event": "assistant_done",
            "turn_index": turn_index,
            "content": str(content or ""),
        }
        if message_phase:
            done_payload["message_phase"] = message_phase
        for delta in self._assistant_delta_chunks(content):
            payload: Dict[str, Any] = {
                "event": "assistant_delta",
                "turn_index": turn_index,
                "content": delta,
            }
            if message_phase:
                payload["message_phase"] = message_phase
            yield self._sse_event(payload)
            time.sleep(0.01)
        yield self._sse_event(done_payload)

    def _assistant_delta_chunks(self, content: str) -> Iterator[str]:
        text = str(content or "")
        for char in text:
            yield char

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

    def _case_payload(self, case: EvaluationCase) -> Dict[str, Any]:
        payload = {
            "id": case.id,
            "task_id": case.task_id,
            "name": case.name,
            "user_profile": case.user_profile,
            "initial_message": case.initial_message,
            "max_turns": case.max_turns,
            "expected_goals": case.expected_goals or [],
            "expected_steps": case.expected_steps or [],
            "required_rules": case.required_rules or [],
            "forbidden_rules": case.forbidden_rules or [],
            "trigger_conditions": case.trigger_conditions or [],
            "expected_final_state": case.expected_final_state or "",
            "user_behavior_type": case.user_behavior_type or "",
            "case_mode": case.case_mode or "",
            "difficulty": case.difficulty,
            "data_source": case.data_source or "",
        }
        payload["case_mode"] = normalize_case_mode(payload.get("case_mode"), payload)
        return payload

    def _normalize_user_turn(self, user_turn: Any, fallback_content: str) -> Dict[str, Any]:
        if isinstance(user_turn, dict):
            content = str(user_turn.get("content") or fallback_content or "")
            return {
                "content": content,
                "user_state": user_turn.get("user_state") or {},
                "intent": user_turn.get("intent") or "",
                "should_continue": bool(user_turn.get("should_continue", True)),
                "metadata": user_turn.get("metadata") or {},
            }
        return {
            "content": str(user_turn or fallback_content or ""),
            "user_state": {},
            "intent": "",
            "should_continue": True,
            "metadata": {},
        }

    def _planned_max_turns(self, case_payload: Dict[str, Any], task_type: str) -> int:
        base = int(case_payload.get("max_turns") or 4)
        case_mode = normalize_case_mode(case_payload.get("case_mode"), case_payload)
        if case_mode == "full_flow":
            step_count = len(self._expected_steps(task_type, case_payload))
            if task_type == "course_platform_outbound":
                return max(base, step_count + 8, 30)
            if task_type == "rider_outbound":
                return max(base, step_count + 8, 30)
            return max(base, step_count + 6, 20)
        return base

    def _stop_decision(
        self,
        task_payload: Dict[str, Any],
        case_payload: Dict[str, Any],
        history: list[dict[str, Any]],
        turn_score: Dict[str, Any],
        user_turn: Dict[str, Any],
        target_should_close: bool,
        turn_index: int,
        planned_max_turns: int,
    ) -> Dict[str, Any]:
        task_type = self.target_model.infer_task_type(task_payload, case_payload)
        case_mode = normalize_case_mode(case_payload.get("case_mode"), case_payload)
        user_state = user_turn.get("user_state") or {}
        user_should_continue = bool(user_turn.get("should_continue", True))
        abnormal_stop = self._abnormal_stop_requested(task_type, history, user_state)
        full_flow_status = self._full_flow_status(task_type, case_payload, history)

        if turn_index >= planned_max_turns:
            return {
                "should_stop": True,
                "reason": "reached_planned_max_turns",
                "case_mode": case_mode,
                "full_flow_status": full_flow_status,
            }

        if case_mode == "abnormal_exit":
            should_stop = abnormal_stop or target_should_close or not user_should_continue
            return {
                "should_stop": should_stop,
                "reason": "abnormal_exit_condition_met" if should_stop else "continue_until_abnormal_exit",
                "case_mode": case_mode,
                "full_flow_status": full_flow_status,
            }

        if case_mode == "full_flow":
            if abnormal_stop or user_state.get("goal_progress") == "rejected":
                return {
                    "should_stop": True,
                    "reason": "explicit_abnormal_or_rejected",
                    "case_mode": case_mode,
                    "full_flow_status": full_flow_status,
                }
            min_turns = 4 if task_type == "course_platform_outbound" else 3
            if turn_index < min_turns:
                return {
                    "should_stop": False,
                    "reason": "full_flow_min_turns_not_reached",
                    "case_mode": case_mode,
                    "full_flow_status": full_flow_status,
                }
            enough_coverage = float(full_flow_status.get("coverage_ratio", 0)) >= 0.7
            critical_steps = (
                COURSE_CRITICAL_STEPS_BEFORE_STOP
                if task_type == "course_platform_outbound"
                else RIDER_CRITICAL_STEPS_BEFORE_STOP
            )
            critical_pending = set(full_flow_status.get("pending_steps", [])) & critical_steps
            if enough_coverage and not critical_pending and (target_should_close or not user_should_continue):
                return {
                    "should_stop": True,
                    "reason": "full_flow_expected_steps_70_percent_completed",
                    "case_mode": case_mode,
                    "full_flow_status": full_flow_status,
                }
            return {
                "should_stop": False,
                "reason": "full_flow_key_steps_pending",
                "case_mode": case_mode,
                "full_flow_status": full_flow_status,
            }

        if task_type == "rider_outbound" and self._has_opening_turn(history):
            min_branch_turns = 3
        else:
            min_branch_turns = 1 if self._has_opening_turn(history) else 2
        if self._branch_followup_pending(task_type, history):
            return {
                "should_stop": False,
                "reason": "branch_followup_pending",
                "case_mode": case_mode,
                "full_flow_status": full_flow_status,
            }
        if turn_score.get("pending_rules"):
            return {
                "should_stop": False,
                "reason": "branch_rule_lifecycle_pending",
                "case_mode": case_mode,
                "full_flow_status": full_flow_status,
            }
        if turn_index >= min_branch_turns and (target_should_close or not user_should_continue):
            return {
                "should_stop": True,
                "reason": "branch_goal_closed",
                "case_mode": case_mode,
                "full_flow_status": full_flow_status,
            }
        if turn_index >= min_branch_turns and not turn_score.get("missed_rules") and not turn_score.get("violated_rules"):
            return {
                "should_stop": True,
                "reason": "branch_active_rules_completed",
                "case_mode": case_mode,
                "full_flow_status": full_flow_status,
            }
        return {
            "should_stop": False,
            "reason": "branch_goal_pending",
            "case_mode": case_mode,
            "full_flow_status": full_flow_status,
        }

    def _abnormal_stop_requested(
        self,
        task_type: str,
        history: list[dict[str, Any]],
        user_state: Dict[str, Any],
    ) -> bool:
        last_user = history[-1].get("user_message", "") if history else ""
        if user_state.get("goal_progress") == "rejected":
            return True
        if task_type == "course_platform_outbound":
            return self._has_any(last_user, ["开车", "不方便说", "先挂", "不用继续"])
        if task_type == "rider_outbound":
            return self._has_any(last_user, ["跑不了", "无法配送", "不想干", "不干", "不想跑", "不配送", "先不聊"])
        return self._has_any(last_user, ["先挂", "不用继续", "不方便"])

    def _has_opening_turn(self, history: list[dict[str, Any]]) -> bool:
        return any((item.get("detail") or {}).get("message_phase") == "opening" for item in history)

    def _branch_followup_pending(self, task_type: str, history: list[dict[str, Any]]) -> bool:
        if task_type != "course_platform_outbound" or not history:
            return False
        last_user = str(history[-1].get("user_message", "") or "")
        assistant_text = "\n".join(str(item.get("assistant_message", "") or "") for item in history)
        asked_difference = self._has_any(last_user, ["区别", "标准直播", "低延迟直播", "延迟"])
        explained_standard = self._has_any(assistant_text, ["5-10 秒", "5到10秒", "标准直播延迟", "标准延迟"])
        explained_low_latency = self._has_any(assistant_text, ["1-2 秒", "1到2秒", "低延迟约"])
        return asked_difference and explained_standard and not explained_low_latency

    def _full_flow_status(
        self,
        task_type: str,
        case_payload: Dict[str, Any],
        history: list[dict[str, Any]],
    ) -> Dict[str, Any]:
        assistant_text = "\n".join(item.get("assistant_message", "") for item in history)
        user_text = "\n".join(item.get("user_message", "") for item in history)
        expected_steps = self._expected_steps(task_type, case_payload)
        steps = {
            step: self._full_flow_step_done(task_type, step, user_text, assistant_text)
            for step in expected_steps
        }
        pending = [name for name, done in steps.items() if not done]
        reached_count = len(expected_steps) - len(pending)
        coverage_ratio = round(reached_count / max(len(expected_steps), 1), 4)
        return {
            "expected_steps": expected_steps,
            "steps": steps,
            "pending_steps": pending,
            "reached_count": reached_count,
            "coverage_ratio": coverage_ratio,
            "complete": not pending,
        }

    def _expected_steps(self, task_type: str, case_payload: Dict[str, Any]) -> list[str]:
        configured = [str(item).strip() for item in case_payload.get("expected_steps", []) or [] if str(item).strip()]
        if task_type == "rider_outbound":
            return rider_full_flow_expected_steps(configured, case_payload)
        if task_type == "course_platform_outbound":
            return course_full_flow_expected_steps(configured, case_payload)
        if configured:
            return configured
        return ["说明目的", "推进下一步", "结束确认"]

    def _full_flow_step_done(
        self,
        task_type: str,
        step: str,
        user_text: str,
        assistant_text: str,
    ) -> bool:
        combined = f"{user_text}\n{assistant_text}"
        if task_type == "course_platform_outbound":
            return course_full_flow_step_done(step, user_text, assistant_text)
        if task_type == "rider_outbound":
            checks = {
                "确认身份": self._has_any(combined, ["本人", "骑手", "站长", "请问"]),
                "告知合同生效": self._has_any(assistant_text, ["合同已生效", "合同今天已生效", "飞毛腿合同已生效"]),
                "告知今天飞毛腿合同已生效": self._has_any(assistant_text, ["合同已签署", "签署并生效", "合同已生效", "飞毛腿合同已生效"]),
                "告知合同签署并询问是否开跑": self._has_any(assistant_text, ["合同已签署", "签署并生效", "合同已生效"]) and self._has_any(assistant_text, ["开始配送", "可以开始配送", "是否可以"]),
                "说明午晚高峰上线和单量要求": self._has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and self._has_any(assistant_text, ["X 单", "X单"]) and self._has_any(assistant_text, ["Y 单", "Y单"]),
                "说明午晚高峰和单量要求": self._has_any(assistant_text, ["午晚高峰", "午餐", "晚餐", "高峰", "上线"]) and self._has_any(assistant_text, ["X 单", "X单"]) and self._has_any(assistant_text, ["Y 单", "Y单"]),
                "询问是否开始配送": self._has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送", "能跑吗"]) or self._has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
                "询问是否可以开始配送": self._has_any(assistant_text, ["开始配送", "可以开始配送", "方便开始配送", "能跑吗", "是否可以"]) or self._has_any(user_text, ["可以，我今天能跑", "马上上线", "晚上跑"]),
                "鼓励配送并安全收口": self._has_any(assistant_text, ["拒单", "取消", "超时"]) and self._has_any(assistant_text, ["安全", "注意"]),
                "说明连续配送和未完成影响": self._has_any(assistant_text, ["连续 Y 天", "连续", "Y 天", "Y天"]) and self._has_any(assistant_text, ["影响后续合同", "影响合同", "影响派单", "名额"]),
                "挽留鼓励和安全提醒": self._has_any(assistant_text, ["尽量", "少拒单", "少取消", "别超时"]) and self._has_any(assistant_text, ["安全", "注意"]),
                "根据骑手态度鼓励挽留或安抚": self._has_any(assistant_text, ["尽量", "建议", "理解", "辛苦", "名额", "高峰"]),
                "提醒注意安全": self._has_any(assistant_text, ["安全", "注意"]),
                "回答退出规则": self._has_any(assistant_text, ["前一天", "Z 点", "App", "飞毛腿报名", "次日生效"]),
                "回答奖励规则": self._has_any(assistant_text, ["连续 W 天", "W 天", "W天", "+$"]) and self._has_any(assistant_text, ["额外奖励", "激励"]),
                "说明排名与保资格规则": rider_rank_qualification_done(assistant_text),
                "处理超出职责问题": self._has_any(assistant_text, ["同事确认", "再回电", "能回答的先回答"]),
                "结束确认": self._has_any(user_text, ["明白", "按要求", "按规则", "知道了", "尽量完成", "会按要求"]) and self._has_any(assistant_text, ["好的", "注意安全", "先这样", "辛苦", "后续有问题", "再联系"]),
            }
            return bool(checks.get(step, False))
        return bool(assistant_text.strip())

    def _has_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword and keyword in text for keyword in keywords)

    def _conversation_retrieved_knowledge(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in history:
            detail = item.get("detail") or {}
            for chunk in detail.get("retrieved_knowledge") or []:
                title = str(chunk.get("title") or "")
                content = str(chunk.get("content") or "")
                key = (title, content)
                if not title or key in seen:
                    continue
                result.append(dict(chunk))
                seen.add(key)
        return result
