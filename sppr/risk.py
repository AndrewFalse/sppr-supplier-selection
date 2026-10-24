"""Модель принятия решений в условиях неопределённости (практика №3).

- fx_scenarios      - сценарии курса и их вероятности по историческим данным ЦБ;
- Simulator         - метод Монте-Карло: курс + исходы поставки по каждому поставщику;
- build_tree/rollback - дерево решений на networkx и его свёртка (ожидание в узлах случая, минимум в узле решения);
- criteria          - критерии Байеса, Вальда, Сэвиджа, Гурвица по матрице затрат;
- cvar              - средние затраты в худших (1 - alpha) исходах.
"""
import networkx as nx
import numpy as np
import pandas as pd

FX_NAMES = ["укрепление", "стабильно", "ослабление"]
STATES = ["в срок", "задержка", "срыв"]


def fx_scenarios(rates, horizon_days, threshold, since=None):
    """rates: Series курса по датам. Возвращает DataFrame: scenario, prob, delta (среднее изменение в сценарии)."""
    s = rates.sort_index().asfreq("D").ffill()
    change = (s.shift(-horizon_days) / s - 1).dropna()
    if since:
        change = change[since:]
    bucket = pd.cut(change, [-np.inf, -threshold, threshold, np.inf], labels=FX_NAMES)
    prob = bucket.value_counts(normalize=True).reindex(FX_NAMES).fillna(0)
    delta = change.groupby(bucket, observed=False).mean().reindex(FX_NAMES).fillna(0)
    return pd.DataFrame({"scenario": FX_NAMES, "prob": prob.values, "delta": delta.values, "n": len(change)})


def cvar(costs, alpha=0.95):
    """Средние затраты в худших (1 - alpha) долях исходов (затраты: чем больше, тем хуже)."""
    costs = np.asarray(costs, dtype=float)
    var = np.quantile(costs, alpha)
    return float(costs[costs >= var].mean())


class Simulator:
    """Общие случайные числа для всех стратегий: одинаковые сценарии курса и исходы поставщиков,
    поэтому разница между стратегиями не искажается шумом."""

    def __init__(self, vendors, fx, params, n, seed):
        self.vendors = vendors      # {(category, vendor): dict(unit_cost, exposure, probs, repl)}
        self.fx = fx                # DataFrame fx_scenarios
        self.p = params
        rng = np.random.default_rng(seed)
        self.fx_idx = rng.choice(len(fx), size=n, p=fx["prob"].to_numpy() / fx["prob"].sum())
        self.u = {key: rng.random(n) for key in vendors}
        self.n = n

    def run(self, mix, mode, prob_scale=1.0, key_rate=None):
        """mix: {category: {vendor: share}}. Возвращает dict(cost, state, fx) по всем симуляциям."""
        p = self.p
        key_rate = p["key_rate"] if key_rate is None else key_rate
        n_cx, n = p["n_complexes"], self.n
        delta = self.fx["delta"].to_numpy()[self.fx_idx]
        total = np.zeros(n)
        purchase_now = 0.0
        any_delay = np.zeros(n, bool)
        any_fail = np.zeros(n, bool)
        delayed_share = np.zeros(n)
        delay_days = np.zeros(n)
        for cat, shares in mix.items():
            u_cat = np.zeros(n)
            days_cat = np.zeros(n)
            for vendor, share in shares.items():
                if share <= 0:
                    continue
                v = self.vendors[(cat, vendor)]
                pr = v["probs"]
                bad = min(1.0, (pr["delay"] + pr["fail"]) * prob_scale)
                fail_p = bad * pr["fail"] / (pr["delay"] + pr["fail"])
                u = self.u[(cat, vendor)]
                fail = u >= 1 - fail_p
                delay = (u >= 1 - bad) & ~fail
                base = share * n_cx * v["unit_cost"]
                fx_factor = 1 + v["exposure"] * delta if mode == "on_delivery" else np.ones(n)
                paid = base * fx_factor
                if mode == "advance":
                    purchase_now += base
                r = self.vendors[(cat, v["repl"])]
                repl_cost = share * n_cx * r["unit_cost"] * (1 + p["urgency_premium"]) * (1 + r["exposure"] * delta)
                total += np.where(fail, repl_cost, paid)
                any_delay |= delay
                any_fail |= fail
                u_cat += share * (delay | fail)
                days_cat = np.maximum(days_cat, np.where(fail, p["fail_days"], np.where(delay, p["delay_days"], 0)))
            delayed_share = np.maximum(delayed_share, u_cat)
            delay_days = np.maximum(delay_days, days_cat)
        if mode == "advance":
            # запас куплен заранее: задержки и поиск замены укладываются в горизонт до монтажа
            delay_days = np.maximum(delay_days - p["horizon_days"], 0)
            total += purchase_now * (key_rate * p["horizon_days"] / 365 + p["storage_rate"])
        exposure_days = delayed_share * delay_days
        total += p["contract_value"] * key_rate / p["key_rate_divisor"] * exposure_days
        total += p["crew_cost_per_day"] * exposure_days
        state = np.where(any_fail, 2, np.where(any_delay, 1, 0))
        return {"cost": total, "state": state, "fx": self.fx_idx}


def state_probs(mix, vendors, prob_scale=1.0):
    """Аналитические вероятности состояния поставки для стратегии (поставщики независимы)."""
    on, no_fail = 1.0, 1.0
    for cat, shares in mix.items():
        for vendor, share in shares.items():
            if share <= 0:
                continue
            pr = vendors[(cat, vendor)]["probs"]
            bad = min(1.0, (pr["delay"] + pr["fail"]) * prob_scale)
            fail_p = bad * pr["fail"] / (pr["delay"] + pr["fail"])
            on *= 1 - bad
            no_fail *= 1 - fail_p
    return {"в срок": on, "задержка": no_fail - on, "срыв": 1 - no_fail}


def build_tree(strategies, fx, sprobs, leaf_cost):
    """Дерево: Решение -> стратегии -> курс (случай) -> поставка (случай) -> лист с затратами.
    sprobs[s] = {state: prob}; leaf_cost[(s, fx_name, state)] = затраты."""
    g = nx.DiGraph()
    g.add_node("Решение", kind="decision")
    for s in strategies:
        g.add_node(s, kind="chance", label=s)
        g.add_edge("Решение", s)
        for fx_row in fx.itertuples():
            fx_node = f"{s}|{fx_row.scenario}"
            g.add_node(fx_node, kind="chance")
            g.add_edge(s, fx_node, prob=float(fx_row.prob))
            for st in STATES:
                leaf = f"{fx_node}|{st}"
                g.add_node(leaf, kind="leaf", value=float(leaf_cost[(s, fx_row.scenario, st)]))
                g.add_edge(fx_node, leaf, prob=float(sprobs[s][st]))
    return g


def rollback(g, root="Решение"):
    """Свёртка дерева: в узлах случая - ожидание, в узле решения - минимум затрат."""
    for node in reversed(list(nx.topological_sort(g))):
        kind = g.nodes[node]["kind"]
        if kind == "leaf":
            continue
        children = list(g.successors(node))
        if kind == "chance":
            total_p = sum(g.edges[node, c]["prob"] for c in children)
            g.nodes[node]["value"] = sum(g.edges[node, c]["prob"] * g.nodes[c]["value"] for c in children) / total_p
        else:
            best = min(children, key=lambda c: g.nodes[c]["value"])
            g.nodes[node]["value"] = g.nodes[best]["value"]
            g.nodes[node]["best"] = best
    return g.nodes[root]["best"], g.nodes[root]["value"]


def criteria(costs, probs, pessimism):
    """costs: DataFrame стратегии × состояния природы (затраты), probs: вероятности состояний.
    Возвращает таблицу значений критериев (чем меньше, тем лучше)."""
    regret = costs - costs.min(axis=0)
    out = pd.DataFrame({
        "Байес (ожидание)": costs.mul(probs, axis=1).sum(axis=1) / probs.sum(),
        "Вальд (худший случай)": costs.max(axis=1),
        "Сэвидж (макс. сожаление)": regret.max(axis=1),
        "Гурвиц": pessimism * costs.max(axis=1) + (1 - pessimism) * costs.min(axis=1),
    })
    return out
