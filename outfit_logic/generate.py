"""
PERSON 2 — Building candidate outfits and filtering out impossible ones.

TODO (Person 2):
  - [ ] Add optional accessories to templates
  - [ ] Smarter rain handling (avoid suede, prefer boots)
"""
from itertools import product
from typing import Dict, Iterable, List, Optional

from shared.schema import Category, Item, Weather

# Each template is a list of categories that make one outfit.
TEMPLATES = [
    [Category.top, Category.bottom, Category.shoes],
    [Category.dress, Category.shoes],
    [Category.top, Category.bottom, Category.outerwear, Category.shoes],
    [Category.dress, Category.outerwear, Category.shoes],
]

COAT_BELOW_C = 14  # suggest outerwear below this temperature


def by_category(items: Iterable[Item]) -> Dict[Category, List[Item]]:
    groups: Dict[Category, List[Item]] = {c: [] for c in Category}
    for it in items:
        groups[it.category].append(it)
    return groups


def suits_weather(item: Item, weather: Optional[Weather]) -> bool:
    if weather is None:
        return True
    if weather.season and weather.season not in item.seasons:
        return False
    t = weather.temperature_c
    if t < 8 and item.warmth <= 1 and item.category != Category.top:  # light tops can be layered
        return False
    if t > 24 and item.warmth >= 4:
        return False
    return True


def generate_outfits(items: List[Item], weather: Optional[Weather] = None,
                     exclude_ids: set[str] = frozenset()) -> List[List[Item]]:
    usable = [it for it in items if it.id not in exclude_ids and suits_weather(it, weather)]
    groups = by_category(usable)
    wants_coat = weather is not None and weather.temperature_c < COAT_BELOW_C

    outfits: List[List[Item]] = []
    for template in TEMPLATES:
        has_coat = Category.outerwear in template
        if weather is not None and has_coat != wants_coat:
            continue
        outfits += [list(combo) for combo in product(*(groups[c] for c in template))]
    return outfits
