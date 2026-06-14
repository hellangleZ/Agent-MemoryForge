from __future__ import annotations

import json

from agent_memory_framework.replay import ReplayRunner, RepoContext, RunRecorder


def test_run_recorder_writes_replay_bundle(tmp_path):
    recorder = RunRecorder(
        name="reduce-context-noise-with-replay",
        request={
            "tenant_id": "t_001",
            "workspace_id": "ws_a",
            "agent": "code-assistant",
            "user_id": "u_001",
            "messages": [{"role": "user", "content": "hello"}],
        },
        repo=RepoContext(root=str(tmp_path), head_sha="abc123", dirty=True),
    )

    recorder.record_result(
        trace={"trace_id": "trace_1", "context_hash": "ctx_1"},
        pytest={"command": "pytest -q"},
        patch={"diff": "diff --git a/a b/a\n+hi\n"},
    )

    out_path = recorder.write_json(tmp_path / "bundle.json")
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert payload["name"] == "reduce-context-noise-with-replay"
    assert payload["repo"]["head_sha"] == "abc123"
    assert payload["content_hash"]
    assert payload["result"]["trace"]["trace_id"] == "trace_1"


def test_replay_runner_calls_executor():
    runner = ReplayRunner(lambda request: {"ok": True, "echo": request.get("agent")})

    recorder = RunRecorder(
        name="n",
        request={"agent": "code-assistant"},
    )
    bundle = recorder.to_bundle()
    result = runner.run(bundle)

    assert result == {"ok": True, "echo": "code-assistant"}
