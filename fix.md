# Bug Fixes

## 2026-09-05

- Fixed zero retry configuration skipping the initial LLM or HTTP request.
- Fixed explicit zero STM, semantic, and graph limits being replaced by nonzero defaults.
- Fixed disabled preference policies being re-enabled by context planner output.
- Fixed graph retrieval being disabled or over-expanded by the semantic retrieval limit.
- Fixed selected preference injection bypassing the established filtering and value-length bounds.