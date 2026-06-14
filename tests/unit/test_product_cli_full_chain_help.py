from __future__ import annotations

import subprocess
import sys


def test_product_cli_has_full_chain_commands():
    out = subprocess.run(
        [sys.executable, "-m", "agent_runtime.product.cli", "-h"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "run-full-chain" in out.stdout
    assert "full-chain-status" in out.stdout
    assert "full-chain-stop" in out.stdout
    assert "full-chain-logs" in out.stdout
    assert "full-chain-logs-stream" in out.stdout
    assert "full-chain-deps" in out.stdout
    assert "full-chain-services" in out.stdout
    assert "full-chain-start" in out.stdout
