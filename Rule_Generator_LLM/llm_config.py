"""
Connection settings of the language-model service (EVREN).

Both users of the service - the rule compiler and the incident summarizer - take their
address, key and model from here. Values come from the environment; for local runs they
can be put in a `.env` file at the repository root (see `.env.example`), which is not
committed. Variables that are already set in the environment always win, so
`EVREN_API_KEY=""` switches every call to the service off.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env_file(path: Path) -> None:
    """Reads KEY=VALUE lines into the environment without overriding what is already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name and not name.startswith("#") and name not in os.environ:
            os.environ[name] = value.strip().strip("\"'")


_load_env_file(ENV_FILE)

BASE_URL = os.getenv("EVREN_BASE_URL", "https://evren-llmapi.ssyz.org.tr/v1")
MODEL = os.getenv("EVREN_VLM_MODEL", "qwen3-vl-30b")
API_KEY = os.getenv("EVREN_API_KEY", "")
