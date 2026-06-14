"""Gateway app entrypoint.

Intent: a product-facing gateway that is not tied to a specific demo package.
"""

from __future__ import annotations

from agent_runtime.product.agent_gateway import app

__all__ = ["app"]
