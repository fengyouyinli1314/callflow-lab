from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from sqlmodel import Session, select

from app.models.batch_run import EvaluationBatchRunItem
from app.models.case import EvaluationCase
from app.models.report import EvaluationReport
from app.models.run import EvaluationRun


CaseSignature = Tuple[int, str, str]


def normalize_case_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def case_signature(task_id: int, name: Any, initial_message: Any) -> CaseSignature:
    return (
        int(task_id),
        normalize_case_text(name),
        normalize_case_text(initial_message),
    )


def existing_case(
    session: Session,
    task_id: int,
    name: str,
    initial_message: str,
    exclude_case_id: int | None = None,
) -> EvaluationCase | None:
    signature = case_signature(task_id, name, initial_message)
    candidates = list(
        session.exec(
            select(EvaluationCase)
            .where(EvaluationCase.task_id == int(task_id))
            .order_by(EvaluationCase.id)
        ).all()
    )
    for case in candidates:
        if exclude_case_id is not None and case.id == exclude_case_id:
            continue
        if case_signature(case.task_id, case.name, case.initial_message) == signature:
            return case
    return None


def case_exists(session: Session, task_id: int, name: str, initial_message: str) -> bool:
    return existing_case(session, task_id, name, initial_message) is not None


def get_or_create_case(
    session: Session,
    case_data: Dict[str, Any],
) -> tuple[EvaluationCase, bool]:
    payload = dict(case_data)
    task_id = int(payload.pop("task_id"))
    name = normalize_case_text(payload.get("name"))
    initial_message = normalize_case_text(payload.get("initial_message"))
    payload["name"] = name
    payload["initial_message"] = initial_message

    found = existing_case(session, task_id, name, initial_message)
    if found:
        return found, False

    case = EvaluationCase(task_id=task_id, **payload)
    session.add(case)
    return case, True


def unique_cases(cases: Iterable[EvaluationCase]) -> List[EvaluationCase]:
    result: List[EvaluationCase] = []
    seen: set[CaseSignature] = set()
    for case in sorted(list(cases), key=lambda item: item.id or 0):
        signature = case_signature(case.task_id, case.name, case.initial_message)
        if signature in seen:
            continue
        seen.add(signature)
        result.append(case)
    return result


def deduplicate_cases(
    session: Session,
    task_id: int | None = None,
) -> Dict[str, Any]:
    statement = select(EvaluationCase).order_by(EvaluationCase.task_id, EvaluationCase.id)
    if task_id is not None:
        statement = statement.where(EvaluationCase.task_id == int(task_id))
    cases = list(session.exec(statement).all())

    groups: Dict[CaseSignature, List[EvaluationCase]] = defaultdict(list)
    for case in cases:
        groups[case_signature(case.task_id, case.name, case.initial_message)].append(case)

    deleted_case_ids: List[int] = []
    kept_case_ids: List[int] = []
    skipped_manual_case_ids: List[int] = []
    duplicate_groups: List[Dict[str, Any]] = []
    reassigned_references = 0

    for signature, group in groups.items():
        if len(group) <= 1:
            continue

        sorted_group = sorted(group, key=lambda item: item.id or 0)
        manual_cases = [case for case in sorted_group if getattr(case, "data_source", "") == "manual"]
        keep = manual_cases[0] if manual_cases else sorted_group[0]
        kept_case_ids.append(int(keep.id or 0))
        group_deleted_ids: List[int] = []
        group_skipped_manual_ids: List[int] = []

        for case in sorted_group:
            if case.id == keep.id:
                continue
            if getattr(case, "data_source", "") == "manual":
                group_skipped_manual_ids.append(int(case.id or 0))
                skipped_manual_case_ids.append(int(case.id or 0))
                continue
            reassigned_references += _reassign_case_references(session, int(case.id or 0), int(keep.id or 0))
            session.delete(case)
            group_deleted_ids.append(int(case.id or 0))
            deleted_case_ids.append(int(case.id or 0))

        duplicate_groups.append(
            {
                "task_id": signature[0],
                "name": signature[1],
                "initial_message": signature[2],
                "kept_case_id": keep.id,
                "deleted_case_ids": group_deleted_ids,
                "skipped_manual_case_ids": group_skipped_manual_ids,
            }
        )

    session.commit()
    return {
        "duplicate_group_count": len(duplicate_groups),
        "deleted_count": len(deleted_case_ids),
        "kept_case_ids": kept_case_ids,
        "deleted_case_ids": deleted_case_ids,
        "skipped_manual_case_ids": skipped_manual_case_ids,
        "reassigned_references": reassigned_references,
        "groups": duplicate_groups,
    }


def _reassign_case_references(session: Session, old_case_id: int, new_case_id: int) -> int:
    changed = 0
    for model in (EvaluationRun, EvaluationReport, EvaluationBatchRunItem):
        rows = list(session.exec(select(model).where(model.case_id == old_case_id)).all())
        for row in rows:
            row.case_id = new_case_id
            session.add(row)
            changed += 1
    return changed
