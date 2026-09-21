#!/usr/bin/env bash
set -euo pipefail

# Idempotent bootstrap for the Python validators in this repository.
# Runs after the repository is checked out, from the repository root.

python3 -m pip install --upgrade pip

# Core third-party packages used across the validator branches (pandas, lxml,
# chardet) plus the test runner. Listed explicitly so the environment is usable
# even on branches (and on main) that do not ship a requirements.txt.
python3 -m pip install pandas lxml chardet pytest

# Honor per-branch pinned dependencies when a requirements file is present.
if [ -f requirements.txt ]; then
  python3 -m pip install -r requirements.txt
fi
