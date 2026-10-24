"""
PERSON 4 — Weather from Open-Meteo (free, no API key).

Defaults to Nottingham's coordinates; pass your own lat/lon.
If the request fails (no internet, etc.) we fall back to a mild default
so the rest of the app keeps working. Results are cached for 10 minutes, since every
"Dress me" press asks for the weather and the live call takes ~0.4s.
"""
import time
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


CACHE_SECONDS = 600
_cache: dict = {}  # (lat, lon) -> (fetched_at, Weather)


def get_weather(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> Weather:
    hit = _cache.get((lat, lon))
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1].model_copy()  # a copy: callers sometimes override temperature_c
    weather = _fetch_weather(lat, lon)
    _cache[(lat, lon)] = (time.monotonic(), weather)
    return weather.model_copy()


def _fetch_weather(lat: float, lon: float) -> Weather:
    season = season_for(date.today())
    try:
        r = requests.get(URL, params={"latitude": lat, "longitude": lon,
                                      "current": "temperature_2m,precipitation"}, timeout=5)
        r.raise_for_status()
        cur = r.json()["current"]
        return Weather(temperature_c=cur["temperature_2m"], raining=cur["precipitation"] > 0, season=season)
    except Exception:
        return Weather(temperature_c=14.0, raining=False, season=season)
