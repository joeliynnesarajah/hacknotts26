"""
PERSON 2 — Rules-based "does it look nice?" scoring.

score_outfit(items) -> ScoredOutfit with a score from 0 to 1, a verdict and reasons.
Each rule subtracts a penalty from a starting score of 1.0, and adds a reason
so the user can see WHY ("two competing patterns").

TODO (Person 2):
  - [ ] Tune the penalty numbers by trying lots of outfits
  - [ ] Add rules: metal accessories matching, etc.
"""
import colorsys
from itertools import combinations
from typing import List, Tuple

from shared.schema import Category, Item, Pattern, ScoredOutfit

MATCH_THRESHOLD = 0.6
SHOE_CLASH_PENALTY = 0.12


def hex_to_hsv(hex_color: str) -> Tuple[float, float, float]:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    return hue * 360, sat, val


def is_neutral(hex_color: str) -> bool:
    """Black, white, grey, beige, navy-ish dark tones and denim go with almost anything."""
    hue, sat, val = hex_to_hsv(hex_color)
    if sat < 0.18 or val < 0.22 or (val > 0.9 and sat < 0.25):
        return True
    if 15 <= hue <= 45 and (sat < 0.55 or val < 0.5):  # beige / camel / tan / brown leather
        return True
    if 200 <= hue <= 225 and val < 0.7:  # navy and denim blues
        return True
    return False


def hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def color_penalty(items: List[Item]) -> Tuple[float, List[str]]:
    accents = []  # the non-neutral main color of each item
    for it in items:
        main = it.colors[0]
        if not is_neutral(main):
            accents.append((it.name, hex_to_hsv(main)[0]))

    penalty, reasons = 0.0, []
    if len(accents) >= 3:
        penalty += 0.25
        reasons.append(f"Too many bold colors ({len(accents)}); try swapping one for a neutral")
    for (name_a, ha), (name_b, hb) in combinations(accents, 2):
        gap = hue_gap(ha, hb)
        if gap <= 35:
            reasons.append(f"{name_a} and {name_b} are analogous colors (good)")
        elif 150 <= gap <= 210:
            reasons.append(f"{name_a} and {name_b} are complementary colors (bold but works)")
        elif 60 <= gap < 150:
            penalty += 0.3
            reasons.append(f"{name_a} and {name_b} clash")
    if not accents:
        reasons.append("All neutrals — safe and classic")
    elif len(accents) == 1:
        penalty -= 0.1  # small bonus: a single pop of color is a stylist favourite
        reasons.append(f"{accents[0][0]} adds one pop of color against neutrals")
    return penalty, reasons


def pattern_penalty(items: List[Item]) -> Tuple[float, List[str]]:
    patterned = [it.name for it in items if it.pattern != Pattern.solid]
    if len(patterned) >= 2:
        return 0.35, [f"Competing patterns: {', '.join(patterned)}"]
    return 0.0, []


def formality_penalty(items: List[Item]) -> Tuple[float, List[str]]:
    levels = [it.formality for it in items]
    gap = max(levels) - min(levels)
    if gap >= 3:
        return 0.45, ["Formality mismatch (e.g. joggers with loafers)"]
    if gap == 2:
        return 0.15, ["Slight formality mismatch"]
    return 0.0, []


def shoe_penalty(items: List[Item]) -> Tuple[float, List[str]]:
    """Bold shoes should pick up the bottom's color family. Neutral shoes, or bold shoes
    against neutral bottoms (red trainers with jeans), are fine."""
    shoes = next((it for it in items if it.category == Category.shoes), None)
    bottom = next((it for it in items if it.category == Category.bottom), None)
    if not shoes or not bottom:
        return 0.0, []
    shoe_color, bottom_color = shoes.colors[0], bottom.colors[0]
    if is_neutral(shoe_color) or is_neutral(bottom_color):
        return 0.0, []
    if hue_gap(hex_to_hsv(shoe_color)[0], hex_to_hsv(bottom_color)[0]) <= 35:
        return 0.0, []
    return SHOE_CLASH_PENALTY, [f"{shoes.name} don't pick up the color of {bottom.name}"]


def score_outfit(items: List[Item]) -> ScoredOutfit:
    score, reasons = 0.9, []  # room for bonuses to lift good outfits to 1.0
    for rule in (color_penalty, pattern_penalty, formality_penalty, shoe_penalty):
        p, r = rule(items)
        score -= p
        reasons += r
    score = max(0.0, min(1.0, score))
    return ScoredOutfit(
        item_ids=[it.id for it in items],
        score=round(score, 3),
        verdict="MATCH" if score >= MATCH_THRESHOLD else "MISMATCH",
        reasons=reasons,
    )
