from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException
from sqlmodel import Session

from app.models.case import EvaluationCase
from app.models.run import EvaluationRun, RunMessage
from app.models.task import EvaluationTask
from app.services.llm_judge import LLMJudge
from app.services.report_service import ReportService
from app.services.rule_judge import RuleJudge
from app.services.target_bot import TargetBot
from app.services.user_simulator import UserSimulator


class EvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.user_simulator = UserSimulator()
        self.target_bot = TargetBot()
        self.rule_judge = RuleJudge()
        self.llm_judge = LLMJudge()

    def start_evaluation(self, task_id: int, case_id: int) -> Dict[str, Any]:
        task = self.session.get(EvaluationTask, task_id)
        case = self.session.get(EvaluationCase, case_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        if not case or case.task_id != task_id:
            raise HTTPException(status_code=404, detail="case not found for task")

        run = EvaluationRun(task_id=task_id, case_id=case_id, status="running")
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        task_payload = self._task_payload(task)
        case_payload = self._case_payload(case)
        history: list[dict[str, Any]] = []

        for turn_index in range(1, case.max_turns + 1):
            user_message = (
                case.initial_message
                if turn_index == 1
                else self.user_simulator.generate_next_message(case_payload, history, turn_index)
            )
            started = time.perf_counter()
            assistant_message = self.target_bot.reply(task_payload, case_payload, user_message, history)
            latency_ms = round((time.perf_counter() - started) * 1000 + 120 + turn_index * 17, 2)

            turn_history = history + [
                {
                    "turn_index": turn_index,
                    "user_message": user_message,
                    "assistant_message": assistant_message,
                    "latency_ms": latency_ms,
                }
            ]
            turn_score = self.rule_judge.score_turn(case_payload, turn_history, latency_ms)
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
                detail={"reason": turn_score["reason"]},
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

        rule_result = self.rule_judge.evaluate_conversation(task_payload, case_payload, history)
        llm_result = self.llm_judge.evaluate(task_payload, case_payload, history, rule_result)
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
