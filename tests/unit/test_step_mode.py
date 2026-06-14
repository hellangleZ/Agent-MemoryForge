from agent_runtime.product.step_mode import parse_numbered_steps, is_yes, is_cancel


def test_parse_numbered_steps_accepts_contiguous_list():
    text = "1- a\n2- b\n3- c\n"
    assert parse_numbered_steps(text, max_steps=10) == ["a", "b", "c"]


def test_parse_numbered_steps_rejects_non_contiguous():
    assert parse_numbered_steps("1- a\n3- c\n", max_steps=10) is None


def test_parse_numbered_steps_rejects_non_matching_lines():
    assert parse_numbered_steps("a\nb\n", max_steps=10) is None


def test_parse_numbered_steps_truncates_to_max():
    text = "\n".join([f"{i}- s{i}" for i in range(1, 20)]) + "\n"
    got = parse_numbered_steps(text, max_steps=10)
    assert got is not None
    assert len(got) == 10
    assert got[0] == "s1"
    assert got[-1] == "s10"


def test_yes_and_cancel_detection():
    assert is_yes("yes")
    assert is_yes(" YES ")
    assert not is_yes("y")
    assert is_cancel("取消")
    assert is_cancel("cancel")
    assert not is_cancel("continue")
