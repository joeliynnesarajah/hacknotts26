"""Test isolation.

Every run gets a throwaway database and image directory, so a test upload never
lands in the demo wardrobe. This must happen before any test module imports
`backend.main`, because main.py opens the database at import time.
"""
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="wardrobe-tests-"))
os.environ["WARDROBE_DB"] = str(_TMP / "test.db")
os.environ["WARDROBE_IMAGES_DIR"] = str(_TMP / "images")

# Blank (not unset) so a real .env can't turn the tagger into a network call:
# load_dotenv does not override existing values, and an empty string is falsy.
for _key in ("POLLINATIONS_API_KEY", "GEMINI_API_KEY"):
    os.environ[_key] = ""


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
