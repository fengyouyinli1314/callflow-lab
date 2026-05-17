def test_list_model_providers_hides_api_key(client):
    response = client.get("/api/model-providers")
    assert response.status_code == 200
    providers = response.json()
    names = {item["name"] for item in providers}
    assert names == {"mock_fallback", "openai_compatible", "custom_endpoint"}
    assert all("api_key" not in item for item in providers)
    assert all("description" in item for item in providers)


def test_mock_fallback_provider_connection_test(client):
    response = client.post("/api/model-providers/test", json={"provider": "mock_fallback"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True
    assert result["provider"] == "mock_fallback"


def test_legacy_mock_provider_maps_to_fallback(client):
    response = client.post("/api/model-providers/test", json={"provider": "mock_strong"})
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True
    assert result["provider"] == "mock_fallback"
