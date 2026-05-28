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

    assert after_once <= before
    assert after_twice == after_once


def test_official_tasks_keep_core_case_catalog(client):
    tasks = client.get("/api/tasks").json()
    rider_task = next(task for task in tasks if task["task_type"] == "rider_outbound")
    course_task = next(task for task in tasks if task["task_type"] == "course_platform_outbound")

    rider_cases = [
        case
        for case in client.get(f"/api/cases?task_id={rider_task['id']}").json()
        if case.get("data_source") != "manual"
    ]
    course_cases = [
        case
        for case in client.get(f"/api/cases?task_id={course_task['id']}").json()
        if case.get("data_source") != "manual"
    ]

    assert {case["name"] for case in rider_cases} == {
        "飞毛腿骑手合同生效外呼用例",
    }
    assert {case["name"] for case in course_cases} == {
        "课程直播产品升级外呼用例",
    }
    assert len({(case["name"], case["initial_message"]) for case in rider_cases}) == len(rider_cases)
    assert len({(case["name"], case["initial_message"]) for case in course_cases}) == len(course_cases)

    rider_by_name = {case["name"]: case for case in rider_cases}
    course_by_name = {case["name"]: case for case in course_cases}
    rider_case = rider_by_name["飞毛腿骑手合同生效外呼用例"]
    assert rider_case["case_mode"] == "full_flow"
    assert rider_case["initial_message"] == "是我，你说。"
    assert rider_case["max_turns"] >= 10
    assert rider_case["expected_steps"] == [
        "确认身份",
        "告知今天飞毛腿合同已生效",
        "说明午晚高峰和单量要求",
        "询问是否可以开始配送",
        "根据骑手态度鼓励挽留或安抚",
        "提醒注意安全",
        "说明排名与保资格规则",
        "结束确认",
    ]
    assert all(case["initial_message"] == "是我，你说。" for case in rider_cases)
    course_case = course_by_name["课程直播产品升级外呼用例"]
    assert course_case["case_mode"] == "full_flow"
    assert course_case["initial_message"] == "我是负责人，你说吧。"
    assert course_case["max_turns"] >= 12
    assert course_case["expected_steps"] == [
        "身份确认",
        "确认是否知情",
        "传达升级内容",
        "说明标准直播和低延迟直播区别",
        "说明价格差异",
        "询问发布方式",
        "确认前端是否可见并说明配置路径",
        "检查学员端费用/加速线路费",
        "企业微信添加",
        "结束确认",
    ]


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
