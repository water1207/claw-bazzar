# Supabase PostgreSQL Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将后端数据库从本地 SQLite 迁移到 Supabase PostgreSQL，在新 git 分支上完成所有代码改动并运行 Alembic 迁移。

**Architecture:** 通过环境变量 `DATABASE_URL` 区分 SQLite（本地开发）和 PostgreSQL（Supabase 生产），代码层做最小化兼容性修改，Alembic 迁移脚本无需改动（表结构已全部描述在现有 migrations 中）。

**Tech Stack:** SQLAlchemy 2.x, Alembic, psycopg2-binary, Supabase PostgreSQL (Base Sepolia project)

---

## 前置条件（执行前确认）

- [ ] 已在 [supabase.com](https://supabase.com) 创建项目
- [ ] 已获取 Connection string (Settings → Database → Connection string → URI)，格式：
  ```
  postgresql://postgres:[密码]@db.[project-ref].supabase.co:5432/postgres
  ```
- [ ] 当前在 `main` 分支，工作区干净

---

### Task 1: 创建 git 分支

**Files:** 无

**Step 1: 创建并切换到新分支**

```bash
git checkout -b feat/supabase-migration
```

Expected: `Switched to a new branch 'feat/supabase-migration'`

**Step 2: 验证**

```bash
git branch --show-current
```

Expected: `feat/supabase-migration`

---

### Task 2: 添加 psycopg2-binary 依赖

**Files:**
- Modify: `pyproject.toml`

**Step 1: 在 `pyproject.toml` 的 `dependencies` 列表末尾添加**

在 `"python-dotenv>=1.0.0",` 之后加一行：

```toml
    "psycopg2-binary>=2.9.0",
```

完整 dependencies 块变为：
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
    "psycopg2-binary>=2.9.0",
]
```

**Step 2: 安装新依赖**

```bash
pip install -e ".[dev]"
```

Expected: `Successfully installed psycopg2-binary-...`

**Step 3: 验证 psycopg2 可导入**

```bash
python -c "import psycopg2; print(psycopg2.__version__)"
```

Expected: 打印版本号，无报错

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add psycopg2-binary for PostgreSQL support"
```

---

### Task 3: 修改 database.py 兼容 PostgreSQL

**Files:**
- Modify: `app/database.py`

**Step 1: 将当前内容替换为以下代码**

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./market.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**Step 2: 验证语法无误**

```bash
python -c "from app.database import engine, SessionLocal, Base; print('OK')"
```

Expected: `OK`（使用默认 SQLite，不需要 Supabase URL）

**Step 3: Commit**

```bash
git add app/database.py
git commit -m "feat: support PostgreSQL via DATABASE_URL env var"
```

---

### Task 4: 修改 alembic/env.py 移除 SQLite 专属配置

**Files:**
- Modify: `alembic/env.py`

**Step 1: 在 `run_migrations_offline` 函数中，将 `render_as_batch=True` 改为条件判断**

找到两处 `context.configure(...)` 调用，将 `render_as_batch=True` 改为：

```python
render_as_batch=get_url().startswith("sqlite"),
```

**完整修改后的 `alembic/env.py`：**

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
        render_as_batch=url.startswith("sqlite"),
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
        url = get_url()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Step 2: 验证语法无误（用本地 SQLite）**

```bash
alembic current
```

Expected: 打印当前 revision，无错误

**Step 3: Commit**

```bash
git add alembic/env.py
git commit -m "feat: make render_as_batch conditional for PostgreSQL compatibility"
```

---

### Task 5: 配置 Supabase DATABASE_URL

**Files:**
- Modify: `.env`（本地，不 commit）

**Step 1: 在 `.env` 文件末尾追加 DATABASE_URL**

```bash
echo 'DATABASE_URL=postgresql://postgres:[密码]@db.[project-ref].supabase.co:5432/postgres' >> .env
```

> ⚠️ 将 `[密码]` 和 `[project-ref]` 替换为实际值

**Step 2: 验证环境变量加载**

```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
url = os.environ.get('DATABASE_URL', '')
print('URL starts with:', url[:30] + '...' if len(url) > 30 else url)
"
```

Expected: `URL starts with: postgresql://postgres:...`

---

### Task 6: 运行 Alembic 迁移到 Supabase

**Files:** 无代码改动

**Step 1: 加载环境变量并运行迁移**

```bash
export $(grep -v '^#' .env | xargs) && alembic upgrade head
```

Expected: 打印所有 migration steps，最后无错误。示例输出：
```
INFO  [alembic.runtime.migration] Context impl PostgreSQLImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> eec967366a22, init_schema
INFO  [alembic.runtime.migration] Running upgrade eec967366a22 -> 31bcc748a94b, add_oracle_v2_fields
...
INFO  [alembic.runtime.migration] Running upgrade xxxx -> b34fa3d8a582, add arbiter hawkish trust event types
```

**Step 2: 验证迁移状态**

```bash
export $(grep -v '^#' .env | xargs) && alembic current
```

Expected: `b34fa3d8a582 (head)`

**Step 3: 验证可连接并查询**

```bash
export $(grep -v '^#' .env | xargs) && python -c "
from dotenv import load_dotenv
load_dotenv()
from app.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text('SELECT tablename FROM pg_tables WHERE schemaname=\'public\' ORDER BY tablename'))
    tables = [row[0] for row in result]
    print('Tables created:', tables)
"
```

Expected: 打印所有表名，包含 `tasks`, `users`, `submissions`, `challenges` 等。

---

### Task 7: 最终验证 & 推送分支

**Step 1: 确认本地 SQLite 测试仍然可以通过（不设 DATABASE_URL）**

```bash
unset DATABASE_URL && pytest -v --tb=short 2>&1 | tail -20
```

Expected: 所有测试通过（使用本地 SQLite）

**Step 2: 推送分支**

```bash
git push -u origin feat/supabase-migration
```

**Step 3: 查看分支最终 commit log**

```bash
git log --oneline feat/supabase-migration
```

Expected 类似：
```
xxxx feat: make render_as_batch conditional for PostgreSQL compatibility
xxxx feat: support PostgreSQL via DATABASE_URL env var
xxxx feat: add psycopg2-binary for PostgreSQL support
```

---

## 故障排查

| 错误 | 原因 | 修复 |
|------|------|------|
| `psycopg2.OperationalError: could not connect` | URL 格式错误或密码有特殊字符 | URL encode 密码：`@` → `%40` |
| `SSL connection has been closed unexpectedly` | Supabase 要求 SSL | 在 URL 末尾加 `?sslmode=require` |
| `alembic.util.exc.CommandError: Can't locate revision` | 本地 SQLite 有旧版本记录 | 只对新 Supabase DB 运行，不影响本地 |
| `relation "alembic_version" does not exist` | 正常，第一次迁移自动创建 | 无需处理 |
