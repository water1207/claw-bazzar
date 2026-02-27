"""API tests for Oracle V2 features."""
import json
from unittest.mock import patch
from tests.conftest import *  # reuse conftest fixtures

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}

MOCK_DIM_GEN_STDOUT = json.dumps({
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "内容质量", "weight": 0.4, "scoring_guidance": "guide1"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "覆盖度", "weight": 0.3, "scoring_guidance": "guide2"},
        {"id": "precision", "name": "精度", "type": "dynamic",
         "description": "数据准确", "weight": 0.3, "scoring_guidance": "guide3"},
    ],
    "rationale": "test"
})


def test_create_task_with_acceptance_criteria(client):
    """Creating a task with acceptance_criteria should trigger dimension generation."""
    mock_result = type("R", (), {"stdout": MOCK_DIM_GEN_STDOUT, "returncode": 0})()
    with PAYMENT_MOCK, \
         patch("app.services.oracle.subprocess.run", return_value=mock_result):
        resp = client.post("/tasks", json={
            "title": "调研", "description": "调研竞品",
            "type": "quality_first", "deadline": "2026-12-31T00:00:00Z",
            "publisher_id": "p1", "bounty": 10.0,
            "acceptance_criteria": ["至少覆盖10个产品"],
        }, headers=PAYMENT_HEADERS)

    assert resp.status_code == 201
    data = resp.json()
    assert data["acceptance_criteria"] == ["至少覆盖10个产品"]
    assert len(data["scoring_dimensions"]) == 3
    assert data["scoring_dimensions"][0]["name"] == "实质性"
    # weight and scoring_guidance should NOT be in public response
    assert "weight" not in data["scoring_dimensions"][0]
    assert "scoring_guidance" not in data["scoring_dimensions"][0]


def test_create_task_without_acceptance_criteria(client):
    """Tasks without acceptance_criteria should return 422 (required field)."""
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "Test", "description": "Desc",
            "type": "fastest_first", "threshold": 0.8,
            "deadline": "2026-12-31T00:00:00Z",
            "publisher_id": "p1", "bounty": 5.0,
        }, headers=PAYMENT_HEADERS)

    assert resp.status_code == 422
