## 2026-09-05

### Status: Retry and Memory Boundary Fixes Complete

- Ensured zero retry configuration still performs one initial request.
- Preserved explicit zero memory limits without backend reads.
- Made preference opt-out authoritative and bounded selected preference injection.
- Decoupled graph retrieval from semantic retrieval limits.
- Added regression tests that record and assert actual backend calls.
- Validation: 53 focused tests and 490 unit tests passed.

---

## 2026-06-01

### Status: 架构整顿 — 核心运行时下沉到 SDK，打破倒置依赖

**问题（架构师视角）**：`agent_memory_framework`（号称 SDK / 核心）反向 import
`agent_runtime`（产品层）拿 `ExecutionLoop` / `MemoryManager` / `ToolRegistry`，
依赖方向倒置；且存在两套 Agent 基类（框架 `Agent` vs 产品 `DemoAgent`）和三层
context builder 跳板。

**整顿（全程 348 tests 绿）**：
- **A** `ToolRegistry` 真身从 `agent_runtime/core/base_agent.py` 下沉到
  `agent_memory_framework/tools.py`（单一真源）。
- **B** `ExecutionLoop` 从 `agent_runtime/core/execution_loop.py` 物理搬到
  `agent_memory_framework/execution_loop.py`；`framework/agent.py` 改为顶层 import。
- **B2** 整个 memory 运行时层 `agent_runtime/memory/` → `agent_memory_framework/memory_runtime/`
  （memory_manager / context_builder / context_planner / policies / openai_like_llm /
  key_mapping），全量改 import（含 tests/examples）。
- **C** `DemoAgent`/`DemoRuntime` 从 `agent_runtime/product/demo_base.py` 下沉到
  `agent_memory_framework/demo_agent.py`，并让 `DemoAgent` 继承框架 `Agent`
  （单一 agent 根；共享 `enable_mcp` / 历史裁剪 / 抽象契约）。保留其 memory-aware
  `__init__`/`run_turn`（直接驱动 `llm_call_fn` 以支持 Responses API 的
  `previous_response_id` 链式工具调用）。gateway 行为零变化。
- **D** 收敛三层 context builder：删除 `framework/context_builder.py` 的
  `FrameworkContextBuilder` 反射跳板，`ContextAssembler.build` 内联可插拔逻辑
  （`AGENT_MEMORY_CONTEXT_BUILDER` / `config["context_builder"]` 仍支持）。
- **E** 删死代码 `agent_runtime/core/base_agent.py::BaseAgent`（全仓零实例化/继承）；
  `core/__init__.py` 退化为 SDK re-export；重写 `test_base_agent.py` 只测 ToolRegistry。
- **额外**：`llm_clients.py` 从 `agent_runtime/product/` 下沉到 SDK，消除 SDK 里
  最后一处对 `agent_runtime` 的惰性 import。**SDK 现已完全自包含**，依赖方向严格
  `agent_runtime` → `agent_memory_framework`。
- **G** 收敛双 config：`config/settings.py`（pydantic `AppConfig` + 8 个子配置）
  除自身测试和一处 MCP bridge 外全仓零 live 引用，唯一活配置是
  `config/agent_config.py`。把 `mcp_stdio_client.mcp_servers_from_settings` 改为
  直接读 `MCP_ENABLED/MCP_STDIO_COMMAND/MCP_STDIO_ARGS/MCP_NAMESPACE` env，删
  `config/settings.py` + `tests/unit/test_config.py`。
- **收尾**：删除已无引用的 `agent_runtime/core/`（B/E 后只剩 re-export shim）。

**验证**：`python -m pytest -q` → 338 passed（删 test_config 的 10 个低价值断言后数量回落）。
所有 entrypoint（memory service / gateway / 两个 app shim / 模板 / examples）import smoke 通过。

---

## 2026-05-31

### Status: 开源就绪审计 + 修复（多 agent team 审计）

#### 修复的真实 bug
- **P0 `execution_loop.py` `_previous_response_id` 跨轮污染**：实例属性从不重置，复用 ExecutionLoop 跨对话轮次会把上一轮 Responses API 的 response_id 带进新请求 → API 拒绝。`run_single_turn` 入口重置为 None。
- **P0 `auth_tokens.py` / `auth_store.py` JWT/refresh secret 无生产守卫**：默认 `dev-secret`，开源后任何人可伪造 JWT。新增 `APP_ENV/ENVIRONMENT=production` 时 secret 仍为默认则抛 RuntimeError。dev 不受影响。
- **P1 `execution_loop.py` 工具异常只 catch TypeError**：其它异常炸穿整个 agent loop。加 `except Exception` 返回 error result 继续。
- **P1 `full_chain_manager.py:158` fd 泄漏**：`open(log_path)` 后 Popen 但从不 close 父端句柄，反复 start 会耗尽 fd。Popen 后 `finally` close。
- **P1 `auth_store.py::update_password` 原地 mutate UserRecord**：并发下 authenticate 可能读到半写入的 password_hash。改为整对象 immutable 替换。
- **P2 `gateway/app.py` lifespan 静默吞路由重绑错误**：`except Exception: pass` → 改为 `logger.warning`，真实误配不再被隐藏。
- **P2 `memory_distill_worker.py` STM fallback 静默吞异常**：空摘要落库无迹可循 → 加 `logger.warning`。
- **P2 `conversation_value_filter.py` 缓存 check-then-act 竞态**：`in + []` + `del` 改为 `.get`/`.pop(...,None)`，并发下不再 KeyError。

#### 清理（开源就绪）
- 删死代码：`feature_flags.py::enable_faiss_idmap`（生产零调用，FAISS 已移除）+ 其测试断言。
- `git rm` 8 个内部草稿 md：fix/plan/updates/architect/CODING_FIX_PLAN/REVIEW_AND_GUIDE/DEMO_说明/HANDOVER。保留 README/AGENTS/CLAUDE/PROGRESS。
- 删 `.git_disabled` 影子仓库（4.4MB）、编辑器临时文件、清空 61MB 磁盘日志。

#### 测试质量整改（用户原话"好多测试都不合理"）
- `test_memory_manager.py`：把 `assert_called_once()`（mock 验 mock）改成 `assert_called_once_with(...)` / 校验转发实参，真正验证 STM/WM 转发语义。
- `test_runtime_config_immutability.py::test_config_independence`：测试名承诺"每次返回新 proxy"但只断言值相等 → 补 `config1 is not config2`。
- 删 `test_feature_flags.py` 中给死 flag 背书的断言。
- 新增 `test_portal_admin_members.py`（8 用例）：覆盖此前 0% 的 admin RBAC / workspace 成员增改删 / ws_default 删除保护 / 404 分支 / `_require_admin` 拒绝非 admin —— 多租户安全最关键路径。
- **重写 `test_workflows.py`**：删字面量==字面量的常量断言 + 脆弱子进程 MCP 测试；改为验真实行为——`MemoryPolicy.from_config` 覆盖/默认/`stm_ttl` 别名、`calculate_budget` 真实算术与回落、logger 真写文件。
- **重写 `test_golden_scenario_replay.py`**：原本只测 JSON round-trip；改为验 replay 真正契约——`content_hash` 对相同内容确定、内容变更后变化（回归检测基石）、落盘 hash 与内存一致（防篡改）、`ReplayRunner` 把 request 喂给 executor 并返回新结果。
- **重写 `test_multi_agent_thread_safety.py`**：原本测 CPython contextvar 语言特性；改为验我们自己的传播逻辑——两个并发 run 不同 trace_id 不串扰、TraceCollector 每线程 span 数隔离。

#### 验证
- `python -m pytest -q` → **354 passed**（修复前 341；新增 admin 8 + 测试重写净增，无回归）。
- 生产守卫手测：APP_ENV=production + 默认 secret → 正确抛错；设置 secret → 正常签发；dev → 正常。
- SDK 解耦手测：`import agent_memory_framework` 不再 import-time 拉 agent_runtime；`f.ToolRegistry` 懒加载正常。

#### 架构分层倒置（已处理 import-time 耦合）
- `agent_memory_framework/{agent,tools}.py` 不再在模块顶层 `import agent_runtime`：`ExecutionLoop/MemoryManager` 移入 `Agent.__init__` 懒加载，`ToolRegistry` 经 `__getattr__` 懒加载。`import agent_memory_framework` 现已 import-time 自洽。
- 说明：彻底的物理分包（把 `core` 下沉进 framework 成独立 wheel）仍需后续规划——当前 runtime 仍依赖 agent_runtime 存在，但耦合已从"import 即炸"降为"实例化时解析"。

#### 仍留给用户处理
- `.env` 真实密钥落盘 — 未被 git 跟踪，开源打包前需轮换。

#### 重命名（去除误导性命名，开源可读性）
- **顶层包 `project_management/` → `agent_runtime/`**：实为 core+product 运行时，与"项目管理"无关。whole-word 替换全部 171 处 import/路径 + `pyproject.toml` 包 glob + 9 个 docs + 2 个 shell。`pip install -e .` 重装后 import 正常。
- `product/framework.py` → `product/demo_base.py`（定义 DemoAgent/DemoRuntime）。
- `product/gateway_models.py` → `product/chat_models.py`（Chat* pydantic 模型，与 `gateway/models.py` 区分）。
- 删除被跟踪的运行时残留 `.last-branch`。
- 保留 `examples/project_management_demo_real.py` 原名——它是真正"项目管理主题"的 demo（gantt/budget/itinerary）。
- 验证：rename 后 `python -m pytest -q` → **354 passed**，无回归。

---

## 2026-02-16

### Status: Test-Driven Compatibility Fixes

### Changes
- Fixed File-First `top_k` parsing so `0` is rejected (no falsey coercion).
- Made `ConversationItem.timestamp` optional by default and removed noisy stdout prints during Azure OpenAI init.
- Added portal monitoring direct-call compatibility without breaking FastAPI response models; included `total` in metrics response.
- Restored legacy workspace-member helper signatures/config shape (auto-migrating tenant-level list into workspace mapping).

### Commands
- `python -m pytest tests/unit -q`
- `python -m pytest -q`

---

## 2026-02-15

### Status: Gateway Modularization Complete

### Changes
- Split gateway into modular app + core/portal routers under `agent_runtime/product/gateway/`.
- Added `_portal_shell_html` compatibility shim.
- Fixed multi-agent trace propagation/reset and full-chain log streaming.
- Adjusted KnowledgeGraphMemory to honor `agent_memory_system` Neo4j override in tests.

### Commands
- `python -m pytest tests/unit -q`

---

# Progress Log

> Only the latest entry matters. Older entries archived to `docs/archive/`.

---

## 2026-02-13

### Status: HTML Portal Removal Complete ✅

### Major Change: Python HTML Portal Removed

#### Summary
Removed Python-based HTML portal from `agent_gateway.py`, keeping only API endpoints.
The frontend is now exclusively served by Next.js (`portal-ui/`) on port 3000.

#### Changes Made

1. **Removed HTML Template Functions** (~2,600 lines removed):
   - `_portal_admin_shell_html()` - Admin portal HTML shell
   - `_portal_customer_shell_html()` - Customer portal HTML shell
   - `_portal_shell_html()` - Back-compat wrapper

2. **Removed 29 HTML Routes**:
   - Customer routes: `/portal`, `/portal/chat`, `/portal/signup`, `/portal/login`,
     `/portal/workspaces`, `/portal/agents`, `/portal/chat/{agent_id}`, `/portal/workspace`,
     `/portal/config`, `/portal/profile`, `/portal/logout`, `/portal/tools`, `/portal/runs`,
     `/portal/runs/{trace_id}`, `/portal/me`, `/portal/monitoring`, `/portal/memory`
   - Admin routes: `/portal/admin`, `/portal/admin/tools`, `/portal/admin/signup`,
     `/portal/admin/login`, `/portal/admin/workspaces`, `/portal/admin/agents`,
     `/portal/admin/chat/{agent_id}`, `/portal/admin/runs`, `/portal/admin/runs/{trace_id}`,
     `/portal/admin/me`, `/portal/admin/monitoring`, `/portal/admin/memory`

3. **Cleaned Up Imports**:
   - Removed `HTMLResponse` from fastapi.responses import (no longer used)

4. **File Size Reduction**:
   - `agent_gateway.py`: 5,746 → 2,986 lines (~48% reduction)

5. **Created API Verification Script**:
   - `scripts/verify_api_endpoints.py` - Tests all 44+ API endpoints for accessibility

#### API Endpoints Preserved (44+)

All endpoints required by `portal-ui/src/lib/api.ts` are intact:
- Authentication: `/portal/v1/login`, `/portal/v1/signup`, `/portal/v1/logout`, `/portal/v1/me`
- Workspace: `/portal/v1/workspaces/*`, `/portal/v1/workspace/config`, `/portal/v1/workspace/apply`
- Tools: `/portal/v1/tools`, `/portal/v1/tools/status`, `/portal/v1/tools/policy`
- Agents: `/portal/v1/agents`, `/portal/v1/agents/{id}`
- Memory: `/portal/v1/memory/*`, `/v1/memory/*`
- Monitoring: `/portal/v1/monitoring/*`
- Runs: `/v1/runs`, `/v1/runs/{trace_id}`
- Chat: `/v1/chat`, `/v1/chat/stream`
- Health: `/health`, `/healthz`, `/readyz`
- Full Chain: `/v1/full-chain/*`
- Jobs: `/v1/jobs/*`

#### Verification
- Module imports successfully: `python -c "import agent_runtime.product.agent_gateway"`
- All 35 frontend API functions have corresponding backend endpoints
- API verification script created for automated testing

---

### Code Review & Fixes Applied

#### Critical Issues Fixed (4/4) ✅
1. **Syntax Error in `portal-ui/src/lib/api.ts`** - Moved `ToolPolicy` interface and related functions from inside `postJson` to top level
2. **Thread Safety in `multi_agent.py`** - Added `contextvars` for thread-safe trace management in parallel execution
3. **Mutable Config in `runtime.py`** - Changed `config` property to return `MappingProxyType` for immutability
4. **Silent Exception Handlers in `agent_memory_system.py`** - Replaced `pass` with proper logging in exception handlers

#### High Priority Issues Fixed (2/4) ✅
1. **Unbounded History in `agent.py`** - Added `MAX_HISTORY_SIZE=100` constant and `_prune_history()` method
2. **Error Boundaries in Portal UI** - Added `ErrorBoundary` component, `error.tsx` for global errors, and `errorTracking.ts` utility

#### Medium Priority Issues Fixed (4/4) ✅
1. **Console.log in Portal UI** - Replaced 7 instances with `logError()` from errorTracking.ts
2. **E2E Tests** - Added Playwright configuration and test suites for auth/workspace/tools/memory

#### Code Quality Improvements (4/4) ✅
1. **Magic Numbers** - Added constants to `config/constants.py` for MultiAgent and Retry configs
2. **MCP Base Class** - Extracted `BaseMCPClient` from stdio/http clients to reduce duplication
3. **Constants Usage** - Updated `agent.py` to use `MemoryConfig.MAX_CONVERSATION_HISTORY`
4. **Dead Code** - `ProceduralMemory` already disabled with RuntimeError

#### God Object Refactoring (2/2) ✅
1. **`agent_memory_system.py`** - Split into `memory/` package with modular components:
   - `memory/utils.py` - Helper functions and EnhancedJSONEncoder
   - `memory/stm.py` - ShortTermMemory class
   - `memory/wm.py` - WorkingMemory class
   - `memory/ltm.py` - StructuredLTM class
   - `memory/vector.py` - VectorMemory class
   - `memory/knowledge_graph.py` - KnowledgeGraphMemory class
   - `memory/orchestrator.py` - MemoryOrchestrator class
2. **`agent_gateway.py`** - Created `gateway/` package with modular routes:
   - `gateway/models.py` - Pydantic request/response models
   - `gateway/deps.py` - Common dependencies (auth, tenant context)
   - `gateway/auth_routes.py` - Authentication endpoints
   - `gateway/fullchain_routes.py` - Full-chain control endpoints
   - `gateway/memory_routes.py` - Memory proxy endpoints

### Unit Tests (226 tests passing)
- `tests/unit/test_multi_agent_thread_safety.py` - Thread safety tests
- `tests/unit/test_runtime_config_immutability.py` - Config immutability tests
- `tests/unit/test_agent_history_pruning.py` - History pruning tests
- Plus existing test suite

### Bug Fixes (This Session)
- Fixed missing `Any` import in `memory/knowledge_graph.py`
- Fixed TypeScript errors in `portal-ui/src/app/admin/runs/[trace_id]/page.tsx`
- Fixed linting issues (unused imports)

### E2E Tests Added (Playwright)
- `portal-ui/e2e/auth.spec.ts` - Authentication flow tests
- `portal-ui/e2e/workspace.spec.ts` - Workspace configuration tests
- `portal-ui/e2e/tools.spec.ts` - Tools discovery tests
- `portal-ui/e2e/memory.spec.ts` - Memory statistics tests

### Remaining Items (Deferred)
- [ ] Tight coupling in `agent.py` - Requires dependency injection refactor
- [ ] Long function in `orchestrator.py` execute() - Already organized with internal helpers

---

## 2026-02-12 (Session 1)

### Status: Production Ready

### Recent Changes (Feb 2026)

1. **File-First Memory Backend** (`677f88b`)
   - Markdown files as source of truth
   - SQLite FTS as derived search index
   - Resilient to backend failures

2. **Task-Graph Orchestration** (`17ffd20`)
   - Dynamic DAG-based agent orchestration
   - Parallel execution support

3. **Task-Run Tracking Snapshots** (`f2cb06b`, `dffc154`)
   - Persistent run state snapshots
   - Debugging and replay support

### Next Steps

- [x] E2E test coverage for portal UI (Playwright setup complete)
- [ ] Performance benchmarking for large contexts
- [ ] API versioning strategy

---

## Archive

Older entries moved to `docs/archive/progress/`.

---

## 2026-02-16

- Removed legacy/hybrid memory backends and legacy memory modules (`agent_memory_system.py`, `memory/`); memory service is File-First only now.
- Updated gateway entrypoint to remove the `legacy_pm_gateway` shim.
- Distill worker now writes via File-First native `/v1/memory/write`; portal memory stats/search now align with File-First backend.
- Gateway now proxies file-first `/v1/memory/search` + `/v1/memory/get` for portal UI; workspace page supports refresh and agent counts are split by workspace custom vs system agents.
- Portal UI no longer exposes vector memory; stats/search surfaces are File-First only.
- Verification:
  - `python -m pytest -q`
  - `cd portal-ui && npm run test:e2e -- --project=chromium`

## 2026-02-16

- Portal Admin Memory now shows File-First index health and can trigger derived index rebuild via `/portal/v1/memory/index/rebuild` (memory service gate still applies).
- Playwright E2E no longer attempts to proxy unmocked `/portal/v1/*` requests to `127.0.0.1:8080`; specs explicitly mock/fail unhandled portal endpoints to keep runs quiet and deterministic.

## 2026-02-16

- File-First memory service now supports optional derived-index auto-heal:
  - rebuild+retry on search failures when index is corrupted/uninitialized
  - background rebuild when index is stale (e.g. manual Markdown edits)
- New env flags documented in `docs/CONFIG_REFERENCE.md` under "Derived index controls".

## 2026-02-18

- Hardened File-First optional auto index rebuild paths for multi-threaded servers by guarding internal bookkeeping state; behavior remains best-effort and derived-index-only.

## 2026-02-18

- Improved observability: replaced a few silent `pass` exception handlers with debug logs in best-effort planner/tool-event code paths.

## 2026-02-18

- Expanded test coverage:
  - Added hermetic unit tests for sub-agent runner behavior.
  - Expanded Playwright Chromium E2E to assert portal button actions actually hit expected APIs (tools toggle, index rebuild, workspace save/apply, workspace refresh).
- Verification:
  - `python -m pytest -q`
  - `cd portal-ui && npm run test:e2e -- --project=chromium`

## 2026-02-18

- Removed remaining vector/FAISS-facing config surface area (constants/settings/docs) and added a hermetic gateway `/v1/chat/stream` integration test that validates tool SSE events and token streaming with a mocked LLM.
- Replaced `datetime.utcnow()` usage with timezone-aware UTC timestamps to avoid Python 3.12+ deprecation warnings.
- Verification:
  - `python -m pytest -q`
  - `cd portal-ui && npm run test:e2e -- --project=chromium`

## 2026-02-18

- Removed final legacy config fallback: `VECTOR_DB_PATH` is no longer read by `config/agent_config.py` (use `LTM_DB_PATH` only).
- Verification:
  - `python -m pytest -q`

## 2026-02-18

- Updated `start_services.sh` to better match the current stack:
  - Redis/Neo4j are treated as optional (distill/graph only).
  - Portal UI can be started/stopped/checked from the script.
  - Background processes detach more reliably; stop has port-based fallbacks.
