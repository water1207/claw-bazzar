from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()
import os
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .routers import tasks as tasks_router
from .routers import submissions as submissions_router
from .routers import internal as internal_router
from .routers import users as users_router
from .routers import challenges as challenges_router
from .routers import trust as trust_router_module
from .routers import auth as auth_router_module
from .scheduler import create_scheduler


def run_migrations():
    import os
    from alembic.config import Config
    from alembic import command
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(base_dir, "alembic.ini"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    #run_migrations()
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Agent Market", version="0.2.0", lifespan=lifespan)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(f"[ERROR] {request.method} {request.url.path}\n{tb}", flush=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": tb},
    )


app.include_router(tasks_router.router)
app.include_router(submissions_router.router)
app.include_router(internal_router.router)
app.include_router(users_router.router)
app.include_router(challenges_router.router)
app.include_router(trust_router_module.router)
app.include_router(auth_router_module.router)
