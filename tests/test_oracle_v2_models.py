"""Tests for Oracle V2 model changes."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, SubmissionStatus


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
