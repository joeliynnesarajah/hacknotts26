"""
PERSON 2 — The single entry point the backend calls.

rate(items)          -> ScoredOutfit (rules, blended with taste model if trained)
suggest(items, ...)  -> best N outfits for today
"""
import random
from typing import List, Optional

from outfit_logic.feedback_model import TasteModel
from outfit_logic.generate import generate_outfits
from outfit_logic.rules import MATCH_THRESHOLD, score_outfit
from shared.schema import Item, ScoredOutfit, Weather

TASTE_WEIGHT = 0.4  # how much the user's learned taste counts vs the rules


def rate(items: List[Item], taste: Optional[TasteModel] = None) -> ScoredOutfit:
    result = score_outfit(items)
    p = taste.predict(items) if taste else None
    if p is not None:
        blended = (1 - TASTE_WEIGHT) * result.score + TASTE_WEIGHT * p
        result.score = round(blended, 3)
        result.verdict = "MATCH" if blended >= MATCH_THRESHOLD else "MISMATCH"
        result.reasons.append(f"Your past feedback says {p:.0%} likely you'll like it")
    return result


def suggest(items: List[Item], weather: Optional[Weather] = None, taste: Optional[TasteModel] = None,
            exclude_ids: set[str] = frozenset(), top_n: int = 5) -> List[ScoredOutfit]:
    candidates = generate_outfits(items, weather, exclude_ids)
    random.shuffle(candidates)  # so equally good outfits come up in a different order each time
    scored = [rate(o, taste) for o in candidates]
    scored.sort(key=lambda s: s.score, reverse=True)  # stable sort keeps the shuffle among ties
    return scored[:top_n]
