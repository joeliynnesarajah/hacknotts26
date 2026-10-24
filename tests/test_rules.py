"""Person 2's tests — run with:  pytest"""
import json
from pathlib import Path

from outfit_logic.feedback_model import TasteModel
from outfit_logic.generate import generate_outfits
from outfit_logic.rules import is_neutral, score_outfit
from shared.schema import Item, Weather

ITEMS = {i["id"]: Item(**i) for i in json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "sample_items.json").read_text())}


def outfit(*ids):
    return [ITEMS[i] for i in ids]


def test_neutrals():
    assert is_neutral("#1b1b1b") and is_neutral("#f4f4f2") and is_neutral("#d6c4a3")
    assert not is_neutral("#c0392b")


def test_classic_outfit_matches():
    # white tee, blue jeans, white trainers
    assert score_outfit(outfit("t1", "b1", "s1")).verdict == "MATCH"


def test_formality_mismatch():
    # navy shirt, grey joggers, black loafers
    result = score_outfit(outfit("t2", "b5", "s3"))
    assert result.verdict == "MISMATCH"
    assert any("Formality" in r for r in result.reasons)


def test_competing_patterns():
    # striped top with plaid skirt
    result = score_outfit(outfit("t3", "b4", "s2"))
    assert any("patterns" in r for r in result.reasons)


def test_cold_weather_adds_coat_and_drops_sandals():
    outfits = generate_outfits(list(ITEMS.values()), Weather(temperature_c=3, season="winter"))
    assert outfits
    for o in outfits:
        cats = {it.category for it in o}
        assert "outerwear" in cats
        assert all(it.id != "s4" for it in o)


def test_taste_model_needs_enough_data():
    model = TasteModel()
    assert model.train([outfit("t1", "b1", "s1")], [True]) is False
    outfits = [outfit("t1", "b1", "s1"), outfit("t2", "b5", "s3")] * 6
    liked = [True, False] * 6
    assert model.train(outfits, liked) is True
    assert model.predict(outfit("t1", "b1", "s1")) > model.predict(outfit("t2", "b5", "s3"))
