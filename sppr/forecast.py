"""Прогнозные модели (практика №6).

Модели работают с логарифмом уровня ряда (курс, индекс цен):
- Naive      - случайное блуждание: прогноз = последнее значение;
- Drift      - последнее значение + средний наклон за окно обучения;
- HoltDamped - экспоненциальное сглаживание Хольта с затухающим трендом (параметры - минимум
               суммы квадратов ошибок прогноза на шаг вперёд, scipy.optimize);
- GBReturns  - градиентный бустинг (scikit-learn) по признакам прошлых изменений, волатильности и
               ключевой ставки; прогнозирует изменение ряда сразу на горизонт h (прямая стратегия).
Оценка - скользящее начало (rolling origin): модель переобучается в каждой точке и прогнозирует
h = 1..H шагов вперёд. Интервалы - эмпирические квантили относительных ошибок этой проверки
(конформный подход): отдельно для каждого горизонта, без предположения о нормальности.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingRegressor


class Naive:
    name = "Случайное блуждание"

    def fit(self, y, exog=None):
        self.last = float(np.log(y[-1]))
        return self

    def predict(self, h, exog_last=None):
        return np.exp(np.full(h, self.last))


class Drift:
    name = "Дрейф"

    def fit(self, y, exog=None):
        x = np.log(np.asarray(y, dtype=float))
        self.last = x[-1]
        self.slope = (x[-1] - x[0]) / (len(x) - 1)
        return self

    def predict(self, h, exog_last=None):
        return np.exp(self.last + self.slope * np.arange(1, h + 1))


class HoltDamped:
    name = "Хольт с затухающим трендом"

    @staticmethod
    def _filter(x, a, b, phi):
        level, trend = x[0], x[1] - x[0]
        sse = 0.0
        for t in range(1, len(x)):
            pred = level + phi * trend
            e = x[t] - pred
            sse += e * e
            level = pred + a * e
            trend = phi * trend + a * b * e
        return sse, level, trend

    def fit(self, y, exog=None):
        x = np.log(np.asarray(y, dtype=float))
        res = minimize(lambda p: self._filter(x, *p)[0], x0=[0.5, 0.05, 0.9],
                       bounds=[(0.01, 0.99), (0.001, 0.5), (0.8, 0.98)], method="L-BFGS-B")
        self.alpha, self.beta, self.phi = res.x
        _, self.level, self.trend = self._filter(x, *res.x)
        return self

    def predict(self, h, exog_last=None):
        damp = np.cumsum(self.phi ** np.arange(1, h + 1))
        return np.exp(self.level + damp * self.trend)


def _features(x, key, t):
    """Признаки в момент t: изменения за 1, 4, 13 шагов, волатильность, отклонение от средней, ставка."""
    r = np.diff(x[: t + 1])
    return [x[t] - x[t - 1], x[t] - x[t - 4], x[t] - x[t - 13], float(np.std(r[-13:])),
            x[t] - float(np.mean(x[t - 25: t + 1])), key[t], key[t] - key[t - 13]]


class GBReturns:
    name = "Градиентный бустинг"
    min_hist = 26

    def __init__(self, horizon=13, seed=0):
        self.H = horizon
        self.seed = seed

    def fit(self, y, exog=None):
        x = np.log(np.asarray(y, dtype=float))
        key = np.asarray(exog if exog is not None else np.zeros(len(x)), dtype=float)
        X, Y = [], []
        for t in range(self.min_hist, len(x) - 1):
            f = _features(x, key, t)
            for h in range(1, self.H + 1):
                if t + h < len(x):
                    X.append(f + [h])
                    Y.append(x[t + h] - x[t])
        self.model = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200,
                                                   l2_regularization=1.0, random_state=self.seed)
        self.model.fit(np.array(X), np.array(Y))
        self.last_feat = _features(x, key, len(x) - 1)
        self.last = x[-1]
        return self

    def predict(self, h, exog_last=None):
        X = np.array([self.last_feat + [k] for k in range(1, h + 1)])
        return np.exp(self.last + self.model.predict(X))


def rolling_backtest(y, factories, horizon, start, step, exog=None, dates=None):
    """Скользящее начало: для каждой точки origin модели обучаются на y[:origin+1] и прогнозируют horizon шагов.
    Возвращает DataFrame(origin, origin_date, model, h, actual, pred, err_pct)."""
    y = np.asarray(y, dtype=float)
    rows = []
    for origin in range(start, len(y) - horizon, step):
        hist = y[: origin + 1]
        ex = None if exog is None else np.asarray(exog)[: origin + 1]
        for name, make in factories.items():
            pred = make().fit(hist, ex).predict(horizon)
            for h in range(1, horizon + 1):
                act = y[origin + h]
                rows.append({"origin": origin, "origin_date": None if dates is None else dates[origin], "model": name,
                             "h": h, "actual": act, "pred": pred[h - 1], "err_pct": act / pred[h - 1] - 1})
    return pd.DataFrame(rows)


def metrics(bt):
    """MAE, MAPE и RMSE по моделям (по всем горизонтам и на последнем горизонте)."""
    g = bt.assign(ae=(bt.actual - bt.pred).abs(), ape=bt.err_pct.abs(), se=(bt.actual - bt.pred) ** 2)
    hmax = g.h.max()
    out = g.groupby("model").agg(mae=("ae", "mean"), mape=("ape", "mean"), rmse=("se", lambda s: float(np.sqrt(s.mean()))))
    out["mape_hmax"] = g[g.h == hmax].groupby("model")["ape"].mean()
    return out.sort_values("mape")


def conformal_quantiles(bt_model, levels=(0.8, 0.95)):
    """Квантили относительной ошибки по горизонтам: {h: {(lo, hi) для каждого уровня}}."""
    q = {}
    for h, g in bt_model.groupby("h"):
        q[h] = {lv: (float(np.quantile(g.err_pct, (1 - lv) / 2)), float(np.quantile(g.err_pct, 1 - (1 - lv) / 2)))
                for lv in levels}
    return q


def coverage(bt_eval, q, level=0.8):
    """Доля фактических значений внутри интервала уровня level."""
    inside = [(1 + q[r.h][level][0]) <= r.actual / r.pred <= (1 + q[r.h][level][1]) for r in bt_eval.itertuples()]
    return float(np.mean(inside)) if inside else float("nan")


def with_intervals(pred, q, levels=(0.8, 0.95)):
    """Точечный прогноз -> таблица с интервалами."""
    rows = []
    for h, p in enumerate(pred, start=1):
        row = {"h": h, "point": float(p)}
        for lv in levels:
            lo, hi = q[h][lv]
            row[f"lo{int(lv * 100)}"] = float(p * (1 + lo))
            row[f"hi{int(lv * 100)}"] = float(p * (1 + hi))
        rows.append(row)
    return pd.DataFrame(rows)
