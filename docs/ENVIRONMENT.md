# Environment

Create and test the Conda environment:

    conda env create -f environment.yml
    conda activate ar-codex-agents
    pytest
    python scripts/smoke_test.py

If the environment already exists, `scripts/setup_conda.sh` reuses it by default and runs verification. Set `AR_CODEX_UPDATE_ENV=1` to force a Conda update from `environment.yml`.

Mock mode is CPU-compatible and does not require a GPU, model weights, external segmentation service, LangGraph, LangChain, OpenAI Agents SDK, or an OpenAI API key.
