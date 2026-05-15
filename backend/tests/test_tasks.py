def test_seeded_tasks_visible(client):
    response = client.get("/api/tasks")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    assert any(item["name"] == "飞毛腿骑手合同生效外呼评测" for item in data)
    assert any(item["name"] == "课程直播产品升级外呼评测" for item in data)
    assert all(item["data_source"] == "excel_desensitized" for item in data)
