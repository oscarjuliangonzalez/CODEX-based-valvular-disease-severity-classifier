#!/usr/bin/env bash
set -euo pipefail
if conda env list | awk '{print $1}' | grep -qx ar-codex-agents; then
  if [[ "${AR_CODEX_UPDATE_ENV:-0}" == "1" ]]; then
    conda env update -n ar-codex-agents -f environment.yml --prune
  else
    echo "Conda environment ar-codex-agents already exists; set AR_CODEX_UPDATE_ENV=1 to update it."
  fi
else
  conda env create -f environment.yml
fi
eval "$(conda shell.bash hook)"
conda activate ar-codex-agents
pytest
python scripts/smoke_test.py
