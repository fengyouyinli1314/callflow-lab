from __future__ import annotations

import time
import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException
from sqlmodel import Session

from app.models.case import EvaluationCase
from app.models.run import EvaluationRun, RunMessage
from app.models.task import EvaluationTask
from app.services.agents.evaluator_agent import EvaluatorAgent
from app.services.report_service import ReportService
from app.services.rule_judge import RuleJudge
from app.services.target_model_client import TargetModelClient
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
        run = EvaluationRun(
            task_id=task_id,
            case_id=case_id,
            status="running",
            model_provider=model_info["model_provider"],
            model_name=model_info["model_name"],
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

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

        for turn_index in range(1, case.max_turns + 1):
            user_turn = self._normalize_user_turn(
                self.user_simulator.generate_message(task_payload, case_payload, history, turn_index),
                case.initial_message,
            )
            user_message = user_turn["content"]
            started = time.perf_counter()
            target_result = self.target_model.generate_reply(task_payload, case_payload, user_message, history)
            assistant_message = target_result.content
            latency_ms = round((time.perf_counter() - started) * 1000 + 120 + turn_index * 17, 2)

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
            if target_result.should_close and user_state.get("goal_progress") != "rejected":
                user_state["goal_progress"] = "accepted"
                user_state["current_intent"] = "接受并结束"
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
                    "not_applicable_rules": turn_score.get("not_applicable_rules", []),
                    "current_stage": turn_score.get("current_stage", ""),
                    "active_rules_explanation": turn_score.get("active_rules_explanation", ""),
                    "user_state": user_state,
                    "user_intent": user_turn.get("intent", ""),
                    "should_continue": user_turn.get("should_continue", True),
                    "model_provider": target_result.provider,
                    "model_name": target_result.model_name,
                    "target_fallback_used": target_result.fallback_used,
                    "task_type": target_result.task_type,
                    "target_call_chain": target_result.call_chain,
                    "target_should_close": target_result.should_close,
                    "dialogue_state": target_result.dialogue_state,
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
            if not user_turn.get("should_continue", True) or target_result.should_close:
                logger.info(
                    "evaluation stopped early run_id=%s turn=%s user_should_continue=%s target_should_close=%s",
                    run.id,
                    turn_index,
                    user_turn.get("should_continue", True),
                    target_result.should_close,
                )
                break

        rule_result = self.rule_judge.evaluate_conversation(task_payload, case_payload, history)
        llm_result = self.evaluator_agent.evaluate(task_payload, case_payload, history, rule_result)
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
            "run_id": run.id,
            "report_id": report.report_id,
            "total_score": report.total_score,
            "model_provider": run.model_provider,
            "model_name": run.model_name,
            "task_type": task_type,
            "message": "evaluation finished",
        }

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
        return {
            "id": case.id,
            "task_id": case.task_id,
            "name": case.name,
            "user_profile": case.user_profile,
            "initial_message": case.initial_message,
            "max_turns": case.max_turns,
            "expected_goals": case.expected_goals or [],
            "required_rules": case.required_rules or [],
            "forbidden_rules": case.forbidden_rules or [],
            "difficulty": case.difficulty,
        }

    def _normalize_user_turn(self, user_turn: Any, fallback_content: str) -> Dict[str, Any]:
        if isinstance(user_turn, dict):
            content = str(user_turn.get("content") or fallback_content or "")
            return {
                "content": content,
                "user_state": user_turn.get("user_state") or {},
                "intent": user_turn.get("intent") or "",
                "should_continue": bool(user_turn.get("should_continue", True)),
            }
        return {
            "content": str(user_turn or fallback_content or ""),
            "user_state": {},
            "intent": "",
            "should_continue": True,
        }
