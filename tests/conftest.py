"""
Runs before any test module is imported, so these settings apply everywhere:
  - a throwaway database, so tests never touch data/wardrobe.db
  - no API keys and placeholder-only tagging, so tests never hit the network
    (tests that need a provider set TAGGER_PROVIDER_ORDER themselves and mock it)
Empty strings (not missing) so keys.env can't fill them back in.
"""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="wardrobe-test-"))
os.environ["WARDROBE_DB"] = str(_tmp / "test.db")
os.environ["POLLINATIONS_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["TAGGER_PROVIDER_ORDER"] = "placeholder"
