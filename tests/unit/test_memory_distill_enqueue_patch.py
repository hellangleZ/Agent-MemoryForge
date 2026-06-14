import os

import pytest


@pytest.mark.unit
def test_gateway_imports_distill_symbols():
    # Smoke test: file can be imported with distill env disabled.
    os.environ.pop("MEMORY_DISTILL_ENABLED", None)
    import agent_runtime.product.agent_gateway as gw  # noqa: F401
