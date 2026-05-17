from sqlmodel import Session, select

from app.core.database import engine
from app.models.case import EvaluationCase
from app.seed.sample_data import seed_sample_data


def _case_signature(case):
    return (
        case["task_id"],
        str(case["name"]).strip(),
        str(case["initial_message"]).strip(),
    )


def test_create_case_is_idempotent_by_task_name_and_initial_message(client):
    task = client.get("/api/tasks").json()[0]
    payload = {
        "task_id": task["id"],
        "name": "幂等创建用例",
        "user_profile": "用于验证重复创建不会插入第二条。",
        "initial_message": "这是幂等创建的初始问题。",
        "max_turns": 2,
        "expected_goals": ["验证幂等"],
        "required_rules": ["必须保持幂等"],
        "forbidden_rules": ["禁止重复插入"],
        "difficulty": "简单",
    }

    first = client.post("/api/cases", json=payload).json()
    second = client.post("/api/cases", json={**payload, "user_profile": "重复提交"}).json()
    cases = client.get(f"/api/cases?task_id={task['id']}").json()
    matches = [case for case in cases if _case_signature(case) == _case_signature(first)]

    assert first["id"] == second["id"]
    assert len(matches) == 1


def test_seed_sample_data_does_not_increase_case_count_on_repeated_startup():
    with Session(engine) as session:
        before = len(session.exec(select(EvaluationCase)).all())

    seed_sample_data()
    with Session(engine) as session:
        after_once = len(session.exec(select(EvaluationCase)).all())

    seed_sample_data()
    with Session(engine) as session:
        after_twice = len(session.exec(select(EvaluationCase)).all())

    assert after_once == before
    assert after_twice == before


def test_seed_sample_data_does_not_delete_unique_manual_case(client):
    task = client.get("/api/tasks").json()[0]
    payload = {
        "task_id": task["id"],
        "name": "手动用例保留验证",
        "user_profile": "用户手动新增的验证用例。",
        "initial_message": "这是手动用例保留验证的初始问题。",
        "max_turns": 2,
        "expected_goals": ["验证保留"],
        "required_rules": ["必须保留手动用例"],
        "forbidden_rules": ["禁止启动初始化删除"],
        "difficulty": "简单",
    }

    created = client.post("/api/cases", json=payload).json()
    seed_sample_data()
    fetched = client.get(f"/api/cases/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["name"] == payload["name"]


def test_deduplicate_cases_endpoint_removes_exact_duplicate_records(client):
    task = client.get("/api/tasks").json()[0]
    payload = {
        "task_id": task["id"],
        "name": "历史重复清理测试用例",
        "user_profile": "用于验证清理接口。",
        "initial_message": "这是历史重复清理测试的初始问题。",
        "max_turns": 2,
        "expected_goals": ["验证清理"],
        "required_rules": ["必须清理重复"],
        "forbidden_rules": ["禁止误删保留项"],
        "difficulty": "简单",
        "data_source": "ai_generated",
    }

    with Session(engine) as session:
        session.add(EvaluationCase(**payload))
        session.add(EvaluationCase(**payload))
        session.commit()

    result = client.post(f"/api/cases/deduplicate?task_id={task['id']}").json()
    cases = client.get(f"/api/cases?task_id={task['id']}").json()
    matches = [case for case in cases if _case_signature(case) == (task["id"], payload["name"], payload["initial_message"])]

    assert result["deleted_count"] >= 1
    assert len(matches) == 1
