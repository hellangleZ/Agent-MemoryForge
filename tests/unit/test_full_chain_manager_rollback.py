from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.product.full_chain_manager import FullChainManager, ManagedService


@pytest.mark.unit
def test_start_group_rolls_back_on_health_check_failure(tmp_path: Path) -> None:
    repo_root = tmp_path
    mgr = FullChainManager(repo_root=repo_root)

    services = [
        ManagedService(
            name="svc1",
            cmd=["python", "-c", "import time; time.sleep(60)"],
            cwd=repo_root,
            env={},
        ),
        ManagedService(
            name="svc2",
            cmd=["python", "-c", "import time; time.sleep(60)"],
            cwd=repo_root,
            env={},
        ),
    ]

    def _ok() -> bool:
        return True

    def _fail() -> bool:
        return False

    with pytest.raises(RuntimeError):
        mgr.start_group(
            services,
            health_checks={"svc1": _ok, "svc2": _fail},
            health_timeout_s=0.2,
            rollback_on_failure=True,
        )

    # Both pid files should be gone due to rollback.
    assert not (repo_root / ".runtime" / "full_chain" / "svc1.pid").exists()
    assert not (repo_root / ".runtime" / "full_chain" / "svc2.pid").exists()
