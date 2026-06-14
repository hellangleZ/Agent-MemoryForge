# Memory Decision Policy

The product uses a two-layer memory policy.

## Context Selection

Context selection retrieves candidate memories with deterministic limits and
optional LLM planning. Code then filters unsafe entries before prompt injection.

The context builder expands the candidate window first, removes internal test
markers and synthetic entries, then truncates to the configured context budget.
This prevents noisy test data from crowding out real memories.

## Distillation

Distillation uses an LLM only to propose STM checkpoints, semantic facts,
preferences, and graph relations. Service code then rejects:

- test markers and synthetic seed data
- internal memory keys
- assistant guesses, suggestions, and assumptions
- candidates not grounded in the user's own messages

STM checkpoints are rolling conversation summaries. Preferences, semantic facts,
and graph relations may be persisted automatically when they are grounded in the
user's own message and pass deterministic safety filters. Manual confirmation is
reserved for deployments or fields that explicitly require approval.
