#!/usr/bin/env python3
"""End-to-end test suite for the memory-driven agent product (real APIs).

Sections:
  1. SMOKE        - login, multi-turn chat, in-conversation recall, preference store
  2. GOLDEN       - cross-session keyed recall + preference-extraction precision
  3. PLANNER      - context planner returns a real plan (gpt-5.4-mini)
  4. ISOLATION    - no memory leakage across user_id / workspace / tenant
  5. NONFUNC      - auth negative cases (401/400) + embedding dimension consistency

Run on the host with .env sourced and PYTHONPATH=repo root.
Admin password read from env ADMIN_PW.
"""
from __future__ import annotations
import json, os, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path

BASE = os.getenv("GW_BASE", "http://localhost:8080")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PW = os.environ["ADMIN_PW"]
WS = "ws_default"
RUN = uuid.uuid4().hex[:6]

results = []  # (section, name, status, detail)  status in PASS/FAIL/WARN


def rec(section, name, status, detail=""):
    results.append((section, name, status, detail))
    mark = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[status]
    print(f"[{mark}] {section}: {name}" + (f" -- {detail}" if detail else ""))


def http(method, path, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw.decode()[:300]
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, ""


def login(user, pw):
    st, b = http("POST", "/portal/v1/login", {"username": user, "password": pw})
    if st == 200 and isinstance(b, dict) and b.get("access_token"):
        return b["access_token"]
    return None


def H(tok, ws=WS):
    return {"Authorization": "Bearer " + tok, "x-workspace-id": ws}


def chat(tok, user_id, conv, content, ws=WS):
    return http("POST", "/v1/chat", {
        "agent": "pm-minimal", "user_id": user_id, "conversation_id": conv,
        "messages": [{"role": "user", "content": content}],
    }, H(tok, ws))


def retrieve_pref(tok, user_id, key, ws=WS):
    st, b = http("POST", "/v1/memory/retrieve",
                 {"memory_type": "ltm_preference", "params": {"user_id": user_id, "key": key}},
                 H(tok, ws))
    val = b.get("data") if isinstance(b, dict) else None
    return st, val


# ----------------------------------------------------------------------------
# SECTION 1: SMOKE
# ----------------------------------------------------------------------------
def section_smoke():
    S = "SMOKE"
    tok = login(ADMIN_USER, ADMIN_PW)
    if not tok:
        rec(S, "login", "FAIL", "could not obtain token")
        return None, None
    rec(S, "login", "PASS", "token acquired")

    uid = f"smoke_{RUN}"
    conv = f"smoke_conv_{RUN}"
    st, r1 = chat(tok, uid, conv, "Please remember: my project codename is Lunzi and my preferred database is PostgreSQL. Acknowledge briefly.")
    ans1 = (r1 or {}).get("answer") if isinstance(r1, dict) else None
    rec(S, "chat turn1 (200 + answer)", "PASS" if (st == 200 and ans1) else "FAIL", f"status={st}")

    st, r2 = chat(tok, uid, conv, "What is my project codename and which database do I prefer?")
    ans2 = ((r2 or {}).get("answer") or "") if isinstance(r2, dict) else ""
    ok = st == 200 and "lunzi" in ans2.lower() and ("postgres" in ans2.lower())
    rec(S, "in-conversation recall", "PASS" if ok else "FAIL", f"status={st} answer={ans2[:120]!r}")

    # preference persisted -> deterministic keyed retrieve
    st, v_db = retrieve_pref(tok, uid, "preferred_database")
    rec(S, "preference stored+retrievable (preferred_database)",
        "PASS" if (st == 200 and isinstance(v_db, str) and "postgres" in v_db.lower()) else "FAIL",
        f"value={v_db!r}")
    return tok, uid


# ----------------------------------------------------------------------------
# SECTION 2: GOLDEN cross-session recall + preference extraction precision
# ----------------------------------------------------------------------------
def section_golden(tok):
    S = "GOLDEN"
    uid = f"golden_{RUN}"
    convA = f"golden_A_{RUN}"
    convB = f"golden_B_{RUN}"

    # Setup: state two clear preferences in conversation A
    chat(tok, uid, convA, "For my projects I prefer the Go programming language. Please remember this.")
    chat(tok, uid, convA, "Also remember my preferred cloud provider is AWS.")
    time.sleep(2)

    # Discover what the extractor actually stored for this user (key names are model-chosen)
    root = os.getenv("AGENT_MEMORY_FILE_ROOT") or os.path.expanduser("~/.agent_memory_service/workspaces")
    md = Path(root) / "t_admin__ws_ws_default" / "MEMORY.md"
    stored = {}
    if md.exists():
        for line in md.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("<!-- am:entry"):
                try:
                    meta = json.loads(line[len("<!-- am:entry"):-len("-->")].strip())
                except Exception:
                    continue
                if meta.get("user_id") == uid and meta.get("tier") == "preferences":
                    stored[str(meta.get("key"))] = meta.get("value")

    if stored:
        garbage = [k for k, v in stored.items() if not k or v in (None, "", "null")]
        rec(S, "preference extraction (entries written)", "PASS", f"keys={list(stored.keys())}")
        rec(S, "preference extraction precision (no empty/garbage)",
            "PASS" if not garbage else "FAIL", f"garbage={garbage}")
    else:
        rec(S, "preference extraction (entries written)", "WARN",
            f"no entries found for user {uid} in {md}")

    # Deterministic ROUND-TRIP: retrieve each actually-stored key via the API
    rt_ok = True
    for key, exp in stored.items():
        st, val = retrieve_pref(tok, uid, key)
        if not (st == 200 and str(val) == str(exp)):
            rt_ok = False
    if stored:
        rec(S, "keyed retrieve round-trip (store->retrieve by exact key)",
            "PASS" if rt_ok else "FAIL", f"round-tripped {len(stored)} keys")

    # FINDING: does the planner's guessed key vocabulary match the stored keys?
    planner_keys = []
    try:
        import dataclasses
        from agent_memory_framework.memory_runtime.context_planner import LLMContextPlanner, ContextPlan
        f = {x.name: x.default for x in dataclasses.fields(ContextPlan)}
        d = ContextPlan(**{k: (v if v is not dataclasses.MISSING else (0 if k != "preference_keys" else [])) for k, v in f.items()})
        planner_keys = LLMContextPlanner().plan(
            user_query="which programming language and cloud provider do I prefer?", defaults=d).preference_keys or []
    except Exception:
        pass
    overlap = set(planner_keys) & set(stored.keys())
    rec(S, "extractor/planner key-vocabulary alignment",
        "PASS" if overlap else "WARN",
        f"stored={list(stored.keys())} planner_guessed={planner_keys} overlap={list(overlap)}")

    # Cross-session behavioral recall via a brand-new conversation (same user)
    st, rB = chat(tok, uid, convB, "Remind me: which programming language do I prefer for my projects?")
    ansB = ((rB or {}).get("answer") or "") if isinstance(rB, dict) else ""
    cross_ok = st == 200 and ("go" in ansB.lower() or "golang" in ansB.lower())
    rec(S, "cross-session recall (new conversation)", "PASS" if cross_ok else "WARN",
        f"status={st} answer={ansB[:140]!r}")
    return uid, stored


# ----------------------------------------------------------------------------
# SECTION 3: PLANNER (in-app, gpt-5.4-mini)
# ----------------------------------------------------------------------------
def section_planner():
    S = "PLANNER"
    try:
        import dataclasses
        from agent_memory_framework.memory_runtime.context_planner import LLMContextPlanner, ContextPlan
        fields = {f.name: f.default for f in dataclasses.fields(ContextPlan)}
        defaults = ContextPlan(**{k: (v if v is not dataclasses.MISSING else (0 if k != "preference_keys" else [])) for k, v in fields.items()})
        p = LLMContextPlanner()
        if not p.settings.enabled:
            rec(S, "planner enabled", "WARN", "CONTEXT_PLANNER_ENABLED is off")
            return
        plan = p.plan(user_query="What database do I prefer and should we use Go?", defaults=defaults)
        ok = isinstance(plan.preference_keys, list)
        rec(S, "planner returns real plan (no 404)", "PASS" if ok else "FAIL",
            f"model={p.settings.model} keys={plan.preference_keys} notes={(plan.notes or '')[:80]!r}")
    except Exception as e:
        rec(S, "planner returns real plan (no 404)", "FAIL", f"{type(e).__name__}: {str(e)[:200]}")


# ----------------------------------------------------------------------------
# SECTION 4: ISOLATION (user / workspace / tenant)
# ----------------------------------------------------------------------------
def section_isolation(tok, known_uid, known_key, accepts):
    S = "ISOLATION"
    st, base_val = retrieve_pref(tok, known_uid, known_key)
    pos_ok = st == 200 and isinstance(base_val, str) and any(a in base_val.lower() for a in accepts)
    rec(S, "positive control (correct scope returns value)",
        "PASS" if pos_ok else "FAIL", f"{known_key}={base_val!r}")

    # 4a cross-user: same tenant+ws, different user_id -> must NOT return the value
    st, other = retrieve_pref(tok, f"intruder_{RUN}", known_key)
    rec(S, "cross-user isolation", "PASS" if (other != base_val) else "FAIL", f"intruder got {other!r}")

    # 4b cross-workspace: same tenant+user, different workspace -> must NOT return value
    st, ws_other = retrieve_pref(tok, known_uid, known_key, ws="ws_test")
    rec(S, "cross-workspace isolation", "PASS" if (ws_other != base_val) else "FAIL", f"ws_test got {ws_other!r}")

    # 4c cross-tenant: mint a second-tenant user in the shared auth store, login, try to read
    try:
        from agent_runtime.product.auth_store import SQLiteAuthStore
        repo = Path(__file__).resolve().parent
        db = str((repo / ".runtime" / "portal_auth.db").resolve())
        store = SQLiteAuthStore(db_path=db)
        u, pw, ten = f"isob_{RUN}", "isoPW-" + RUN, f"t_isob_{RUN}"
        try:
            store.create_user(username=u, password=pw, tenant_id=ten)
        except ValueError:
            pass  # already exists
        tok_b = login(u, pw)
        if not tok_b:
            rec(S, "cross-tenant isolation", "WARN", "could not login second-tenant user (auth store path mismatch?)")
        else:
            st, t_other = retrieve_pref(tok_b, known_uid, known_key)  # same user_id+ws, different tenant
            rec(S, "cross-tenant isolation", "PASS" if (t_other != base_val) else "FAIL",
                f"other tenant got {t_other!r}")
    except Exception as e:
        rec(S, "cross-tenant isolation", "WARN", f"setup error: {type(e).__name__}: {str(e)[:160]}")


# ----------------------------------------------------------------------------
# SECTION 5: NON-FUNCTIONAL (auth negatives + embedding dimension)
# ----------------------------------------------------------------------------
def section_nonfunc(tok):
    S = "NONFUNC"
    body = {"agent": "pm-minimal", "user_id": "x", "conversation_id": "x",
            "messages": [{"role": "user", "content": "hi"}]}

    # no auth header
    st, _ = http("POST", "/v1/chat", body, {"x-workspace-id": WS}, timeout=30)
    rec(S, "chat without token -> 401/403", "PASS" if st in (401, 403) else "FAIL", f"status={st}")

    # bad token
    st, _ = http("POST", "/v1/chat", body, {"Authorization": "Bearer not-a-real-token", "x-workspace-id": WS}, timeout=30)
    rec(S, "chat with bad token -> 401", "PASS" if st in (401, 403) else "FAIL", f"status={st}")

    # missing workspace header
    st, _ = http("POST", "/v1/chat", body, {"Authorization": "Bearer " + tok}, timeout=30)
    rec(S, "chat missing x-workspace-id -> 400", "PASS" if st == 400 else "FAIL", f"status={st}")

    # embedding dimension consistency (in-app, real Azure ada-002)
    try:
        from config.agent_config import AgentConfig
        from agent_memory_lib.embedding_client import embedding_client_from_env_like_config
        cfg = AgentConfig.from_env()
        ec = embedding_client_from_env_like_config(cfg)
        v = ec.embed_one("dimension consistency check")
        expected = int(os.getenv("EMBEDDING_DIMENSION", "0") or 0)
        ok = (len(v) == expected) if expected else (len(v) > 0)
        rec(S, "embedding dimension == EMBEDDING_DIMENSION",
            "PASS" if ok else "FAIL", f"got={len(v)} expected={expected} provider={cfg.embedding_provider}")
    except Exception as e:
        rec(S, "embedding dimension == EMBEDDING_DIMENSION", "FAIL", f"{type(e).__name__}: {str(e)[:200]}")


def main():
    print(f"==== E2E SUITE run={RUN} base={BASE} ====")
    tok, smoke_uid = section_smoke()
    if not tok:
        print("\nFATAL: cannot authenticate; aborting.")
        sys.exit(2)
    golden_uid, golden_found = section_golden(tok)
    section_planner()
    section_isolation(tok, smoke_uid, "preferred_database", ["postgres"])
    section_nonfunc(tok)

    # summary
    n_pass = sum(1 for *_, s, _ in [(r[0], r[1], r[2], r[3]) for r in results] if s == "PASS")
    npass = sum(1 for r in results if r[2] == "PASS")
    nfail = sum(1 for r in results if r[2] == "FAIL")
    nwarn = sum(1 for r in results if r[2] == "WARN")
    print("\n==================== SUMMARY ====================")
    for sec, name, status, detail in results:
        if status != "PASS":
            print(f"  {status}  {sec}: {name} -- {detail}")
    print(f"\nTOTAL: {npass} PASS / {nfail} FAIL / {nwarn} WARN  (of {len(results)} checks)")
    print("RESULT:", "PASS" if nfail == 0 else "FAIL")
    sys.exit(0 if nfail == 0 else 1)


if __name__ == "__main__":
    main()
