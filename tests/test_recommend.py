import numpy as np
import pandas as pd
import pytest

from sppr import recommend as rec

W = pd.Series({"k1": 0.5, "k2": 0.5})
CRIT_CFG = [{"id": "k1", "direction": "min"}, {"id": "k2", "direction": "max"}]


def local_table():
    return pd.DataFrame([
        {"category": "A", "vendor": "a1", "k1": 0.5, "k2": 0.6},
        {"category": "A", "vendor": "a2", "k1": 0.3, "k2": 0.3},
        {"category": "A", "vendor": "a3", "k1": 0.2, "k2": 0.1},
        {"category": "B", "vendor": "b1", "k1": 0.6, "k2": 0.5},
        {"category": "B", "vendor": "b2", "k1": 0.4, "k2": 0.5},
    ])


def admissible(excluded=()):
    t = local_table()[["category", "vendor"]].copy()
    t["admissible"] = ~t["vendor"].isin(excluded)
    return t


def test_context_weights_normalized_and_shifted():
    w = rec.context_weights(W, {"k2": 3.0})
    assert w.sum() == pytest.approx(1.0) and w["k2"] == pytest.approx(0.75)


def test_rescore_excludes_and_renormalizes():
    sc = rec.rescore(local_table(), W, admissible(excluded=("a1",)))
    assert "a1" not in set(sc.vendor)
    a = sc[sc.category == "A"]
    assert a["k1"].sum() == pytest.approx(1.0) and a["k2"].sum() == pytest.approx(1.0)
    assert a.iloc[0]["vendor"] == "a2" and a.iloc[0]["rank"] == 1


def test_confidence_dominant_vs_close():
    loc = local_table()
    loc.loc[loc.vendor == "b1", ["k1", "k2"]] = [0.55, 0.45]   # компромисс: b1 лучше по k1, b2 - по k2
    loc.loc[loc.vendor == "b2", ["k1", "k2"]] = [0.45, 0.55]
    w = pd.Series({"k1": 0.55, "k2": 0.45})
    sc = rec.rescore(loc, w, admissible())
    conf = rec.confidence(sc, w, kappa=50, n=4000)
    assert conf["A"] == pytest.approx(1.0)          # a1 лучше по обоим критериям
    assert 0.6 < conf["B"] < 0.9                     # b1 лидирует, только пока вес k1 больше веса k2


def test_price_counterfactual_finds_cut():
    alts = pd.DataFrame([{"category": "B", "vendor": "b1", "price_rub": 100.0},
                         {"category": "B", "vendor": "b2", "price_rub": 150.0}])
    loc = pd.DataFrame([{"category": "B", "vendor": "b1", "k1": 0.6, "k2": 0.5},
                        {"category": "B", "vendor": "b2", "k1": 0.4, "k2": 0.5}])
    sc = rec.rescore(loc, W, loc[["category", "vendor"]].assign(admissible=True))
    cut = rec.price_counterfactual("B", sc, alts, W, CRIT_CFG)
    assert cut is not None and 0.3 < cut < 0.4              # нужно подешеветь до ~100 руб.: снижение ~33 %


def test_actions_include_approval_when_in_plan():
    plan = pd.DataFrame([{"category": "B", "vendor": "b2", "complexes": 6}, {"category": "B", "vendor": "b1", "complexes": 4}])
    kb_table = pd.DataFrame([{"vendor": "b2", "flag_rules": "R9, R10, R11"}, {"vendor": "b1", "flag_rules": ""}])
    acts = rec.action_recommendations(plan, kb_table, {"holding": 1e5}, 2e5, (75.0, 85.0), approval_whatif="тест")
    assert acts[0]["priority"] == 1 and "b2" in acts[0]["action"] and "тест" in acts[0]["action"]
    assert any("ЗИП" in a["action"] for a in acts)
    assert all(not ("." in a["action"].split("руб")[0][-4:] and a["action"][0].isdigit()) for a in acts)
