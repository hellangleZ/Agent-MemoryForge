# AUTO_TASK_GRAPH (Markdown-First Orchestration Program)

This file defines the **Coordinator** instructions for dynamic multi-agent
orchestration.

The coordinator must output a single **TaskGraph JSON** object that can be
validated and executed by `agent_memory_framework.orchestrator.TaskGraphOrchestrator`.

Note: task progress tracking is handled by the executor (Task Run snapshots);
you do not need to add “tracking” tasks to the graph.

## Output contract (strict)

- Output **JSON only** (no prose).
- JSON must be a single object (no arrays).
- Do not wrap the JSON in code fences.
- Use `version: "v1"`.

## TaskGraph schema (v1)

Top-level:

- `version`: `"v1"`
- `goal`: string (what “done” means)
- `constraints`: string[] (hard rules the executor must follow)
- `tasks`: Task[]
- `final`: object
  - `task_id`: string (must match one task id; the final answer is taken from this task output)
  - `merge_tasks`: string[] (optional; ids of tasks the final step should reference)
  - `format`: `"patch"` or `"report"` (default `"report"`)

Task:

- `id`: string (unique)
- `role`: one of `["planner","research","implement","review","test","synthesize"]`
- `agent_id`: string (executor selects the agent instance by this id)
- `depends_on`: string[] (ids)
- `instructions`: string (explicit deliverable)
- `inputs`: object
  - `artifacts_from`: string[] (task ids; their artifacts will be inlined into the prompt)
- `parallel_group`: string|null (tasks with same group may run in parallel)
- `artifact`: object
  - `name`: string
  - `persist`: boolean (default true)
  - `tier`: string (default `"wm"`)
  - `scope`: string (default `"orchestration"`)
- `limits`: object
  - `max_tool_turns`: int|null
  - `timeout_s`: int|null

## Planning heuristics (how to be “smart”)

- Prefer a small DAG (<= 8 tasks) unless complexity requires more.
- Create parallelism only where tasks are truly independent:
  - Example: two `research` tasks in the same `parallel_group`.
- Always include:
  - at least one `implement` task if the request is about code changes,
  - one `review` task to catch mistakes,
  - one `test` task to define verification commands,
  - one `synthesize` task as `final.task_id`.
- Put “must not” constraints into `constraints` so the executor can enforce them.
- Ensure every task has:
  - clear instructions,
  - correct dependencies,
  - the right upstream artifacts in `inputs.artifacts_from`.
