from __future__ import annotations

import json

from agent_memory_framework.replay import (
    RepoContext,
    ReplayBundle,
    ReplayRunner,
    RunRecorder,
)


def _make_recorder(tmp_path) -> RunRecorder:
    return RunRecorder(
        name="reduce-context-noise-with-replay",
        request={
            "tenant_id": "t_001",
            "workspace_id": "ws_a",
            "agent": "code-assistant",
            "user_id": "u_001",
            "messages": [{"role": "user", "content": "make the context concise"}],
        },
        repo=RepoContext(root=str(tmp_path), head_sha="test", dirty=True),
    )


def test_content_hash_is_deterministic_for_same_inputs(tmp_path):
    """Identical content at the same logical time must hash identically — the
    property replay relies on to detect drift. created_at_s is pinned so the
    hash is a pure function of content."""
    base = _make_recorder(tmp_path)
    base.record_result(patch={"diff": "diff --git a/x b/x\n+ok\n"})
    bundle = base.to_bundle()

    twin = ReplayBundle(
        name=bundle.name,
        created_at_s=bundle.created_at_s,
        request=dict(bundle.request),
        result=dict(bundle.result),
        repo=bundle.repo,
    )
    assert twin.content_hash == bundle.content_hash


def test_content_hash_changes_when_result_changes(tmp_path):
    """A different captured result must yield a different hash — otherwise replay
    could not distinguish a regression from a clean run."""
    base = _make_recorder(tmp_path)
    base.record_result(patch={"diff": "diff --git a/x b/x\n+ok\n"})
    bundle = base.to_bundle()

    regressed = ReplayBundle(
        name=bundle.name,
        created_at_s=bundle.created_at_s,
        request=dict(bundle.request),
        result={"patch": {"diff": "diff --git a/x b/x\n+REGRESSION\n"}},
        repo=bundle.repo,
    )
    assert regressed.content_hash != bundle.content_hash


def test_write_json_embeds_matching_hash(tmp_path):
    """Persisted bundle must carry the same content_hash as the in-memory bundle
    (tamper-evidence), and preserve the recorded artifacts."""
    recorder = _make_recorder(tmp_path)
    recorder.record_result(
        patch={"diff": "diff --git a/x b/x\n+ok\n"},
        trace={"trace_id": "trace_1", "context_hash": "ctx_1"},
    )
    expected_hash = recorder.to_bundle().content_hash

    path = recorder.write_json(tmp_path / "replay_bundle.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["content_hash"] == expected_hash
    assert payload["result"]["trace"]["trace_id"] == "trace_1"


def test_replay_runner_drives_request_through_executor(tmp_path):
    """ReplayRunner must feed the captured *request* (not the recorded result)
    into the executor and return the executor's fresh output."""
    recorder = _make_recorder(tmp_path)
    recorder.record_result(patch={"diff": "old"})
    bundle = recorder.to_bundle()

    seen: dict = {}

    def executor(request):
        seen.update(request)
        return {"patch": {"diff": "fresh"}}

    out = ReplayRunner(executor).run(bundle)

    assert seen["user_id"] == "u_001"
    assert seen["messages"][0]["content"] == "make the context concise"
    assert out["patch"]["diff"] == "fresh"
