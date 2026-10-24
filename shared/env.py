"""
Loads API keys from a local file into os.environ, so nobody has to export them by hand.

Put lines like these in `keys.env` (or `.env`) in the project root — both are gitignored:
    POLLINATIONS_API_KEY=sk_...
    GEMINI_API_KEY=...

`.env` is only read if it's a file (some of us have a virtualenv folder called .env).
Variables already set in the environment always win.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILES = [ROOT / "keys.env", ROOT / ".env"]


def load_env() -> None:
    for path in ENV_FILES:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.removeprefix("export ").strip()
            os.environ.setdefault(key, value.strip().strip("'\""))
