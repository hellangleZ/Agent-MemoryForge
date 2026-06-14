# Examples

This folder contains runnable demos and experimental scripts that are not
required by the library/runtime.

Notes:
- Legacy `skills/` and `procedural_skill` have been removed. Use MCP tools.
- `/v1/tools` returns `tools_by_namespace`; `/v1/tools/flat` returns flat `tools`.

## MCP config examples

This repo supports both environment-based config and a JSON file that you can
convert into `AGENT_MEMORY_MCP_SERVERS`.

See `examples/mcp_servers.example.json`.

## Demo CLI

Run the project management demo:

```
python examples/project_management_demo_real.py \
  --memory-service-url http://127.0.0.1:8001 \
  --user-id project_manager_alice \
  --agent-id agent_project_management_assistant \
  --mcp-config examples/mcp_servers.example.json

If you run the framework in a product-agnostic mode, configure a context builder:

```
export AGENT_MEMORY_CONTEXT_BUILDER='agent_memory_framework.memory_runtime.context_builder:ContextBuilder'
```
```

**Local MCP (stdio)**

Set `AGENT_MEMORY_MCP_STDIO`:

```
export AGENT_MEMORY_MCP_STDIO='{"command":"python","args":["-m","agent_memory_mcp_server"]}'
```

**Local + Third-party MCP (namespaced)**

Set `AGENT_MEMORY_MCP_SERVERS`:

```
export AGENT_MEMORY_MCP_SERVERS='[
  {"name":"local","transport":"stdio","namespace":"local","command":"python","args":["-m","agent_memory_mcp_server"]},
  {"name":"third","transport":"http","namespace":"third","url":"http://127.0.0.1:8002/mcp"}
]'
```

If you are looking for the framework entrypoints, start from `README.md`.
