import pandas as pd
import pytest

pulp = pytest.importorskip("pulp")
from sppr import optimize as opt  # noqa: E402


def make_tab():
    rows = [
        # category, vendor, exp_cost, utility, lead, k6, admissible
        ("A", "a1", 100.0, 1.00, 1, 1, True),
        ("A", "a2", 60.0, 0.70, 2, 4, True),
        ("A", "a3", 40.0, 0.50, 12, 3, True),
        ("B", "b1", 200.0, 1.00, 1, 4, True),
        ("B", "b2", 150.0, 0.80, 1, 1, True),
    ]
    tab = pd.DataFrame(rows, columns=["category", "vendor", "exp_cost", "utility", "lead_weeks", "k6", "admissible"])
    tab["unit_cost"] = tab["exp_cost"]
    return tab


def test_demand_and_share_cap():
    r = opt.solve(make_tab(), 10, max_share=0.6, max_suppliers=2, min_lot=2)
    assert r["status"] == "Optimal"
    plan = r["plan"]
    assert plan.groupby("category")["complexes"].sum().eq(10).all()
    assert (plan["complexes"] <= 6).all()
    assert plan.groupby("category")["vendor"].count().le(2).all()


def test_utility_monotone_in_budget():
    tab = make_tab()
    lo = opt.solve(tab, 10, objective="cost")["cost"]
    hi = opt.solve(tab, 10)["cost"]
    us = [opt.solve(tab, 10, budget=b)["utility"] for b in (lo, (lo + hi) / 2, hi)]
    assert us[0] <= us[1] <= us[2]


def test_lead_time_and_infeasibility():
    tab = make_tab()
    r = opt.solve(tab, 10, t_max=6)
    assert r["status"] == "Optimal"
    assert "a3" not in set(r["plan"]["vendor"])
    tab.loc[tab["category"] == "B", "admissible"] = False
    r2 = opt.solve(tab, 10)
    assert r2["status"] != "Optimal"
    assert r2["empty_categories"] == ["B"]


def test_single_admissible_supplier_lifts_share_cap():
    tab = make_tab()
    tab.loc[tab["vendor"] == "b2", "admissible"] = False
    r = opt.solve(tab, 10, max_share=0.6)
    assert r["status"] == "Optimal"
    assert r["categories"]["B"]["single"]
    assert int(r["plan"].loc[r["plan"]["vendor"] == "b1", "complexes"].iloc[0]) == 10


def test_high_risk_cap():
    # без ограничения риска выбирается рискованный, но полезный a2/b1; с ограничением - меньше рискованных
    tab = make_tab()
    free = opt.solve(tab, 10)
    capped = opt.solve(tab, 10, max_high_risk_share=0.3)
    risky = lambda r: r["plan"].merge(tab[["vendor", "k6"]], on="vendor").query("k6 >= 4")["complexes"].sum()
    assert risky(capped) <= 6 and risky(capped) <= risky(free)
