import numpy as np
import pandas as pd
import pytest

from sppr import risk


def test_fx_scenarios_probabilities_sum_to_one():
    dates = pd.date_range("2023-01-01", periods=400, freq="D")
    rates = pd.Series(np.linspace(80, 100, 400), index=dates)
    fx = risk.fx_scenarios(rates, 91, 0.05)
    assert fx["prob"].sum() == pytest.approx(1.0)
    assert list(fx["scenario"]) == risk.FX_NAMES


def test_cvar_is_mean_of_tail():
    costs = np.arange(1, 101)
    assert risk.cvar(costs, 0.95) == pytest.approx(np.mean(costs[costs >= np.quantile(costs, 0.95)]))


def test_rollback_expectation_and_min():
    fx = pd.DataFrame({"scenario": risk.FX_NAMES, "prob": [0.2, 0.5, 0.3]})
    sprobs = {"A": {"в срок": 1.0, "задержка": 0.0, "срыв": 0.0},
              "B": {"в срок": 0.5, "задержка": 0.5, "срыв": 0.0}}
    leaf = {}
    for s, base in (("A", 100), ("B", 90)):
        for f in risk.FX_NAMES:
            for st in risk.STATES:
                leaf[(s, f, st)] = base + (30 if st == "задержка" else 0)
    g = risk.build_tree(["A", "B"], fx, sprobs, leaf)
    best, value = risk.rollback(g)
    # A: 100; B: 0.5*90 + 0.5*120 = 105 -> лучше A
    assert best == "A" and value == pytest.approx(100)
    assert g.nodes["B"]["value"] == pytest.approx(105)


def test_criteria_wald_savage():
    costs = pd.DataFrame({"s1": [10, 20], "s2": [30, 15]}, index=["A", "B"])
    out = risk.criteria(costs, pd.Series({"s1": 0.5, "s2": 0.5}), pessimism=0.5)
    assert out.loc["A", "Вальд (худший случай)"] == 30
    assert out.loc["B", "Сэвидж (макс. сожаление)"] == 10   # B: сожаления 10 и 0
    assert out.loc["A", "Сэвидж (макс. сожаление)"] == 15   # A: сожаления 0 и 15


def test_simulator_advance_has_no_fx_and_delay_cost():
    fx = pd.DataFrame({"scenario": risk.FX_NAMES, "prob": [0.3, 0.4, 0.3], "delta": [-0.1, 0.0, 0.1]})
    probs = {"on_time": 0.5, "delay": 0.4, "fail": 0.1}
    vendors = {("ИБП", "X"): {"unit_cost": 100.0, "exposure": 1.0, "probs": probs, "repl": "Y"},
               ("ИБП", "Y"): {"unit_cost": 120.0, "exposure": 0.0, "probs": probs, "repl": "X"}}
    params = {"n_complexes": 1, "urgency_premium": 0.0, "fail_days": 42, "delay_days": 28, "horizon_days": 91,
              "storage_rate": 0.0, "key_rate": 0.0, "contract_value": 1000.0, "key_rate_divisor": 300,
              "crew_cost_per_day": 0.0}
    sim = risk.Simulator(vendors, fx, params, n=20000, seed=1)
    adv = sim.run({"ИБП": {"X": 1}}, "advance")
    # без курса и простоя затраты = 100 (поставка) или 120 (замена при срыве)
    assert set(np.unique(adv["cost"])) <= {100.0, 120.0}
    probs_analytic = risk.state_probs({"ИБП": {"X": 1}}, vendors)
    assert probs_analytic["срыв"] == pytest.approx(0.1)
    assert (adv["state"] == 2).mean() == pytest.approx(0.1, abs=0.01)
