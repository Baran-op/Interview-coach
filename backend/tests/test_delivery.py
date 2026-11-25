"""Tests for delivery.text_stats. Run from the repo root: pytest backend/tests"""

import pytest

from backend import delivery, feedback
from backend.delivery import text_stats


def test_empty():
    assert text_stats("") == {"words": 0, "fillers": 0, "hedges": 0, "i_count": 0, "we_count": 0, "numbers": 0}


def test_words():
    assert text_stats("one  two\nthree\tfour")["words"] == 4


def test_fillers_reuse_feedback():
    t = "Um, I basically, you know, actually did it, like, a lot"
    assert text_stats(t)["fillers"] == feedback.filler_words([t])["count"] == 5


def test_like_not_filler_without_commas():
    assert text_stats("I'd like to use tools like Jira")["fillers"] == 0


@pytest.mark.parametrize(
    "text,n",
    [
        ("I think it worked", 1),
        ("I guess so, I suppose", 2),
        ("Maybe, perhaps, probably", 3),
        ("Hopefully it lands", 1),
        ("I feel like we did well", 1),
        ("i THINK so", 1),
        ("I thinking about it", 0),
        ("We shipped it", 0),
    ],
)
def test_hedges(text, n):
    assert text_stats(text)["hedges"] == n


def test_hedges_do_not_overlap_fillers():
    for h in ["I think", "I guess", "I suppose", "maybe", "perhaps", "probably", "hopefully", "I feel like"]:
        s = text_stats(h)
        assert s["hedges"] == 1 and s["fillers"] == 0, h
    for f in ["um", "uh", "you know", "I mean", "kind of", "sort of", "basically", "literally", "actually"]:
        assert text_stats(f)["hedges"] == 0, f


def test_i_count():
    s = text_stats("I led it. I'm proud, I've learned, I'd do it again. Ask me about my team.")
    assert s["i_count"] == 6 and s["we_count"] == 0


def test_i_count_curly_apostrophe_and_no_substrings():
    assert text_stats("I’m in")["i_count"] == 1
    assert text_stats("It is mine, my")["i_count"] == 1


def test_we_count():
    s = text_stats("We built it. We're live, we've grown, we'd scale. Give us our data.")
    assert s["we_count"] == 6 and s["i_count"] == 0


def test_we_not_substring():
    assert text_stats("answer weekly bus")["we_count"] == 0


def test_i_and_we_mixed():
    s = text_stats("We shipped and I owned the rollout for our team")
    assert (s["i_count"], s["we_count"]) == (1, 2)


@pytest.mark.parametrize(
    "text,n",
    [
        ("We had 12 people", 1),
        ("Grew 30% in 2 years", 2),
        ("Saved £5m and $2.5k", 2),
        ("Revenue of €1.2bn", 1),
        ("10,000 users", 1),
        ("Ten percent faster", 1),
        ("Two hundred thousand users", 1),
        ("Cut it in half and then double it", 2),
        ("a hundred calls, a million rows", 2),
        ("no figures here", 0),
        ("Went from 20 to 5 days", 2),
    ],
)
def test_numbers(text, n):
    assert text_stats(text)["numbers"] == n


def test_target_seconds():
    assert delivery.TARGET_SECONDS["intro"] == (60, 90)
    assert delivery.TARGET_SECONDS["motivation"] == (45, 90)
    assert delivery.TARGET_SECONDS["behavioural"] == (90, 150)
    assert "technical" not in delivery.TARGET_SECONDS
