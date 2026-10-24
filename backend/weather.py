"""
PERSON 4 — Weather from Open-Meteo (free, no API key).

Defaults to Nottingham's coordinates; pass your own lat/lon.
If the request fails (no internet, etc.) fall back to a mild default
so the rest of the app keeps working.

TODO (Person 4):
  - [ ] Fill in the functions below
"""
from datetime import date

import requests

from shared.schema import Season, Weather

DEFAULT_LAT, DEFAULT_LON = 52.95, -1.15
URL = "https://api.open-meteo.com/v1/forecast"


def season_for(day: date) -> Season:
    """Month to season, northern hemisphere: Mar-May spring, Jun-Aug summer,
    Sep-Nov autumn, Dec-Feb winter."""
    pass


def get_weather(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> Weather:
    """GET URL with params latitude, longitude, current=temperature_2m,precipitation.
    temperature_c = temperature_2m, raining = precipitation > 0, season = season_for(today).
    Use a short timeout; if anything fails, return 14°C, not raining."""
    pass
