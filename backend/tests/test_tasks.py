def test_seeded_tasks_visible(client):
    response = client.get("/api/tasks")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    assert any(item["name"] == "外卖退款客服流程评测" for item in data)
