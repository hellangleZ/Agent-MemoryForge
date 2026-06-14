import pytest


@pytest.mark.unit
def test_docs_smoke_check_allows_root_relative_links(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "docs").mkdir(parents=True, exist_ok=True)

    (repo / "README.md").write_text(
        "# Repo\n\n- [Arch](/docs/ARCHITECTURE.md)\n",
        encoding="utf-8",
    )
    (repo / "docs" / "ARCHITECTURE.md").write_text("# Arch\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    from scripts.docs_smoke_check import main

    assert main() == 0


@pytest.mark.unit
def test_docs_smoke_check_reports_missing_links(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "docs").mkdir(parents=True, exist_ok=True)

    (repo / "README.md").write_text(
        "# Repo\n\n- [Missing](/docs/DOES_NOT_EXIST.md)\n",
        encoding="utf-8",
    )
    (repo / "docs" / "ARCHITECTURE.md").write_text("# Arch\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    from scripts.docs_smoke_check import main

    assert main() == 1
