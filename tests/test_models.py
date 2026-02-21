from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, timezone


def test_create_task_and_submission():
    from app.database import Base
    from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    task = Task(
        title="Write a poem",
        description="Write a haiku about the sea",
        type=TaskType.fastest_first,
        threshold=0.8,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(task)
    db.flush()

    sub = Submission(
        task_id=task.id,
        worker_id="agent-1",
        revision=1,
        content="Ocean waves crash here",
    )
    db.add(sub)
    db.commit()

    assert db.query(Task).count() == 1
    assert db.query(Submission).count() == 1
    assert sub.status == SubmissionStatus.pending
    assert task.status == TaskStatus.open
    assert task.winner_submission_id is None

    db.close()
