from scripts.rescore import spread, summarise


def _ans(turn, s):
    return {"question_turn": turn, "question": "q", "scores": dict(zip(("relevance", "structure", "specificity", "evidence"), s)),
            "average": sum(s) / 4}


def test_spread():
    assert spread([3, 4.5, 3.5]) == 1.5
    assert spread([]) == 0.0


def test_summarise():
    r1 = {"overall_score": 3.0, "answers": [_ans(1, (3, 3, 3, 3))]}
    r2 = {"overall_score": 3.5, "answers": [_ans(1, (4, 3, 3, 4))]}
    s = summarise([r1, r2])
    assert s["overall_spread"] == 0.5
    a = s["answers"][0]
    assert a["criteria"]["relevance"] == 1 and a["criteria"]["structure"] == 0
    assert a["average_spread"] == 0.5
