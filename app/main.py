from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from .database import engine, Base
from .routers import tasks as tasks_router
from .routers import submissions as submissions_router
from .routers import internal as internal_router
from .routers import users as users_router
from .routers import challenges as challenges_router
from .routers import trust as trust_router_module
from .routers import auth as auth_router_module
from .scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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
app.include_router(trust_router_module.router)
app.include_router(auth_router_module.router)
