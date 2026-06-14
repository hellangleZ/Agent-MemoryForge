from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class RepoContext:
    """Lightweight repo snapshot metadata for reproducible runs."""

    root: str
    head_sha: Optional[str] = None
    dirty: bool = False


@dataclass(frozen=True)
class PatchArtifact:
    """A patch/diff produced by the agent."""

    diff: str
    applies_cleanly: Optional[bool] = None


@dataclass(frozen=True)
class ReplayBundle:
    """Deterministic capture of a single run/turn for later replay."""

    name: str
    created_at_s: int
    request: Dict[str, Any]
    result: Dict[str, Any]
    repo: RepoContext

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "name": self.name,
                "created_at_s": self.created_at_s,
                "request": self.request,
                "result": self.result,
                "repo": asdict(self.repo),
            },
            sort_keys=True,
        )
        return sha256(payload.encode("utf-8")).hexdigest()


class RunRecorder:
    """Collects request/response artifacts for a single run."""

    def __init__(
        self,
        *,
        name: str,
        request: Dict[str, Any],
        repo: Optional[RepoContext] = None,
    ) -> None:
        self._name = name
        self._request = dict(request)
        self._repo = repo or RepoContext(root=str(Path.cwd()))
        self._result: Dict[str, Any] = {}

    def record_result(self, **result_fields: Any) -> None:
        self._result.update(result_fields)

    def to_bundle(self) -> ReplayBundle:
        return ReplayBundle(
            name=self._name,
            created_at_s=int(time.time()),
            request=self._request,
            result=self._result,
            repo=self._repo,
        )

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        bundle = self.to_bundle()
        payload = {
            **asdict(bundle),
            "content_hash": bundle.content_hash,
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return path


class ReplayRunner:
    """Replays a captured bundle through a provided executor."""

    def __init__(self, executor: Callable[[Dict[str, Any]], Dict[str, Any]]):
        self._executor = executor

    def run(self, bundle: ReplayBundle) -> Dict[str, Any]:
        return self._executor(bundle.request)


__all__ = [
    "PatchArtifact",
    "ReplayBundle",
    "ReplayRunner",
    "RepoContext",
    "RunRecorder",
]
