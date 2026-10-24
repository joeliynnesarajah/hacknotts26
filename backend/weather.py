"""
PERSON 4 — Weather from Open-Meteo (free, no API key).

Defaults to Nottingham's coordinates; pass your own lat/lon.
If the request fails (no internet, etc.) we fall back to a mild default
so the rest of the app keeps working.
"""
from datetime import date

import requests

from shared.schema import Season, Weather

DEFAULT_LAT, DEFAULT_LON = 52.95, -1.15
URL = "https://api.open-meteo.com/v1/forecast"


def season_for(day: date) -> Season:
    m = day.month  # Northern hemisphere
    if m in (3, 4, 5):
        return Season.spring
    if m in (6, 7, 8):
        return Season.summer
    if m in (9, 10, 11):
        return Season.autumn
    return Season.winter


def get_weather(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> Weather:
    season = season_for(date.today())
    try:
        r = requests.get(URL, params={"latitude": lat, "longitude": lon,
                                      "current": "temperature_2m,precipitation"}, timeout=5)
        r.raise_for_status()
        cur = r.json()["current"]
        return Weather(temperature_c=cur["temperature_2m"], raining=cur["precipitation"] > 0, season=season)
    except Exception:
        return Weather(temperature_c=14.0, raining=False, season=season)
