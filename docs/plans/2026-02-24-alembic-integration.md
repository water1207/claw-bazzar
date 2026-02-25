# Alembic 集成实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 引入 Alembic 管理数据库迁移，服务启动时自动执行 `upgrade head`，替换现有的 `create_all`。

**Architecture:** 在 `pyproject.toml` 添加依赖 → 初始化 Alembic 并配置 `env.py` 指向现有 engine/Base → 生成初始迁移脚本 → 修改 `lifespan` 调用迁移函数 → 更新测试 patch 目标。

**Tech Stack:** Alembic 1.13+, SQLAlchemy 2.0, SQLite (开发), FastAPI lifespan

---

### Task 1: 添加 Alembic 依赖

**Files:**
- Modify: `pyproject.toml`

**Step 1: 在 pyproject.toml 的 dependencies 中添加 alembic**

将 `alembic>=1.13.0` 加入依赖列表：

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "apscheduler>=3.10.0",
    "web3>=7.0.0",
    "fastapi-x402>=0.1.0",
    "python-dotenv>=1.0.0",
]
```

**Step 2: 安装依赖**

```bash
pip install -e ".[dev]"
```

Expected: 输出包含 `Successfully installed alembic-...`

**Step 3: 验证安装**

```bash
alembic --version
```

Expected: `alembic 1.13.x`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add alembic dependency"
```

---

### Task 2: 初始化 Alembic 并配置 env.py

**Files:**
- Create: `alembic.ini`（由 `alembic init` 自动生成）
- Create: `alembic/env.py`（生成后修改）
- Create: `alembic/script.py.mako`（自动生成，不需手动改）

**Step 1: 初始化 Alembic**

```bash
alembic init alembic
```

Expected: 生成 `alembic.ini` 和 `alembic/` 目录。

**Step 2: 修改 alembic.ini，清空 sqlalchemy.url**

找到这一行：
```ini
sqlalchemy.url = driver://user:pass@localhost/dbname
```

替换为：
```ini
sqlalchemy.url =
```

原因：实际 URL 在 `env.py` 里从环境变量读取，避免重复配置。

**Step 3: 替换 alembic/env.py 全部内容**

```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# 加载所有 Model，确保 metadata 包含所有表
from app.database import Base
import app.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    return os.environ.get("DATABASE_URL", "sqlite:///./market.db")


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 需要 batch mode 支持 ALTER
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 需要 batch mode 支持 ALTER
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 4: Commit**

```bash
git add alembic.ini alembic/env.py alembic/script.py.mako
git commit -m "feat: init alembic and configure env.py"
```

---

### Task 3: 生成初始迁移脚本

**Files:**
- Create: `alembic/versions/xxxx_init_schema.py`（自动生成）

**Step 1: 生成初始迁移**

```bash
alembic revision --autogenerate -m "init schema"
```

Expected: 输出 `Generating .../alembic/versions/xxxx_init_schema.py ... done`

**Step 2: 检查生成的迁移脚本**

打开 `alembic/versions/xxxx_init_schema.py`，确认 `upgrade()` 函数包含 `op.create_table(...)` 调用，覆盖所有表（tasks, submissions, users, challenges）。

**Step 3: 验证迁移可在临时数据库上执行（不影响 market.db）**

```bash
DATABASE_URL=sqlite:///./test_migration.db alembic upgrade head
```

Expected: 无报错，生成 `test_migration.db`

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('test_migration.db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print([t[0] for t in tables])
"
```

Expected: 输出包含 `['alembic_version', 'tasks', 'submissions', 'users', 'challenges']`（顺序可能不同）

**Step 4: 删除临时测试数据库**

```bash
rm test_migration.db
```

**Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: add initial schema migration"
```

---

### Task 4: 修改 main.py lifespan

**Files:**
- Modify: `app/main.py`

**Step 1: 修改 main.py**

将现有内容：

```python
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
from .scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()
```

替换为：

```python
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
```

注意：删除了 `from .database import engine, Base` 和 `Base.metadata.create_all`，改为调用 `run_migrations()`。

**Step 2: 启动服务，确认迁移正常执行**

```bash
uvicorn app.main:app --reload --port 8000
```

Expected: 日志中包含 Alembic 迁移相关输出，服务正常启动，无报错。

**Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: replace create_all with alembic upgrade head in lifespan"
```

---

### Task 5: 更新测试 patch 目标

**Files:**
- Modify: `tests/conftest.py`

背景：`conftest.py` 原来 patch 了 `app.database.Base.metadata.create_all`，现在 lifespan 改成调用 `app.main.run_migrations`，需要更新 patch 目标。

**Step 1: 修改 conftest.py 的 patch**

将：

```python
with patch("app.main.create_scheduler", return_value=MagicMock()), \
     patch("app.database.Base.metadata.create_all"):
```

替换为：

```python
with patch("app.main.create_scheduler", return_value=MagicMock()), \
     patch("app.main.run_migrations"):
```

**Step 2: 运行所有测试，确认全部通过**

```bash
pytest -v
```

Expected: 所有测试通过，无 FAILED。

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: update conftest patch target from create_all to run_migrations"
```

---

### Task 6: 推送并验证

**Step 1: 推送到远程**

```bash
git push
```

**Step 2: 最终检查——在全新数据库上完整验证**

```bash
DATABASE_URL=sqlite:///./fresh.db uvicorn app.main:app --port 8001
```

另开终端：

```bash
curl http://localhost:8001/tasks
```

Expected: 返回 `[]`（空列表），无 500 错误。

**Step 3: 清理**

```bash
rm fresh.db
```
