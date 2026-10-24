"""
THE SHARED ITEM FORMAT — agreed by the whole team on day one.

Everyone builds against these models:
  - Person 1 produces Item objects from photos
  - Person 4 stores and serves them
  - Person 2 scores lists of them
  - Person 3 displays them

Change this file only after telling the whole team.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    top = "top"
    bottom = "bottom"
    dress = "dress"
    shoes = "shoes"
    outerwear = "outerwear"
    accessory = "accessory"


class Pattern(str, Enum):
    solid = "solid"
    stripe = "stripe"
    plaid = "plaid"
    floral = "floral"
    graphic = "graphic"
    other = "other"


class Season(str, Enum):
    spring = "spring"
    summer = "summer"
    autumn = "autumn"
    winter = "winter"


class Item(BaseModel):
    id: str
    name: str
    image: str = Field(description="Path or URL of the background-removed PNG")
    category: Category
    colors: List[str] = Field(description="Main colors as hex codes, most dominant first, e.g. ['#1f3a5f']")
    pattern: Pattern = Pattern.solid
    formality: int = Field(ge=1, le=5, description="1 = loungewear, 3 = smart casual, 5 = formal")
    seasons: List[Season] = Field(default_factory=lambda: list(Season))
    warmth: int = Field(default=2, ge=1, le=5, description="1 = very light, 5 = very warm")


class Outfit(BaseModel):
    # At least one item: scoring nothing is meaningless, and the rules would blow up
    # on an empty list (max() of no formality levels).
    item_ids: List[str] = Field(min_length=1)


class ScoredOutfit(BaseModel):
    item_ids: List[str]
    score: float = Field(description="0 to 1, higher looks better")
    verdict: str = Field(description="'MATCH' or 'MISMATCH'")
    reasons: List[str] = Field(default_factory=list)


class Feedback(BaseModel):
    item_ids: List[str]
    liked: bool


class Weather(BaseModel):
    temperature_c: float
    raining: bool = False
    season: Optional[Season] = None
