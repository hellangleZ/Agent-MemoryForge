# Memory Layer Slimming Guide

This project supports multiple memory types. Not every deployment needs all of them.

## Recommended default (lean but strong)

Keep these ON by default:

1. **STM summaries** (`stm` with `conversation_summary`)
   - Purpose: cheap, stable recap of recent conversational state.
   - Used directly by context assembly.

2. **Semantic facts** (`semantic_fact`)
   - Purpose: durable project/user facts, decisions, constraints, domain knowledge.
   - High ROI for recall with low token usage.

Optional, depending on your product goals:

3. **Preferences** (`ltm_preference`)
   - Purpose: explicit, structured personalization (tone, format, default choices).
   - Recommended if you want strong invariants; can be distilled asynchronously.

4. **Working memory** (`wm`)
   - Purpose: multi-step task state.
   - Keep bounded/TTL; treat as state, not permanent memory.

## Defer until proven

5. **Knowledge Graph** (`kg_relation` in Neo4j)
   - Highest maintenance cost (schema, extraction quality, query design).
   - Defer unless you need relationship reasoning/navigation.
   - Practical compromise: still distill triples, but store them as metadata / semantic facts first.
   
6. **Event history**
   - Prefer durable evidence (audit logs, traces, commits, tickets) rather than model-generated summaries.
   - Store searchable notes as `semantic_fact` with provenance metadata.

## Operational note

Async distillation is eventually consistent: the current completed turn may not immediately appear in long-term memory until the worker processes it.
