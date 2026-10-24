"""
PERSON 2 — The single entry point the backend calls.

rate(items)          -> ScoredOutfit (rules, blended with taste model if trained)
suggest(items, ...)  -> best N outfits for today
pick_outfit(...)     -> ONE good outfit for "Dress me", chosen at random among the matches
"""
import random
from typing import Collection, List, Optional

from outfit_logic.feedback_model import TasteModel
from outfit_logic.generate import generate_outfits
from outfit_logic.rules import MATCH_THRESHOLD, score_outfit
from shared.schema import Category, Item, ScoredOutfit, Weather

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


OUTFIT_KINDS = ("separates", "dress")


def outfit_kind(item_ids: Collection[str], items_by_id: dict) -> str:
    return "dress" if any(items_by_id[i].category == Category.dress for i in item_ids if i in items_by_id) else "separates"


def pick_outfit(items: List[Item], weather: Optional[Weather] = None, taste: Optional[TasteModel] = None,
                exclude_ids: set[str] = frozenset(), avoid: Collection[str] = (),
                rng: random.Random = random, kind: Optional[str] = None) -> Optional[ScoredOutfit]:
    """A random good outfit, so "Dress me" gives something different each time.

    kind: "separates" or "dress" to pick within the mode the user is in. With no kind, the
    kind is chosen first, 50/50 among the kinds that have outfits: there are far more
    top+bottom+shoes combinations than dress+shoes ones, so picking from all outfits at once
    would almost never land on a dress.

    Only outfits the scorer calls MATCH are eligible; better scores are more likely
    (weighted by score). `avoid` is the outfit currently on screen, which is skipped
    when there's any other choice. If nothing matches, falls back to one of the three
    best-scoring outfits. None if no outfit (of that kind) can be built at all.
    """
    by_id = {it.id: it for it in items}
    scored = [rate(o, taste) for o in generate_outfits(items, weather, exclude_ids)]
    groups = {k: [s for s in scored if outfit_kind(s.item_ids, by_id) == k] for k in OUTFIT_KINDS}
    if kind in groups:
        scored = groups[kind]
    else:
        available = [k for k in OUTFIT_KINDS if groups[k]]
        scored = groups[rng.choice(available)] if available else []
    if not scored:
        return None
    pool = [s for s in scored if s.verdict == "MATCH"] or sorted(scored, key=lambda s: s.score, reverse=True)[:3]
    # Compare what's visible: coats have no carousel/paper-doll slot, so the same top, bottom and
    # shoes with a different (or no) coat still counts as the outfit already on screen.
    visible = {it.id for it in items if it.category != Category.outerwear}
    avoid_visible = set(avoid) & visible
    fresh = [s for s in pool if not avoid_visible or set(s.item_ids) & visible != avoid_visible]
    pool = fresh or pool
    return rng.choices(pool, weights=[max(s.score, 0.01) for s in pool], k=1)[0]
