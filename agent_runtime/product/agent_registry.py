"""Product agent discovery/loader used by the gateway.

The product gateway runtime is built around `DemoRuntime` + `DemoAgent`
(`agent_runtime/product/framework.py`). Some framework templates also
define `agent_memory_framework.agent.Agent` subclasses, but those are not
compatible with the gateway runtime.

Keep this module product-scoped (not in the framework) to avoid importing
`agent_runtime` from `agent_memory_framework`.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Dict, Iterable, Type

from agent_memory_framework.demo_agent import DemoAgent


@dataclass(frozen=True)
class DiscoveredProductAgent:
    key: str
    spec: str
    cls: Type[DemoAgent]


def _iter_modules(package_name: str) -> Iterable[str]:
    pkg = importlib.import_module(package_name)
    if not getattr(pkg, "__path__", None):
        return []
    for modinfo in pkgutil.iter_modules(pkg.__path__):
        yield f"{package_name}.{modinfo.name}"


def _default_agent_key(module_basename: str) -> str:
    # Preserve existing public default for the minimal demo.
    if module_basename == "minimal_demo":
        return "pm-minimal"
    return module_basename.replace("_agent", "").replace("_", "-")


def _load_object_from_spec(spec: str):
    if ":" not in spec:
        raise ValueError("Invalid spec; expected 'module:AttrName'")
    module_name, attr_name = spec.split(":", 1)
    mod = importlib.import_module(module_name)
    return getattr(mod, attr_name)


def discover_product_agents(
    package: str = "agent_runtime.product.templates",
) -> Dict[str, DiscoveredProductAgent]:
    """Discover gateway-compatible product agents (DemoAgent subclasses)."""

    discovered: Dict[str, DiscoveredProductAgent] = {}
    for module_name in _iter_modules(package):
        module_basename = module_name.rsplit(".", 1)[-1]
        mod = importlib.import_module(module_name)

        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if not isinstance(obj, type) or not issubclass(obj, DemoAgent) or obj is DemoAgent:
                continue
            if obj.__module__ != mod.__name__:
                continue

            spec = f"{obj.__module__}:{attr_name}"
            key = _default_agent_key(module_basename)
            discovered.setdefault(
                key,
                DiscoveredProductAgent(key=key, spec=spec, cls=obj),
            )

    return discovered


def load_product_agent(name_or_spec: str) -> Type[DemoAgent]:
    """Load a gateway-compatible agent class by registry key or module spec."""

    discovered = discover_product_agents()
    if name_or_spec in discovered:
        return discovered[name_or_spec].cls

    obj = _load_object_from_spec(name_or_spec)
    if not isinstance(obj, type) or not issubclass(obj, DemoAgent):
        raise TypeError(f"{name_or_spec} is not a DemoAgent subclass")
    return obj
