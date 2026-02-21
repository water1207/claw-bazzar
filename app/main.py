from contextlib import asynccontextmanager
from fastapi import FastAPI
from .database import engine, Base
from .scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Agent Market", lifespan=lifespan)

from .routers import tasks as tasks_router
from .routers import submissions as submissions_router
from .routers import internal as internal_router
app.include_router(tasks_router.router)
app.include_router(submissions_router.router)
app.include_router(internal_router.router)
