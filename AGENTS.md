# Agent entry

Read `SKILL.md`, then `README.md` for executable entrypoints. `CLAUDE.md` points to the same contract.

- This is a standalone public toolkit, not a device backup repository.
- Work outside this Git tree. Never commit real keys, serials, profiles, images or logs.
- No hardware changes while editing, testing or publishing this project.
- Native build tests are synthetic. Hardware execution is separately explicit via `--execute`.
- Preserve exact source pins, partition guards, strict readback and no-reset-on-failure behavior.
- Use the caller's actual environment and existing authorization. Never infer compatibility from the product name alone.
- Local checks with Python 3.11+: `ruff check .`, `ruff format --check .`, `mypy scripts tests native`, `pytest`. Install pinned requirements-dev first. Native tests run during `scripts/native_build.py` using separately acquired upstream input.
- Publication check: `python3 scripts/privacy_scan.py --history`, manual diff review, and third-party license review.
