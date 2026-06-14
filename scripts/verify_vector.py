#!/usr/bin/env python3
"""Verify semantic (vector) retrieval beats FTS-only on a paraphrased query."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_memory_service.backends.file_first import FileFirstBackend
from agent_memory_service.file_first.index_sqlite import SqliteFtsIndex
from agent_memory_service.file_first.paths import workspace_root

T, W = "t_vecdemo", "ws_default"
FACT = "Our flagship product is codenamed Photon and launches in the third quarter."
QUERY = "what is the hidden name of our primary offering"  # no lexical overlap with FACT

b = FileFirstBackend(service_config={})
print("vector_enabled:", b._vector_enabled())
b.store("semantic_fact", content=FACT, user_id="u", tenant_id=T, workspace_id=W)

ws = workspace_root(tenant_id=T, workspace_id=W)
idx = SqliteFtsIndex(index_path=ws / ".index" / "index.sqlite")
fts = idx.search(query=QUERY, top_k=5)
idx.close()

hybrid = b.search_memory(tenant_id=T, workspace_id=W, payload={"query": QUERY, "top_k": 5})
hh = hybrid.get("hits", [])

print(f"\nQUERY: {QUERY!r}")
print(f"FACT : {FACT!r}")
print(f"\nFTS-only hits   : {len(fts)}")
print(f"Hybrid hits     : {len(hh)}")
for h in hh[:3]:
    print(f"  - score={h['score']:.4f} tier={h['tier']} snippet={h['snippet'][:70]!r}")

found = any("photon" in (h.get("snippet") or "").lower() for h in hh)
print("\nRESULT:", "PASS (vector recovered the fact FTS missed)" if (len(fts) == 0 and found) else
      ("PARTIAL" if found else "FAIL"))
