from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from sqlmodel import Session, select

from app.models.batch_run import EvaluationBatchRunItem
from app.models.case import EvaluationCase
from app.models.report import EvaluationReport
from app.models.run import EvaluationRun
from app.services.case_mode import normalize_case_mode


CaseSignature = Tuple[int, str, str]

COURSE_FULL_FLOW_CASE_NAME = "课程直播产品升级外呼用例"
COURSE_LEGACY_SPLIT_CASE_NAMES = {
    "负责人正常沟通",
    "非负责人转达",
    "商家说忙",
    "商家说在开车",
    "追问直播区别",
    "第三方系统看不到选项",
    "询问费用或优惠",
    "负责人正常沟通首轮阶段测试",
}
COURSE_LEGACY_INITIAL_MESSAGES = {
    "您好，我是机构负责人，现在可以简单说一下。",
    "喂，哪位？我现在能接电话，你说吧。",
    "标准直播和低延迟直播具体差多少秒？费用是不是也不一样？",
    "我不是负责人，我只是前台。",
    "我现在很忙，没时间听。",
    "我在开车，不方便说。",
    "我第三方系统里看不到低延迟直播选项。",
    "费用会不会更高？能给优惠券吗？",
}


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
    payload["case_mode"] = normalize_case_mode(payload.get("case_mode"), payload)

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


def sync_task_cases_to_catalog(
    session: Session,
    task_id: int,
    case_payloads: List[Dict[str, Any]],
    data_source: str,
) -> Dict[str, Any]:
    canonical_signatures: set[CaseSignature] = set()
    synced_case_ids: List[int] = []
    created_count = 0
    updated_count = 0

    for payload in case_payloads:
        case_data = {"task_id": task_id, **payload, "data_source": data_source}
        case, created = get_or_create_case(session, case_data)
        canonical_signatures.add(case_signature(task_id, case_data.get("name"), case_data.get("initial_message")))
        if created:
            created_count += 1
        else:
            for key, value in case_data.items():
                if key == "task_id":
                    continue
                setattr(case, key, value)
            updated_count += 1
        session.add(case)

    session.flush()

    all_cases = list(
        session.exec(
            select(EvaluationCase)
            .where(EvaluationCase.task_id == int(task_id))
            .order_by(EvaluationCase.id)
        ).all()
    )
    canonical_by_signature: Dict[CaseSignature, EvaluationCase] = {}
    canonical_by_name: Dict[str, EvaluationCase] = {}
    for case in all_cases:
        signature = case_signature(case.task_id, case.name, case.initial_message)
        if signature in canonical_signatures and signature not in canonical_by_signature:
            canonical_by_signature[signature] = case
            canonical_by_name.setdefault(normalize_case_text(case.name), case)
            if case.id is not None:
                synced_case_ids.append(int(case.id))

    deleted_case_ids: List[int] = []
    skipped_manual_case_ids: List[int] = []
    reassigned_references = 0

    groups: Dict[CaseSignature, List[EvaluationCase]] = defaultdict(list)
    for case in all_cases:
        groups[case_signature(case.task_id, case.name, case.initial_message)].append(case)

    for signature, group in groups.items():
        if len(group) <= 1:
            continue
        sorted_group = sorted(group, key=lambda item: item.id or 0)
        keep = sorted_group[0]
        for case in sorted_group[1:]:
            if getattr(case, "data_source", "") == "manual":
                skipped_manual_case_ids.append(int(case.id or 0))
                continue
            reassigned_references += _reassign_case_references(session, int(case.id or 0), int(keep.id or 0))
            session.delete(case)
            deleted_case_ids.append(int(case.id or 0))

    deleted_set = set(deleted_case_ids)
    refreshed_cases = [
        case
        for case in list(
            session.exec(
                select(EvaluationCase)
                .where(EvaluationCase.task_id == int(task_id))
                .order_by(EvaluationCase.id)
            ).all()
        )
        if int(case.id or 0) not in deleted_set
    ]
    fallback_keep = next(iter(canonical_by_signature.values()), None)
    for case in refreshed_cases:
        signature = case_signature(case.task_id, case.name, case.initial_message)
        if signature in canonical_signatures:
            continue
        replacement = canonical_by_name.get(normalize_case_text(case.name)) or fallback_keep
        if getattr(case, "data_source", "") == "manual" and not _is_legacy_generated_manual_case(case, replacement):
            skipped_manual_case_ids.append(int(case.id or 0))
            continue
        if replacement and replacement.id and case.id:
            reassigned_references += _reassign_case_references(session, int(case.id), int(replacement.id))
        session.delete(case)
        deleted_case_ids.append(int(case.id or 0))

    session.commit()
    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "deleted_count": len(deleted_case_ids),
        "synced_case_ids": synced_case_ids,
        "deleted_case_ids": deleted_case_ids,
        "skipped_manual_case_ids": sorted(set(skipped_manual_case_ids)),
        "reassigned_references": reassigned_references,
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


def _is_legacy_generated_manual_case(case: EvaluationCase, replacement: EvaluationCase | None) -> bool:
    if not replacement:
        return False
    case_name = normalize_case_text(case.name)
    replacement_name = normalize_case_text(replacement.name)
    legacy_case_names = {normalize_case_text(item) for item in COURSE_LEGACY_SPLIT_CASE_NAMES}
    if case_name in legacy_case_names and replacement_name == normalize_case_text(COURSE_FULL_FLOW_CASE_NAME):
        return True
    if case_name != replacement_name:
        return False
    legacy_initial_messages = {normalize_case_text(item) for item in COURSE_LEGACY_INITIAL_MESSAGES}
    return normalize_case_text(case.initial_message) in legacy_initial_messages
