"""
PERSON 2 — Learning the user's taste from thumbs up/down (scikit-learn).

Each outfit becomes a row of numbers (features); liked = 1, disliked = 0.
A logistic regression learns which features the user likes.
Until there's enough feedback (MIN_SAMPLES), predict() returns None and
the app just uses the rules score.

TODO (Person 2):
  - [ ] Add CLIP image embeddings as extra features (from Person 1)
  - [ ] Try RandomForestClassifier and compare accuracy
  - [ ] Save/load the model with joblib instead of retraining every time
"""
from typing import List, Optional

import numpy as np
from sklearn.linear_model import LogisticRegression

from outfit_logic.rules import hex_to_hsv, is_neutral, score_outfit
from shared.schema import Item, Pattern

MIN_SAMPLES = 10


def features(items: List[Item]) -> List[float]:
    formalities = [it.formality for it in items]
    hsv = [hex_to_hsv(it.colors[0]) for it in items]
    return [
        score_outfit(items).score,                                  # what the rules think
        np.mean(formalities),                                       # how dressy overall
        max(formalities) - min(formalities),                        # formality spread
        sum(it.pattern != Pattern.solid for it in items),           # number of patterns
        sum(not is_neutral(it.colors[0]) for it in items),          # number of bold colors
        float(np.mean([s for _, s, _ in hsv])),                     # average saturation
        float(np.mean([v for _, _, v in hsv])),                     # average brightness
        float(np.mean([it.warmth for it in items])),                # how warm
    ]


class TasteModel:
    def __init__(self):
        self.model: Optional[LogisticRegression] = None

    def train(self, outfits: List[List[Item]], liked: List[bool]) -> bool:
        if len(outfits) < MIN_SAMPLES or len(set(liked)) < 2:
            self.model = None
            return False
        X = np.array([features(o) for o in outfits])
        y = np.array(liked, dtype=int)
        self.model = LogisticRegression(max_iter=1000).fit(X, y)
        return True

    def predict(self, items: List[Item]) -> Optional[float]:
        """Probability (0-1) the user likes this outfit, or None if not trained."""
        if self.model is None:
            return None
        return float(self.model.predict_proba([features(items)])[0, 1])
