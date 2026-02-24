# Alembic 数据库迁移引入设计

日期：2026-02-24

## 背景

项目目前使用 `Base.metadata.create_all()` 管理数据库结构，该方式只能建表、无法感知列变更，导致 Model 更新后旧数据库不会同步，引发运行时异常（如 `challenger_wallet` 列缺失导致调度器静默崩溃）。

## 目标

- 引入 Alembic，让 Model 变更可版本控制、可重现
- 服务启动时自动执行 `alembic upgrade head`，同事拉代码重启即完成迁移
- 不改变现有数据库连接方式（SQLite，`DATABASE_URL` 环境变量）

## 方案选择

选择**方案 A**：在 FastAPI `lifespan` 里自动运行迁移。

理由：零额外步骤，与现有 lifespan 结构天然契合，迁移失败会阻止服务启动（强迫修复，避免带病运行）。

## 设计

### 文件变动

```
pyproject.toml              ← 添加 alembic 依赖
alembic.ini                 ← 新建，Alembic 主配置（sqlalchemy.url 留空，由 env.py 注入）
alembic/
  env.py                    ← 新建，引用 app.database.engine 和 Base.metadata
  script.py.mako            ← 自动生成，迁移脚本模板
  versions/
    xxxx_init_schema.py     ← 新建，初始迁移（当前完整 schema）
app/main.py                 ← 删除 create_all，lifespan 改为调用 run_migrations()
```

### 启动流程

```
uvicorn 启动
  → lifespan 触发
  → run_migrations()：通过 Alembic Python API 执行 upgrade head
  → scheduler 启动
  → 服务就绪
```

### 迁移执行方式

使用 Alembic Python API（非 subprocess），保证与应用共享同一数据库连接配置：

```python
from alembic.config import Config
from alembic import command

def run_migrations():
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "revision")
```

### 后续工作流

每次修改 `app/models.py`：

```bash
alembic revision --autogenerate -m "描述变更"  # 生成迁移脚本
alembic upgrade head                            # 本地验证
git add alembic/versions/xxxx.py app/models.py
git commit
```

同事拉代码后重启服务，`upgrade head` 自动执行，无需手动操作。

## 约束

- `alembic.ini` 中 `sqlalchemy.url` 设为空，实际 URL 在 `env.py` 里从 `DATABASE_URL` 环境变量读取，与 `app/database.py` 保持一致
- 测试用 in-memory SQLite 不受影响（`conftest.py` 直接调用 `create_all`，与 Alembic 隔离）
