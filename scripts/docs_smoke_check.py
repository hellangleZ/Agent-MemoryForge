from __future__ import annotations

from pathlib import Path
import re


MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _iter_targets(line: str) -> list[str]:
    return [target for _label, target in MD_LINK_RE.findall(line)]


def _is_external(target: str) -> bool:
    return bool(re.match(r"^[a-z]+://", target))


def main() -> int:
    repo_root = Path.cwd().resolve()
    docs_dir = repo_root / "docs"

    paths = [repo_root / "README.md"] + sorted(docs_dir.glob("*.md"))

    errors: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for target in _iter_targets(line):
                if _is_external(target) or target.startswith("mailto:"):
                    continue
                if target.startswith("#"):
                    continue

                target_no_anchor = target.split("#", 1)[0]
                if not target_no_anchor:
                    continue

                if target_no_anchor.startswith("/"):
                    candidate = (repo_root / target_no_anchor.lstrip("/")).resolve()
                else:
                    candidate = (path.parent / target_no_anchor).resolve()

                if not candidate.exists():
                    errors.append(
                        f"{path.relative_to(repo_root)}:{lineno}: broken link -> {target}"
                    )

    if errors:
        for err in errors:
            print(err)
        return 1

    print(f"docs_smoke_check OK ({len(paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
