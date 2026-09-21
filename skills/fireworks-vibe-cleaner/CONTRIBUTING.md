# Contributing

Please open an issue for a new adapter or a change that expands deletion eligibility before implementation. Small fixes and tests can go straight to a pull request. Use synthetic data; never commit real sessions, local inventories, credentials or private paths.

## Local development

Use Python 3.11+ on macOS or Linux, Git, and `lsof` for filesystem mutation tests. Work in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python3 -m unittest discover -s tests -v
python3 tools/build_skill.py --check
python3 tools/install_canary.py
ruff check .
mypy vibe_cleaner
python3 -m vibe_cleaner.cli doctor
```

Follow the repository CI workflow for the current lint/type/package checks. Tests must not require a TypeSafe key, reach a real provider, or touch the developer's actual harness data. Keep fixtures under temporary directories. Do not run cleanup commands against HOME as a development check.

## Review expectations

Every new cleanup category needs an explicit ownership/rebuildability rule, protected counterexamples, identity and concurrency checks, and recovery evidence. Age, size, a clean Git status or a model's confidence alone cannot establish safe deletion. Session removal requires separate version-specific dependency and real resume validation; it is outside v0.1.

Test changed files, hardlinks/symlinks, occupied restore paths, interrupted operations, unavailable open-handle inspection and malformed provider output where applicable. Preserve uncertainty rather than broadening execution eligibility. State planned, locally tested and remotely verified results separately.

Update both READMEs, compatibility notes and changelog when user-visible behavior changes. Root files are authoritative; generated Skill bundles must be regenerated with the build tool, never hand-edited. PRs should explain the user-visible change, scope, validation and remaining limitations.

## Release

Maintain version/tag consistency, build the Skill artifacts and checksums, run local checks and clean installation, then verify GitHub CI and the published Release. Finally install from the public tag and read back the resulting version. Publishing credentials belong only in an explicitly authorized release workflow, never ordinary CI or fork PRs.
