"""Offline regression tests: sector-news limit bounds and the keyword emotion heuristic."""
import pytest
from fastapi.testclient import TestClient

from backend.dashboard.core.emotion_agent import EmotionAnalysisAgent
from backend.main import app


@pytest.fixture
def api():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---- 5. sector-news limit ----

@pytest.mark.parametrize("limit", ["0", "-1", "101", "99999999999999999999", "abc"])
def test_sector_news_limit_is_bounded(api, limit):
    assert api.get(f"/api/dashboard/sector-news?limit={limit}").status_code == 422


@pytest.mark.parametrize("limit", ["1", "20", "100"])
def test_sector_news_limit_in_range_ok(api, limit):
    assert api.get(f"/api/dashboard/sector-news?limit={limit}").status_code == 200


# ---- 6. emotion heuristic ----

agent = EmotionAnalysisAgent()


def _bias_names(text):
    return [b["bias"] for b in agent.analyze(text)["biases"]]


def test_negated_panic_is_not_panic_selling():
    r = agent.analyze("I will not panic")
    assert r["dominant_bias"] is None
    assert r["biases"] == []
    assert r["emotion_label"] == "calm"
    assert r["negated_keywords"] == ["panic"]


@pytest.mark.parametrize("text", [
    "I will not panic", "I'm not going to panic", "never panic", "I don't panic", "no panic here",
    "I won't sell everything", "I am not scared",
])
def test_negation_window_neutralises_keyword(text):
    assert "panic_selling" not in _bias_names(text)


def test_plain_panic_still_detected():
    r = agent.analyze("I panic and fear a crash")
    assert r["dominant_bias"] == "panic_selling"
    assert r["emotion_label"] == "anxious"


def test_negator_beyond_window_or_other_sentence_does_not_negate():
    assert "panic_selling" in _bias_names("not sure what to do now and so many reasons I panic")  # 5+ tokens away
    assert "panic_selling" in _bias_names("This is not fun. I panic")                              # different sentence


def test_word_boundaries_no_substring_matches():
    # "overall in" contains the substring "all in"; "afternoon"/"mooncake" contain "noon"/"moon"
    for text in ("overall in the afternoon the market was quiet", "overall income is steady", "I ate a mooncake",
                 "dumpling dinner", "the crashed server was restored", "rocketry club", "fearless investor",
                 "afternoon session"):
        r = agent.analyze(text)
        assert r["biases"] == [], (text, r["biases"])
        assert r["dominant_bias"] is None


def test_phrases_still_match_as_whole_words():
    assert "fomo_buying" in _bias_names("I'm going all in on this")
    assert "fomo_buying" in _bias_names("FOMO, all in, to the moon")
    assert "panic_selling" in _bias_names("I want to sell everything")
    assert "revenge_trading" in _bias_names("I need to make it back")
    assert "overconfidence" in _bias_names("this is a sure thing")


def test_multi_keyword_boost_and_label_unchanged():
    r = agent.analyze("FOMO, all in, to the moon")
    assert r["emotion_label"] == "excited" and r["emotion_intensity"] == pytest.approx(0.8)


def test_still_labelled_a_heuristic_and_handles_empty():
    assert agent.analyze("anything")["method"] == "keyword_heuristic"
    assert agent.analyze("")["emotion_label"] == "calm"


def test_sentiment_route_reports_negated_panic_as_neutral(api):
    r = api.post("/api/dashboard/sentiment", json={"message": "I will not panic"}).json()
    assert r["sentiment"] == "neutral" and r["dominant_bias"] is None and r["method"] == "keyword_heuristic"
