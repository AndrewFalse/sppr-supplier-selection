import numpy as np
import pandas as pd
import pytest

from sppr import forecast as fc


def test_naive_and_drift():
    y = np.array([100.0, 101.0, 102.0, 103.0])
    assert np.allclose(fc.Naive().fit(y).predict(3), 103.0)
    d = fc.Drift().fit(y).predict(2)
    assert d[0] > 103.0 and d[1] > d[0]


def test_holt_follows_trend_and_damps():
    y = np.exp(np.linspace(np.log(80), np.log(100), 60))       # устойчивый рост
    m = fc.HoltDamped().fit(y)
    p = m.predict(13)
    assert p[0] > y[-1] * 0.995                                   # продолжает тренд
    assert 0.8 <= m.phi <= 0.98
    steps = np.diff(np.log(p))
    assert steps[-1] <= steps[0] + 1e-12                          # тренд затухает


def test_backtest_metrics_and_intervals():
    rng = np.random.default_rng(0)
    y = 80 * np.exp(np.cumsum(rng.normal(0, 0.01, 120)))
    bt = fc.rolling_backtest(y, {"Случайное блуждание": fc.Naive, "Дрейф": fc.Drift}, 4, 60, 2)
    assert set(bt.model) == {"Случайное блуждание", "Дрейф"}
    assert bt.groupby("model").h.max().eq(4).all()
    met = fc.metrics(bt)
    assert (met.mape > 0).all() and list(met.columns) == ["mae", "mape", "rmse", "mape_hmax"]
    q = fc.conformal_quantiles(bt[bt.model == "Случайное блуждание"])
    assert all(q[h][0.8][0] <= 0 <= q[h][0.8][1] for h in q)
    cov = fc.coverage(bt[bt.model == "Случайное блуждание"], q, 0.8)
    assert 0.7 <= cov <= 0.9                                       # на калибровочных данных ~80 %
    tab = fc.with_intervals(np.array([100.0, 100.0, 100.0, 100.0]), q)
    assert (tab.lo95 <= tab.lo80).all() and (tab.lo80 <= tab.point).all() and (tab.point <= tab.hi80).all()


def test_gradient_boosting_runs():
    rng = np.random.default_rng(1)
    y = 80 * np.exp(np.cumsum(rng.normal(0, 0.01, 90)))
    key = np.full(90, 14.0)
    p = fc.GBReturns(horizon=5).fit(y, key).predict(5)
    assert p.shape == (5,) and np.all(p > 0)
