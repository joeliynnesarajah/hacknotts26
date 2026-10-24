"""Person 2's tests — run with:  pytest"""
import json
from pathlib import Path

from outfit_logic.feedback_model import TasteModel
from outfit_logic.generate import generate_outfits
from outfit_logic.rules import is_neutral, score_outfit, shoe_penalty
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


def make(id, category, color):
    return Item(id=id, name=id, image="", category=category, colors=[color], formality=2)


def test_shoe_rule_neutral_shoes_are_fine():
    # white trainers + blue jeans
    assert shoe_penalty([make("jeans", "bottom", "#3b5b8a"), make("trainers", "shoes", "#f4f4f2")]) == (0.0, [])


def test_shoe_rule_black_on_black_is_fine():
    assert shoe_penalty([make("trousers", "bottom", "#1b1b1b"), make("loafers", "shoes", "#141414")]) == (0.0, [])


def test_shoe_rule_bold_shoes_with_neutral_bottoms_are_fine():
    # red shoes + jeans: a pop of color, not a clash
    assert shoe_penalty([make("jeans", "bottom", "#3b5b8a"), make("red shoes", "shoes", "#c0392b")])[0] == 0


def test_shoe_rule_clashing_shoes_are_penalised():
    # red shoes + green trousers
    penalty, reasons = shoe_penalty([make("green trousers", "bottom", "#3e8e41"),
                                     make("red shoes", "shoes", "#c0392b")])
    assert penalty > 0 and "red shoes" in reasons[0]


def test_taste_model_save_and_load(tmp_path):
    model = TasteModel()
    model.train([outfit("t1", "b1", "s1"), outfit("t2", "b5", "s3")] * 6, [True, False] * 6)
    path = tmp_path / "taste.joblib"
    model.save(path)
    loaded = TasteModel.load(path)
    assert loaded.predict(outfit("t1", "b1", "s1")) == model.predict(outfit("t1", "b1", "s1"))
    TasteModel().save(path)  # untrained -> removes the stale file
    assert not path.exists() and TasteModel.load(path).model is None
