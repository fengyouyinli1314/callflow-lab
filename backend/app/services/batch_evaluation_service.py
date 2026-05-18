from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean
from typing import Any, Dict, Iterable, List

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.batch_run import EvaluationBatchRun, EvaluationBatchRunItem
from app.models.case import EvaluationCase
from app.models.report import EvaluationReport
from app.models.task import EvaluationTask
from app.schemas.batch_run import BatchRunStartRequest
from app.services.case_registry import unique_cases
from app.services.evaluation_service import EvaluationService
from app.services.target_model_client import normalize_target_provider


METRIC_FIELDS = [
    "task_completion",
    "instruction_following",
    "call_flow_coverage",
    "constraint_compliance",
    "context_consistency",
    "response_quality",
]


class BatchEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start_batch(self, payload: BatchRunStartRequest) -> Dict[str, Any]:
        task_ids = self._unique_ints(payload.task_ids)
        case_ids = self._unique_ints(payload.case_ids)
        providers = self._unique_strings(payload.model_providers) or ["mock_fallback"]
        repeat_times = max(1, int(payload.repeat_times or 1))

        if not task_ids:
            raise HTTPException(status_code=400, detail="task_ids required")

        tasks = self._load_tasks(task_ids)
        cases_by_task = self._resolve_cases(task_ids, case_ids)
        total_runs = sum(len(cases_by_task.get(task_id, [])) for task_id in task_ids) * len(providers) * repeat_times
        if total_runs <= 0:
            raise HTTPException(status_code=400, detail="no cases found for batch evaluation")

        batch = EvaluationBatchRun(
            status="running",
            task_ids=task_ids,
            case_ids=case_ids,
            model_providers=providers,
            repeat_times=repeat_times,
            total_runs=total_runs,
        )
        self.session.add(batch)
        self.session.commit()
        self.session.refresh(batch)

        for repeat_index in range(1, repeat_times + 1):
            for provider in providers:
                for task_id in task_ids:
                    for case in cases_by_task.get(task_id, []):
                        self._run_one(batch.id, tasks[task_id], case, provider, repeat_index)

        summary = self.build_summary(batch.id, persist=True)
        return {
            "batch_id": batch.id,
            "status": summary["status"],
            "total_runs": summary["total_runs"],
            "finished_runs": summary["finished_runs"],
            "failed_runs": summary["failed_runs"],
            "average_score": summary["average_score"],
            "average_latency_ms": summary["average_latency_ms"],
            "pass_rate": summary["pass_rate"],
            "summary": summary,
        }

    def get_batch(self, batch_id: int) -> Dict[str, Any]:
        batch = self.session.get(EvaluationBatchRun, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="batch run not found")
        items = list(
            self.session.exec(
                select(EvaluationBatchRunItem)
                .where(EvaluationBatchRunItem.batch_id == batch_id)
                .order_by(EvaluationBatchRunItem.id)
            ).all()
        )
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "task_ids": batch.task_ids or [],
            "case_ids": batch.case_ids or [],
            "model_providers": self._unique_strings(batch.model_providers or []),
            "repeat_times": batch.repeat_times,
            "total_runs": batch.total_runs,
            "finished_runs": batch.finished_runs,
            "failed_runs": batch.failed_runs,
            "average_score": batch.average_score,
            "average_latency_ms": batch.average_latency_ms,
            "pass_rate": batch.pass_rate,
            "items": [self._item_dict(item) for item in items],
            "summary": batch.summary or self.build_summary(batch_id, persist=False),
            "created_at": batch.created_at,
            "finished_at": batch.finished_at,
        }

    def build_summary(self, batch_id: int, persist: bool = False) -> Dict[str, Any]:
        batch = self.session.get(EvaluationBatchRun, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="batch run not found")
        items = list(
            self.session.exec(
                select(EvaluationBatchRunItem)
                .where(EvaluationBatchRunItem.batch_id == batch_id)
                .order_by(EvaluationBatchRunItem.id)
            ).all()
        )
        reports = {
            item.report_id: self.session.get(EvaluationReport, item.report_id)
            for item in items
            if item.report_id
        }
        reports = {report_id: report for report_id, report in reports.items() if report}
        tasks = self._task_name_map(item.task_id for item in items)
        cases = self._case_name_map(item.case_id for item in items)

        finished_items = [item for item in items if item.status == "finished"]
        failed_items = [item for item in items if item.status == "failed"]
        total_runs = batch.total_runs or len(items)
        scores = [float(item.total_score or 0) for item in finished_items]
        latencies = [float(item.avg_latency_ms or 0) for item in finished_items]
        passed = [item for item in finished_items if float(item.total_score or 0) >= 60]

        failure_counter: Counter[str] = Counter()
        for report in reports.values():
            failure_counter.update(report.failed_rules or [])

        summary: Dict[str, Any] = {
            "batch_id": batch.id,
            "status": self._batch_status(total_runs, finished_items, failed_items),
            "total_runs": total_runs,
            "finished_runs": len(finished_items),
            "failed_runs": len(failed_items),
            "average_score": self._rounded_mean(scores),
            "average_latency_ms": self._rounded_mean(latencies),
            "pass_rate": round(len(passed) / total_runs * 100, 2) if total_runs else 0,
            "task_score_summary": self._task_score_summary(finished_items, tasks, total_runs),
            "metric_score_summary": self._metric_score_summary(reports.values()),
            "failed_rule_top5": [
                {"rule_name": rule, "count": count} for rule, count in failure_counter.most_common(5)
            ],
            "report_list": [
                self._report_item(item, reports.get(item.report_id), tasks, cases) for item in items
            ],
        }

        providers = self._unique_strings(batch.model_providers or [])
        if len(providers) > 1:
            model_summary = self._model_score_summary(finished_items, providers)
            summary["model_score_summary"] = model_summary
            summary["best_model_provider"] = self._best_model_provider(model_summary)

        if persist:
            batch.status = summary["status"]
            batch.finished_runs = summary["finished_runs"]
            batch.failed_runs = summary["failed_runs"]
            batch.average_score = summary["average_score"]
            batch.average_latency_ms = summary["average_latency_ms"]
            batch.pass_rate = summary["pass_rate"]
            batch.summary = summary
            batch.finished_at = datetime.utcnow()
            self.session.add(batch)
            self.session.commit()
            self.session.refresh(batch)
        return summary

    def _run_one(
        self,
        batch_id: int,
        task: EvaluationTask,
        case: EvaluationCase,
        provider: str,
        repeat_index: int,
    ) -> None:
        item = EvaluationBatchRunItem(
            batch_id=batch_id,
            task_id=task.id,
            case_id=case.id,
            model_provider=provider,
            repeat_index=repeat_index,
            status="running",
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        item_id = item.id

        try:
            result = EvaluationService(self.session).start_evaluation(task.id, case.id, provider)
            if result.get("success") is False:
                raise RuntimeError(result.get("error_message") or "evaluation failed")
            report = self.session.get(EvaluationReport, result["report_id"])
            item.status = "finished"
            item.run_id = result["run_id"]
            item.report_id = result["report_id"]
            item.total_score = float(result["total_score"])
            item.avg_latency_ms = float(report.avg_latency_ms if report else 0)
            item.finished_at = datetime.utcnow()
            self.session.add(item)
            self.session.commit()
        except Exception as exc:  # noqa: BLE001 - keep batch execution alive per item.
            self.session.rollback()
            item = self.session.get(EvaluationBatchRunItem, item_id)
            if item:
                item.status = "failed"
                item.error_message = str(exc)[:500]
                item.finished_at = datetime.utcnow()
                self.session.add(item)
                self.session.commit()

    def _resolve_cases(self, task_ids: List[int], case_ids: List[int]) -> Dict[int, List[EvaluationCase]]:
        cases_by_task: Dict[int, List[EvaluationCase]] = {task_id: [] for task_id in task_ids}
        if case_ids:
            cases = unique_cases(self.session.exec(select(EvaluationCase).where(EvaluationCase.id.in_(case_ids))).all())
            found = {case.id for case in cases}
            missing = [case_id for case_id in case_ids if case_id not in found]
            if missing:
                raise HTTPException(status_code=404, detail=f"cases not found: {missing}")
            for case in cases:
                if case.task_id not in cases_by_task:
                    raise HTTPException(status_code=400, detail="case_ids must belong to selected task_ids")
                cases_by_task[case.task_id].append(case)
            return cases_by_task

        for task_id in task_ids:
            cases_by_task[task_id] = unique_cases(
                self.session.exec(
                    select(EvaluationCase).where(EvaluationCase.task_id == task_id).order_by(EvaluationCase.id)
                ).all()
            )
        return cases_by_task

    def _load_tasks(self, task_ids: List[int]) -> Dict[int, EvaluationTask]:
        tasks = {task.id: task for task in self.session.exec(select(EvaluationTask).where(EvaluationTask.id.in_(task_ids))).all()}
        missing = [task_id for task_id in task_ids if task_id not in tasks]
        if missing:
            raise HTTPException(status_code=404, detail=f"tasks not found: {missing}")
        return tasks

    def _task_score_summary(
        self,
        items: List[EvaluationBatchRunItem],
        task_names: Dict[int, str],
        total_runs: int,
    ) -> List[Dict[str, Any]]:
        grouped: Dict[int, List[EvaluationBatchRunItem]] = defaultdict(list)
        for item in items:
            grouped[item.task_id].append(item)
        return [
            {
                "task_id": task_id,
                "task_name": task_names.get(task_id, f"任务 #{task_id}"),
                "total_runs": len(group_items),
                "average_score": self._rounded_mean(item.total_score for item in group_items),
                "pass_rate": round(
                    len([item for item in group_items if float(item.total_score or 0) >= 60])
                    / max(len(group_items), 1)
                    * 100,
                    2,
                ),
                "share": round(len(group_items) / total_runs * 100, 2) if total_runs else 0,
            }
            for task_id, group_items in grouped.items()
        ]

    def _metric_score_summary(self, reports: Iterable[EvaluationReport]) -> List[Dict[str, Any]]:
        report_list = list(reports)
        rows = []
        for field in METRIC_FIELDS:
            values = [float(getattr(report, field, 0) or 0) for report in report_list]
            rows.append({"metric": field, "average_score": self._rounded_mean(values)})
        return rows

    def _model_score_summary(
        self,
        items: List[EvaluationBatchRunItem],
        providers: List[str],
    ) -> List[Dict[str, Any]]:
        rows = []
        for provider in providers:
            group_items = [item for item in items if normalize_target_provider(item.model_provider) == provider]
            rows.append(
                {
                    "model_provider": provider,
                    "total_runs": len(group_items),
                    "average_score": self._rounded_mean(item.total_score for item in group_items),
                    "average_latency_ms": self._rounded_mean(item.avg_latency_ms for item in group_items),
                    "pass_rate": round(
                        len([item for item in group_items if float(item.total_score or 0) >= 60])
                        / max(len(group_items), 1)
                        * 100,
                        2,
                    ),
                }
            )
        return rows

    def _report_item(
        self,
        item: EvaluationBatchRunItem,
        report: EvaluationReport | None,
        task_names: Dict[int, str],
        case_names: Dict[int, str],
    ) -> Dict[str, Any]:
        return {
            "batch_item_id": item.id,
            "task_id": item.task_id,
            "task_name": task_names.get(item.task_id, f"任务 #{item.task_id}"),
            "case_id": item.case_id,
            "case_name": case_names.get(item.case_id, f"用例 #{item.case_id}"),
            "model_provider": normalize_target_provider(item.model_provider),
            "repeat_index": item.repeat_index,
            "status": item.status,
            "run_id": item.run_id,
            "report_id": item.report_id,
            "total_score": item.total_score,
            "avg_latency_ms": item.avg_latency_ms,
            "failed_rule_count": len(report.failed_rules or []) if report else 0,
            "error_message": item.error_message,
        }

    def _item_dict(self, item: EvaluationBatchRunItem) -> Dict[str, Any]:
        return {
            "id": item.id,
            "batch_id": item.batch_id,
            "task_id": item.task_id,
            "case_id": item.case_id,
            "model_provider": normalize_target_provider(item.model_provider),
            "repeat_index": item.repeat_index,
            "status": item.status,
            "run_id": item.run_id,
            "report_id": item.report_id,
            "total_score": item.total_score,
            "avg_latency_ms": item.avg_latency_ms,
            "error_message": item.error_message,
            "created_at": item.created_at,
            "finished_at": item.finished_at,
        }

    def _task_name_map(self, task_ids: Iterable[int]) -> Dict[int, str]:
        ids = self._unique_ints(task_ids)
        if not ids:
            return {}
        return {
            task.id: task.name
            for task in self.session.exec(select(EvaluationTask).where(EvaluationTask.id.in_(ids))).all()
        }

    def _case_name_map(self, case_ids: Iterable[int]) -> Dict[int, str]:
        ids = self._unique_ints(case_ids)
        if not ids:
            return {}
        return {
            case.id: case.name
            for case in self.session.exec(select(EvaluationCase).where(EvaluationCase.id.in_(ids))).all()
        }

    def _batch_status(
        self,
        total_runs: int,
        finished_items: List[EvaluationBatchRunItem],
        failed_items: List[EvaluationBatchRunItem],
    ) -> str:
        if len(finished_items) + len(failed_items) < total_runs:
            return "running"
        return "finished_with_errors" if failed_items else "finished"

    def _best_model_provider(self, rows: List[Dict[str, Any]]) -> str:
        scored = [row for row in rows if row.get("total_runs", 0) > 0]
        if not scored:
            return ""
        return max(scored, key=lambda row: float(row.get("average_score", 0))).get("model_provider", "")

    def _rounded_mean(self, values: Iterable[float]) -> float:
        numbers = [float(value or 0) for value in values]
        return round(mean(numbers), 2) if numbers else 0

    def _unique_ints(self, values: Iterable[int]) -> List[int]:
        result: List[int] = []
        seen: set[int] = set()
        for value in values or []:
            number = int(value)
            if number not in seen:
                result.append(number)
                seen.add(number)
        return result

    def _unique_strings(self, values: Iterable[str]) -> List[str]:
        result: List[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = normalize_target_provider(str(value or "").strip())
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result
