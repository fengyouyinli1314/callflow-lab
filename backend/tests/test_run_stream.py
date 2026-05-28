import json


def _first_case(client):
    task = client.get("/api/tasks").json()[0]
    case = client.get(f"/api/cases?task_id={task['id']}").json()[0]
    return task, case


def _events(response_text):
    rows = []
    for line in response_text.splitlines():
        if not line.startswith("data: "):
            continue
        rows.append(json.loads(line.removeprefix("data: ")))
    return rows


def test_stream_evaluation_emits_events_and_persists_report(client):
    task, case = _first_case(client)
    response = client.post(
        "/api/runs/stream",
        json={"task_id": task["id"], "case_id": case["id"], "model_provider": "mock_fallback"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    event_names = [item["event"] for item in events]

    assert "stage" in event_names
    assert "user_message" in event_names
    assert "assistant_start" in event_names
    assert "assistant_delta" in event_names
    assert "assistant_done" in event_names
    assert "rule_result" in event_names
    assert "report_generating" in event_names
    assert "judge_result" in event_names
    assert event_names[-1] == "done"
    assert event_names.index("assistant_start") < event_names.index("assistant_delta")
    assert next(item for item in events if item["event"] == "assistant_delta")["content"]
    assert len(next(item for item in events if item["event"] == "assistant_delta")["content"]) == 1
    assert any(
        item["event"] == "report_generating" and "LLM Judge" in item.get("message", "")
        for item in events
    )
    rule_event = next(item for item in events if item["event"] == "rule_result")
    assert rule_event.get("memory_state", {}).get("scope") == "run"

    done = events[-1]
    assert done["run_id"] > 0
    assert done["report_id"] > 0
    assert client.get(f"/api/runs/{done['run_id']}/messages").json()
    report_response = client.get(f"/api/reports/{done['report_id']}")
    assert report_response.status_code == 200
    assert report_response.json()["memory_state"]["scope"] == "run"


def test_stream_evaluation_emits_error_event_for_missing_task(client):
    response = client.post(
        "/api/runs/stream",
        json={"task_id": 999999, "case_id": 1, "model_provider": "mock_fallback"},
    )

    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["event"] == "error"
    assert "task not found" in events[-1]["message"]
