"""Tests for Oracle V2 service layer."""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, ScoringDimension, TaskType, TaskStatus, SubmissionStatus


MOCK_DIM_RESULT = json.dumps({
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "内容质量", "weight": 0.3, "scoring_guidance": "guide1"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "覆盖度", "weight": 0.3, "scoring_guidance": "guide2"},
        {"id": "data_precision", "name": "数据精度", "type": "dynamic",
         "description": "准确性", "weight": 0.4, "scoring_guidance": "guide3"},
    ],
    "rationale": "test"
})


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_generate_dimensions(db):
    from app.services.oracle import generate_dimensions

    task = Task(
        title="市场调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="至少覆盖10个产品",
    )
    db.add(task)
    db.commit()

    mock_result = type("R", (), {"stdout": MOCK_DIM_RESULT, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        dims = generate_dimensions(db, task)

    assert len(dims) == 3
    db_dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).all()
    assert len(db_dims) == 3
    assert db_dims[0].dim_id in ["substantiveness", "completeness", "data_precision"]
