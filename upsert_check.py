#!/usr/bin/env python3
"""Focused verification of preference UPSERT + KEY NORMALIZATION (memory service :8001)."""
import json, os, urllib.request, urllib.error, uuid
from pathlib import Path

MEM = "http://localhost:8001"
TEN = "t_upsert_" + uuid.uuid4().hex[:6]
WS = "ws_default"
USER = "upsert_user"
results = []


def rec(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def call(ep, memory_type, params):
    params = {**params, "tenant_id": TEN, "workspace_id": WS}
    body = json.dumps({"memory_type": memory_type, "params": params}).encode()
    req = urllib.request.Request(MEM + "/" + ep, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"_err": e.read().decode()[:200]}


# 1) store same concept twice with messy + normalized key
call("store", "ltm_preference", {"user_id": USER, "key": "Coding Language", "value": "Go"})
call("store", "ltm_preference", {"user_id": USER, "key": "coding_language", "value": "Rust"})

# 2) retrieve latest (upsert -> Rust, not Go)
st, r = call("retrieve", "ltm_preference", {"user_id": USER, "key": "coding_language"})
rec("upsert keeps latest value (Go->Rust)", r.get("data") == "Rust", f"value={r.get('data')!r}")

# 3) retrieve with a messy variant key -> normalized match
st, r = call("retrieve", "ltm_preference", {"user_id": USER, "key": "  Coding-Language "})
rec("retrieve normalizes lookup key", r.get("data") == "Rust", f"value={r.get('data')!r}")

# 4) suffix stripping: store 'database_preference' -> key 'database'
call("store", "ltm_preference", {"user_id": USER, "key": "database_preference", "value": "PostgreSQL"})
st, r = call("retrieve", "ltm_preference", {"user_id": USER, "key": "database"})
rec("suffix '_preference' stripped (database_preference->database)", r.get("data") == "PostgreSQL", f"value={r.get('data')!r}")

# 5) list-all returns ONE entry per key (no duplicates)
st, r = call("retrieve", "ltm_preferences_all", {"user_id": USER})
data = r.get("data") or {}
rec("list-all deduped (coding_language=Rust, database=PostgreSQL)",
    data.get("coding_language") == "Rust" and data.get("database") == "PostgreSQL",
    f"map={data}")

# 6) on-disk: exactly ONE entry per (user,key) -> no append bloat
root = os.getenv("AGENT_MEMORY_FILE_ROOT") or os.path.expanduser("~/.agent_memory_service/workspaces")
md = Path(root) / f"t_{TEN}__ws_{WS}" / "MEMORY.md"
counts = {}
if md.exists():
    for line in md.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("<!-- am:entry"):
            try:
                m = json.loads(line[len("<!-- am:entry"):-3].strip())
            except Exception:
                continue
            if m.get("user_id") == USER and m.get("tier") == "preferences":
                counts[m.get("key")] = counts.get(m.get("key"), 0) + 1
dupes = {k: c for k, c in counts.items() if c != 1}
rec("no append bloat (1 entry per key on disk)", md.exists() and not dupes, f"counts={counts}")

print("\nRESULT:", "PASS" if all(results) else "FAIL", f"({sum(results)}/{len(results)})")
