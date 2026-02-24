from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from .routers import tasks as tasks_router
from .routers import submissions as submissions_router
from .routers import internal as internal_router
from .routers import users as users_router
from .routers import challenges as challenges_router
from .scheduler import create_scheduler


def run_migrations():
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Agent Market", version="0.2.0", lifespan=lifespan)
app.include_router(tasks_router.router)
app.include_router(submissions_router.router)
app.include_router(internal_router.router)
app.include_router(users_router.router)
app.include_router(challenges_router.router)
