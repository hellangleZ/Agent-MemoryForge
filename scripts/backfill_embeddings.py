#!/usr/bin/env python3
"""Backfill embeddings for existing file-first entries into the per-workspace vector index.

Idempotent: clears and re-inserts vectors per markdown file. Run with .env sourced so the
embedding provider is configured. Safe to run repeatedly.

Usage: PYTHONPATH=. python scripts/backfill_embeddings.py [--workspace-root DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_memory_service.file_first.entries import iter_entries
from agent_memory_service.file_first.index_sqlite import SqliteFtsIndex
from agent_memory_service.file_first.paths import default_file_root
from agent_memory_lib.embedding_client import embedding_client_from_env_like_config
from config.agent_config import AgentConfig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace-root", default=None)
    ap.add_argument("--max-chars", type=int, default=8000)
    args = ap.parse_args()

    root = Path(args.workspace_root).expanduser() if args.workspace_root else default_file_root()
    if not root.exists():
        print(f"workspace root not found: {root}")
        return 0

    ec = embedding_client_from_env_like_config(AgentConfig.from_env())

    total_ws = total_files = total_vectors = 0
    for ws in sorted(p for p in root.iterdir() if p.is_dir()):
        index_path = ws / ".index" / "index.sqlite"
        try:
            index = SqliteFtsIndex(index_path=index_path)
        except Exception as e:
            print(f"[skip] {ws.name}: index error {e}")
            continue
        total_ws += 1
        try:
            for md in sorted(ws.rglob("*.md")):
                rel = md.relative_to(ws).as_posix()
                try:
                    text = md.read_text(encoding="utf-8")
                except Exception:
                    continue
                entries = [pe for pe in iter_entries(text) if (pe.content or "").strip()]
                if not entries:
                    continue
                index.delete_vectors_by_path(path=rel)
                n = 0
                for pe in entries:
                    meta = pe.metadata or {}
                    content = (pe.content or "").strip()[: args.max_chars]
                    try:
                        emb = ec.embed_one(content)
                    except Exception as e:
                        print(f"  [embed-fail] {ws.name}/{rel}: {e}")
                        continue
                    index.insert_vector(
                        path=rel,
                        entry_id=str(meta.get("id") or ""),
                        tier=str(meta.get("tier") or ""),
                        scope=str(meta.get("scope") or ""),
                        created_at=str(meta.get("created_at") or ""),
                        line_start=int(pe.start_line or 1),
                        content=content[:2000],
                        metadata=meta,
                        embedding=emb,
                    )
                    n += 1
                total_files += 1
                total_vectors += n
                print(f"  {ws.name}/{rel}: {n} vectors")
        finally:
            index.close()

    print(f"\nDONE: {total_vectors} vectors across {total_files} files in {total_ws} workspaces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
