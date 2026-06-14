# Agent-MemoryForge — User Guide (ZH/EN)

> This document is bilingual: Chinese first, then English.

License: MIT. See `LICENSE`.

Customer entrypoint: `docs/PRODUCT_OVERVIEW.md`.

---

## 中文（从浅到深）

### 0. 这是什么？适合谁？

这是一个“Agent 记忆框架 + 记忆服务”的参考实现，目标是把 Agent 的 **上下文构建、记忆存取、多租户隔离、并行 multi-agent** 做成可测试、可回滚、可观测的工程化系统。

适合：

- 想快速搭一个能跑的 Agent（单体或 multi-agent）
- 想把记忆能力从业务里抽离出来（SDK/Service 分层）
- 需要 tenant/workspace 隔离，避免跨租户泄漏

### 1. 你会得到什么（组件一览）

- **Framework（SDK）**：`agent_memory_framework/`
  - `Agent/Runtime`：单轮执行循环、工具注册
  - `ContextAssembler`：去重 + budget trace
  - `MultiAgentRuntime`：顺序/并行 fan-out（同问多答）
  - `TaskGraphOrchestrator`：动态编排（自动分解 DAG + 并行 + 合并）
  - `llm_resolver`：Azure / OpenAI-like provider wiring
  - `Memory` 抽象与 `MemoryServiceStore` adapter
- **Memory Service**：`agent_memory_service/`（推荐入口）
  - `create_app()`：FastAPI app，避免 import-time 重资源初始化
  - `MemoryOrchestrator`：File-First 路由与派生索引管理
- Optional: **Embedding Service**：`embedding_service.py`
- **Product/Gateway**：`agent_runtime/product/`（产品化 demo/网关）

### 2. 设计理念（要点）

#### 2.1 分层：SDK ≠ Service ≠ Product

- SDK：只做“模型调用/上下文/记忆抽象/协作”，不做具体存储
- Service：只做“存储/索引/隔离/性能”，可独立部署
- Product：鉴权、租户下发、UI/工作流

好处：单测轻、运维可控、线上可降级。

#### 2.2 安全第一：tenant/workspace 必须显式

系统把 `tenant_id` + `workspace_id` 当作最小隔离边界。

为了防止误用导致跨租户数据泄漏：当 `AGENT_MEMORY_ENABLE_SCOPING=0` 时，Framework adapter 会 **拒绝** read/write。

#### 2.3 并行 multi-agent 的工程前提

并行会引入线程安全风险：

- `TraceCollector` 必须线程安全（已加锁 + snapshot）
- `MemoryClient` 不能在多线程共享同一个 `requests.Session`（已改为每 agent clone client）

### 3. 安装（Install）

#### 3.1 Python 依赖

在仓库根目录：

```bash
# Minimal (SDK + client utilities only)
python -m pip install -e .

# Full chain (gateway + memory service; embedding optional)
python -m pip install -e '.[all]'
```

按需安装（可选 extras）：

- `python -m pip install -e '.[framework]'`
- `python -m pip install -e '.[memory-service]'`
- `python -m pip install -e '.[gateway]'`
- `python -m pip install -e '.[embedding]'`
- `python -m pip install -e '.[jieba]'`（更好的中文关键词提取）
- `python -m pip install -e '.[dev]'`（pytest/ruff）

建议用虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[all]'
```

#### 3.2 配置 LLM（必须二选一）

**Azure OpenAI 模式**（示例）：

```bash
export AZURE_OPENAI_ENDPOINT="https://<resource>.openai.azure.com/"
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_API_VERSION="2024-06-01"
export AZURE_OPENAI_MODEL="gpt-4o-mini"
```

**OpenAI-like 模式**（示例）：

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"   # optional
export OPENAI_BASE_URL="..."        # optional for proxies
```

### 4. Quick Start（最快跑通）

#### 4.1 启动 Embedding Service

```bash
python embedding_service.py
```

#### 4.2 启动 Memory Service（推荐）

```bash
uvicorn agent_memory_service.app:create_app --factory --host 0.0.0.0 --port 8001
```

健康检查：

```bash
curl http://localhost:8001/health
```

#### 4.3 运行一个 multi-agent（Framework 装配）

框架侧推荐用工厂：`agent_memory_framework/factory.py`。

（示例会随项目结构变化，建议以 `examples/` 或 README 里的示例为准。）

#### 4.4 运行动态编排（TaskGraph）

本仓库提供一个 markdown-first 的“编排程序”：

- 指令：`workflows/AUTO_TASK_GRAPH.md`
- 运行器：`scripts/run_task_graph.py`

示例：

```bash
python scripts/run_task_graph.py --message "为这个仓库加一个TaskGraph编排示例" --tenant-id t1 --workspace-id ws1
```

运行结果说明：

- 终端会输出一个 JSON，其中包含 `run_id`、每个 step 的 artifact citation（`path#Lline`）。
- 默认会额外写入 **Task Run 快照**（一个 Markdown checklist），用于 UI/日志展示任务进度：
  - `pending → running → done`
  - citations 在 `orchestration_trace.task_list_snapshots` 里
  - `per_role` 隔离模式下，快照写在 **base workspace**（共享），而每步产物写在各自派生 workspace

### 5. 运维与回滚（Feature Flags）

这些开关用于线上快速降级（不需要改 config.toml）：

- `AGENT_MEMORY_ENABLE_PARALLEL`（默认 `1`）
  - `0`：强制顺序执行（回滚并行风险）

- `AGENT_MEMORY_ENABLE_SCOPING`（默认 `1`）
  - `0`：Framework adapter 拒绝访问（防止跨租户泄漏）

（已移除）与 FAISS/向量相关的开关不再适用于当前 File-First runtime。

推荐新增的并行限流（避免线程爆炸）：

- `AGENT_MEMORY_PARALLEL_WORKERS`（默认：自动）
  - 未设置：默认 `min(8, agent_count)`
  - 设置为正整数：线程池上限为 `min(value, agent_count)`

### 6. 深入：实现原理速览

### 7. 推荐运行模式（三选一）

1) **纯 SDK（SDK-only）**：只跑 agents（适合单测/本地快速迭代）。
2) **SDK + Memory Service（单机）**：跑 `agent_memory_service` + agents（推荐本地/单机）。
3) **Gateway + Memory Service（产品化）**：跑 `agent_runtime/product/agent_gateway.py` 对外提供 API/UI。

#### 6.1 LLM Resolver 的错误诊断

OpenAI-like provider：优先 `responses.create(...)`，只有在明确“不支持 responses”的情况下才 fallback 到 `chat.completions.create(...)`，避免吞掉鉴权/网络/模型名错误。

#### 6.2 MemoryClient 线程安全

`requests.Session` 不保证多线程安全，因此并行 multi-agent 时每个 agent runtime 使用独立 client。

#### 6.3 File-First 检索与 scope-filter

File-First 检索通过 SQLite FTS + tenant/workspace scope 过滤完成隔离与检索。

---

## English (from basics to internals)

### 0. What is this? Who is it for?

This repository provides a production-minded reference implementation of **Agent-MemoryForge + Memory Service**, focusing on:

- reliable context assembly (dedup + budget trace)
- tenant/workspace isolation
- sequential/parallel multi-agent coordination
- safe rollbacks via feature flags

### 1. Components

- **Framework SDK**: `agent_memory_framework/`
  - `Agent/Runtime`, tools registry
  - `ContextAssembler` with budget trace
  - `MultiAgentRuntime` (sequential/parallel fan-out)
  - `TaskGraphOrchestrator` (dynamic DAG orchestration: decompose/parallel/merge)
  - `llm_resolver` (Azure/OpenAI-like)
  - `MemoryServiceStore` adapter
- **Memory Service**: `agent_memory_service/` (recommended entrypoint)
  - `create_app()` avoids import-time heavy initialization
  - `MemoryOrchestrator` routes File-First storage and manages derived indexes
- Optional: **Embedding Service**: `embedding_service.py`
- **Product/Gateway demo**: `agent_runtime/product/`

### 2. Architecture principles

- SDK handles agent execution, context construction, memory interface, and coordination.
- Service handles persistence, indexing, isolation, and performance.
- Product handles auth, tenancy routing, and UX.

### 3. Install

```bash
# Minimal (SDK + client utilities only)
python -m pip install -e .

# Full chain (gateway + memory service; embedding optional)
python -m pip install -e '.[all]'
```

Optional extras:

- `python -m pip install -e '.[framework]'`
- `python -m pip install -e '.[memory-service]'`
- `python -m pip install -e '.[gateway]'`
- `python -m pip install -e '.[embedding]'`
- `python -m pip install -e '.[jieba]'`

Configure one LLM mode:

**Azure OpenAI**:

```bash
export AZURE_OPENAI_ENDPOINT=...
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_API_VERSION=...
export AZURE_OPENAI_MODEL=...
```

**OpenAI-like**:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4o-mini
export OPENAI_BASE_URL=...  # optional
```

### 4. Quick start

Start embedding service:

```bash
python embedding_service.py  # optional (not required for file-first memory)
```

Start memory service:

```bash
uvicorn agent_memory_service.app:create_app --factory --host 0.0.0.0 --port 8001
```

Health check:

```bash
curl http://localhost:8001/health
```

### 5. Operations & rollbacks (Feature flags)

- `AGENT_MEMORY_ENABLE_PARALLEL` (default `1`)
  - `0`: force sequential multi-agent execution

- `AGENT_MEMORY_ENABLE_SCOPING` (default `1`)
  - `0`: framework adapter refuses read/write to prevent cross-tenant leakage

Recommended parallel throttle:

- `AGENT_MEMORY_PARALLEL_WORKERS` (default: auto)
  - unset: defaults to `min(8, agent_count)`
  - set to a positive int: capped at `min(value, agent_count)`

### 6. Internals (short)

### 7. Recommended run modes

1) **SDK-only**: run agents locally (great for unit tests and prototyping).
2) **SDK + Memory Service**: run `agent_memory_service` + agents (local/single-node recommended).
3) **Gateway + Memory Service**: run `agent_runtime/product/agent_gateway.py` as the product layer.

- OpenAI-like resolver prefers Responses API and only falls back on explicit “unsupported” signals for better diagnosability.
- Parallel multi-agent execution avoids sharing a single `requests.Session` by cloning `MemoryClient` per agent.
- File-First retrieval uses SQLite FTS with tenant/workspace scoping.
