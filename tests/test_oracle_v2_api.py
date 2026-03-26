"""API tests for Oracle V2 features."""

import json
from unittest.mock import patch
from tests.conftest import *  # reuse conftest fixtures

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}

MOCK_DIM_GEN_STDOUT = json.dumps(
    {
        "dimensions": [
            {
                "id": "substantiveness",
                "name": "实质性",
                "type": "fixed",
                "description": "内容质量",
                "weight": 0.4,
                "scoring_guidance": "guide1",
            },
            {
                "id": "completeness",
                "name": "完整性",
                "type": "fixed",
                "description": "覆盖度",
                "weight": 0.3,
                "scoring_guidance": "guide2",
            },
            {
                "id": "precision",
                "name": "精度",
                "type": "dynamic",
                "description": "数据准确",
                "weight": 0.3,
                "scoring_guidance": "guide3",
            },
        ],
        "rationale": "test",
    }
)


def test_create_task_with_acceptance_criteria(client_with_db):
    """Creating a task with acceptance_criteria should generate dimensions (async).

    POST response returns empty scoring_dimensions (background generation).
    Verify dimensions are correct via GET after manual insertion.
    """
    from app.models import ScoringDimension, Task

    client, db = client_with_db

    with PAYMENT_MOCK:
        resp = client.post(
            "/tasks",
            json={
                "title": "调研",
                "description": "调研竞品",
                "type": "quality_first",
                "deadline": "2026-12-31T00:00:00Z",
                "publisher_id": "p1",
                "bounty": 10.0,
                "acceptance_criteria": ["至少覆盖10个产品"],
            },
            headers=PAYMENT_HEADERS,
        )

    assert resp.status_code == 201
    data = resp.json()
    task_id = data["id"]
    assert data["acceptance_criteria"] == ["至少覆盖10个产品"]
    # POST response has empty dims (background generation)
    assert data["scoring_dimensions"] == []

    # Simulate background dimension generation
    dims_data = json.loads(MOCK_DIM_GEN_STDOUT)["dimensions"]
    for d in dims_data:
        db.add(
            ScoringDimension(
                task_id=task_id,
                dim_id=d["id"],
                name=d["name"],
                dim_type=d["type"],
                description=d["description"],
                weight=d["weight"],
                scoring_guidance=d["scoring_guidance"],
            )
        )
    db.commit()

    # Verify dimensions via GET
    resp2 = client.get(f"/tasks/{task_id}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["scoring_dimensions"]) == 3
    assert data2["scoring_dimensions"][0]["name"] == "实质性"
    # weight and scoring_guidance are included in ScoringDimensionPublic
    assert data2["scoring_dimensions"][0]["weight"] == 0.4
    assert data2["scoring_dimensions"][0]["scoring_guidance"] == "guide1"


def test_create_task_without_acceptance_criteria(client):
    """Tasks without acceptance_criteria should return 422 (required field)."""
    with PAYMENT_MOCK:
        resp = client.post(
            "/tasks",
            json={
                "title": "Test",
                "description": "Desc",
                "type": "fastest_first",
                "threshold": 0.8,
                "deadline": "2026-12-31T00:00:00Z",
                "publisher_id": "p1",
                "bounty": 5.0,
            },
            headers=PAYMENT_HEADERS,
        )

    assert resp.status_code == 422
