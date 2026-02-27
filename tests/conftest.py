import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_session():
    from app.database import Base
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    from app.database import Base, get_db
    from app.main import app

    test_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db

    # Prevent lifespan from touching the real DB or starting scheduler
    with patch("app.main.create_scheduler", return_value=MagicMock()), \
         patch("app.main.run_migrations"):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client_with_db():
    """Yields (TestClient, db_session) sharing the same in-memory engine."""
    from app.database import Base, get_db
    from app.main import app

    test_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db

    with patch("app.main.create_scheduler", return_value=MagicMock()), \
         patch("app.main.run_migrations"):
        with TestClient(app) as c:
            db = TestSession()
            try:
                yield c, db
            finally:
                db.close()

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
