# Requirements (legacy)

The source of truth for dependencies is `pyproject.toml` extras:

- Minimal: `pip install -e .`
- Full chain: `pip install -e '.[all]'`
- Per-module: `pip install -e '.[framework]'`, `.[gateway]`, `.[memory-service]`, `.[embedding]`, `.[dev]`.

This `requirements/` folder exists only for environments that cannot (or should
not) resolve extras from `pyproject.toml`.

If you need a requirements file, generate it from extras in a controlled build
step (lockfile or image build), rather than keeping a hand-maintained list that
drifts from `pyproject.toml`.

