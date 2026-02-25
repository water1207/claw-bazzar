"""Tests for Oracle V2 model changes."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, SubmissionStatus, ScoringDimension


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_submission_status_has_gate_passed():
    assert SubmissionStatus.gate_passed == "gate_passed"


def test_submission_status_has_gate_failed():
    assert SubmissionStatus.gate_failed == "gate_failed"


def test_task_has_acceptance_criteria_column(db):
    task = Task(
        title="Test", description="Desc", type="quality_first",
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="Must include 10 items"
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    assert task.acceptance_criteria == "Must include 10 items"


def test_task_acceptance_criteria_nullable(db):
    task = Task(
        title="Test", description="Desc", type="fastest_first",
        threshold=0.8, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=5.0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    assert task.acceptance_criteria is None


def test_scoring_dimension_create(db):
    task = Task(
        title="Test", description="Desc", type="quality_first",
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
    )
    db.add(task)
    db.commit()

    dim = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="评估提交是否有实质内容",
        weight=0.3, scoring_guidance="高分标准..."
    )
    db.add(dim)
    db.commit()
    db.refresh(dim)

    assert dim.dim_id == "substantiveness"
    assert dim.weight == 0.3
    assert dim.task_id == task.id


def test_task_dimensions_relationship(db):
    task = Task(
        title="Test", description="Desc", type="quality_first",
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="desc1", weight=0.5, scoring_guidance="guide1"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="desc2", weight=0.5, scoring_guidance="guide2"
    )
    db.add_all([dim1, dim2])
    db.commit()
    db.refresh(task)

    assert len(task.dimensions) == 2


# --- Schema tests ---

from app.schemas import TaskCreate, TaskOut, ScoringDimensionPublic


def test_task_create_accepts_acceptance_criteria():
    data = TaskCreate(
        title="Test", description="Desc", type="quality_first",
        deadline="2026-12-31T00:00:00Z", publisher_id="p1", bounty=10.0,
        acceptance_criteria="Must include 10 items"
    )
    assert data.acceptance_criteria == "Must include 10 items"


def test_task_create_acceptance_criteria_optional():
    data = TaskCreate(
        title="Test", description="Desc", type="fastest_first",
        threshold=0.8, deadline="2026-12-31T00:00:00Z",
        publisher_id="p1", bounty=5.0,
    )
    assert data.acceptance_criteria is None


def test_scoring_dimension_public_schema():
    dim = ScoringDimensionPublic(name="实质性", description="评估内容质量")
    assert dim.name == "实质性"
    assert dim.description == "评估内容质量"
