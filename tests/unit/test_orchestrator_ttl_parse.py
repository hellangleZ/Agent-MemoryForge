import pytest

from agent_memory_service.orchestrator import MemoryOrchestrator


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("10", 10),
        (10, 10),
        (10.2, 10),
    ],
)
def test_parse_ttl_seconds_valid(raw, expected):
    assert MemoryOrchestrator._parse_ttl_seconds(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", [0, -1, "0", "-5", True, {}, []])
def test_parse_ttl_seconds_invalid(raw):
    with pytest.raises(ValueError):
        MemoryOrchestrator._parse_ttl_seconds(raw)
