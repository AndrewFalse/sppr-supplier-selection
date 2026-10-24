"""Практика №3: стратегии закупки в условиях неопределённости.

Вход:  config/p3_risk.json, data/raw/cbr_fx.csv, data/raw/cbr_key_rate.csv,
       data/processed/alternatives_scored.csv, outputs/p2/results.csv (ранги АНР)
Выход: outputs/p3/*.csv, summary.json, decision_tree.png
Запуск: python3 scripts/p3_risk.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = ["Times New Roman", "DejaVu Sans"]
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import brentq, minimize_scalar  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sppr import ratings, risk  # noqa: E402

OUT = ROOT / "outputs" / "p3"


def load():
    cfg = json.loads((ROOT / "config" / "p3_risk.json").read_text(encoding="utf-8"))
    fx_all = pd.read_csv(ROOT / "data" / "raw" / "cbr_fx.csv", parse_dates=["date"])
    rates = fx_all[fx_all.currency == cfg["fx"]["currency"]].set_index("date")["rate_rub_per_unit"]
    fx = risk.fx_scenarios(rates, cfg["project"]["horizon_days"], cfg["fx"]["threshold"], cfg["fx"]["since"])
    key = pd.read_csv(ROOT / "data" / "raw" / "cbr_key_rate.csv", parse_dates=["date"]).sort_values("date")
    key_rate = float(key["key_rate_pct"].iloc[-1]) / 100
    key_date = key["date"].iloc[-1].date().isoformat()
    alts = pd.read_csv(ROOT / "data" / "processed" / "alternatives_scored.csv", dtype=str).fillna("")
    ranks = pd.read_csv(ROOT / "outputs" / "p2" / "results.csv")
    return cfg, fx, key_rate, key_date, alts, ranks


def exposure(row, table):
    if ratings.is_russia(row["production_country"]):
        return table["russian_production"]
    if ratings.is_russia(row["vendor_country"]):
        return table["russian_brand_foreign_production"]
    if row["ru_status"] == "official_distributor":
        return table["official_distributor"]
    return table["other"]


def build_vendors(cfg, alts, ranks):
    bom = cfg["bom"]
    vendors = {}
    for row in alts.to_dict("records"):
        cat, v = row["category"], row["vendor"]
        if cat == "ПК и серверы":
            split = cfg["pc_server_split"][v]
            unit = bom["ПК"] * split["ПК"] + bom["Сервер"] * split["Сервер"]
        else:
            unit = bom[cat] * float(row["price_rub"])
        status = row["ru_status"] if row["ru_status"] in cfg["supply"] else "unknown"
        order = ranks[ranks.category == cat].sort_values("rank")["vendor"].tolist()
        repl = next(x for x in order if x != v)        # замена при срыве - лучший по АНР из остальных
        vendors[(cat, v)] = {"unit_cost": unit, "exposure": exposure(row, cfg["fx_exposure"]),
                             "probs": cfg["supply"][status], "repl": repl, "status": status}
    return vendors


def mix_for(strategy, x=None):
    x = strategy.get("leader_share", 1.0) if x is None else x
    def share(s):
        return x if s == "x" else (1 - x if s == "1-x" else float(s))
    return {cat: {v: share(s) for v, s in shares.items()} for cat, shares in strategy["mix"].items()}


def metrics(res):
    c = res["cost"]
    return {"mean": c.mean(), "std": c.std(), "p95": np.quantile(c, 0.95), "cvar95": risk.cvar(c, 0.95),
            "min": c.min(), "max": c.max()}


def draw_tree(g, fx, sprobs, strategies, names, best, path, expand="С1"):
    """Дерево решений в классической нотации (как в TreePlan / PrecisionTree):
    квадрат - узел решения, круг - узел случая, треугольник - конечный исход;
    название ветви над линией, вероятность под линией, значение свёртки у узла;
    неоптимальные ветви решения отсечены «//», свёрнутые поддеревья помечены «+».
    Значения - ожидаемые затраты, млн руб. (единицы указываются в подписи к рисунку)."""
    plt.rcParams.update({"font.family": ["Arial", "DejaVu Sans"], "font.size": 6.5})
    fig, ax = plt.subplots(figsize=(6.3, 3.5), dpi=300)
    ax.axis("off")
    v = lambda x: f"{x / 1e6:.2f}".replace(".", ",")
    pr = lambda x: f"{x:.2f}".replace(".", ",")
    LW, K = 0.6, "black"
    row_h = 1.0
    # строки: 9 исходов раскрытой стратегии, затем по строке на свёрнутые стратегии
    others = [s_ for s_ in strategies if s_ != expand]
    term_y = [-(i * row_h) for i in range(9)]
    fx_y = [sum(term_y[i * 3:(i + 1) * 3]) / 3 for i in range(3)]
    ys = {expand: sum(fx_y) / 3}
    for i, s_ in enumerate(others):
        ys[s_] = term_y[-1] - (i + 1.3) * row_h
    order = sorted(strategies, key=lambda s_: -ys[s_])
    y_dec = (ys[order[0]] + ys[order[-1]]) / 2
    X_DEC, X_S, X_FX, X_T = 0.0, 4.0, 6.4, 10.6
    SH = 0.35   # длина «плеча» (наклонного участка) ветви
    MS = 6.5    # размер маркеров узлов, pt (не зависит от масштаба осей)

    def branch(x0, y0, x1, y1, above, below=None, prune=False):
        ax.plot([x0, x0 + SH, x1], [y0, y1, y1], color=K, lw=LW, solid_capstyle="butt", zorder=1)
        ax.text(x0 + SH + 0.1, y1 + 0.1, above, ha="left", va="bottom")
        if below is not None:
            ax.text(x0 + SH + 0.1, y1 - 0.1, below, ha="left", va="top")
        if prune:
            xm = x1 - 0.55
            for dx in (-0.05, 0.05):
                ax.plot([xm + dx - 0.05, xm + dx + 0.05], [y1 - 0.16, y1 + 0.16], color=K, lw=LW, zorder=2)

    def node(kind, x, y, value=None):
        style = {"decision": ("s", "#d9d9d9", MS + 0.5), "chance": ("o", "white", MS), "terminal": ("<", "white", MS - 0.5)}
        m, face, size = style[kind]
        ax.plot([x], [y], marker=m, ms=size, mfc=face, mec=K, mew=LW, zorder=3)
        if value is not None:
            ax.text(x - 0.08, y - 0.2, value, ha="right", va="top", fontsize=6)

    node("decision", X_DEC, y_dec, v(g.nodes[best]["value"]))
    for s_ in strategies:
        y = ys[s_]
        branch(X_DEC, y_dec, X_S, y, f"{s_} {names[s_]}", prune=(s_ != best))
        node("chance", X_S, y, v(g.nodes[s_]["value"]))
        if s_ != expand:
            ax.plot([X_S, X_S + 0.5], [y, y], color=K, lw=LW, zorder=1)
            ax.plot([X_S + 0.62], [y], marker="s", ms=MS, mfc="white", mec=K, mew=LW, zorder=3)
            ax.text(X_S + 0.62, y - 0.02, "+", ha="center", va="center", fontsize=6.5, zorder=4)
            continue
        for i, fxr in enumerate(fx.itertuples()):
            fy = fx_y[i]
            fnode = f"{s_}|{fxr.scenario}"
            branch(X_S, y, X_FX, fy, f"Курс: {fxr.scenario}", pr(fxr.prob))
            node("chance", X_FX, fy, v(g.nodes[fnode]["value"]))
            for j, st in enumerate(risk.STATES):
                ty = term_y[i * 3 + j]
                branch(X_FX, fy, X_T, ty, f"Поставка: {st}", pr(sprobs[s_][st]))
                node("terminal", X_T, ty)
                ax.text(X_T + 0.25, ty, v(g.nodes[f"{fnode}|{st}"]["value"]), ha="left", va="center")
    ax.set_xlim(-0.6, X_T + 1.2)
    ax.set_ylim(min(ys.values()) - 0.7, term_y[0] + 0.6)
    fig.tight_layout(pad=0.2)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg, fx, key_rate, key_date, alts, ranks = load()
    vendors = build_vendors(cfg, alts, ranks)
    strat = cfg["strategies"]
    names = {s: v["name"] for s, v in strat.items()}
    pr, sup = cfg["project"], cfg["supply"]
    base_cost = sum(vendors[(c, v)]["unit_cost"] * sh for c, m in mix_for(strat["С1"]).items() for v, sh in m.items())
    params = {**pr, "delay_days": sup["delay_days"], "fail_days": sup["fail_days"],
              "urgency_premium": sup["urgency_premium"], "key_rate": key_rate,
              "key_rate_divisor": cfg["penalty"]["key_rate_divisor"],
              "contract_value": pr["contract_multiplier"] * base_cost * pr["n_complexes"]}
    an = cfg["analysis"]
    sim = risk.Simulator(vendors, fx, params, an["mc_samples"], an["seed"])
    beta = an["risk_aversion"]

    # 1. Оптимальная доля лидера в стратегии диверсификации (scipy.optimize.minimize_scalar)
    def objective(x, b):
        c = sim.run(mix_for(strat["С3"], x), "on_delivery")["cost"]
        return (1 - b) * c.mean() + b * risk.cvar(c, 0.95)
    lo, hi = an["share_bounds"]
    opt = {}
    for label, b in (("risk_neutral", 0.0), ("risk_averse", beta)):
        r = minimize_scalar(objective, bounds=(lo, hi), args=(b,), method="bounded", options={"xatol": 1e-3})
        opt[label] = {"beta": b, "x": float(r.x), "objective": float(r.fun)}

    # 2. Прогон стратегий
    runs, rows = {}, []
    for s, spec in strat.items():
        res = sim.run(mix_for(spec), spec["mode"])
        runs[s] = res
        m = metrics(res)
        m.update({"strategy": s, "name": spec["name"], "mode": spec["mode"],
                  "objective_beta": (1 - beta) * m["mean"] + beta * m["cvar95"],
                  **{f"p_{st}": float((res["state"] == i).mean()) for i, st in enumerate(risk.STATES)}})
        rows.append(m)
    summary_df = pd.DataFrame(rows).set_index("strategy")

    # 3. Дерево решений (networkx): вероятности состояний - аналитически, затраты в листьях - условные средние МК
    sprobs = {s: risk.state_probs(mix_for(spec), vendors) for s, spec in strat.items()}
    leaf, payoff = {}, {}
    for s in strat:
        res = runs[s]
        for fi, fname in enumerate(fx["scenario"]):
            for si, st in enumerate(risk.STATES):
                mask = (res["fx"] == fi) & (res["state"] == si)
                val = res["cost"][mask].mean() if mask.any() else np.nan
                leaf[(s, fname, st)] = val
                payoff.setdefault(s, {})[f"{fname} / {st}"] = val
    g = risk.build_tree(list(strat), fx, sprobs, leaf)
    best, best_value = risk.rollback(g)
    tree_rows = [{"node": n, **{k: v for k, v in d.items()}} for n, d in g.nodes(data=True)]
    pd.DataFrame(tree_rows).to_csv(OUT / "tree_nodes.csv", index=False, float_format="%.0f")

    # 4. Критерии принятия решений по матрице «стратегия × состояние природы»
    payoff_df = pd.DataFrame(payoff).T
    state_p = pd.Series({f"{f.scenario} / {st}": f.prob * np.mean([sprobs[s][st] for s in strat])
                         for f in fx.itertuples() for st in risk.STATES})
    crit = risk.criteria(payoff_df, state_p, an["hurwicz_pessimism"])
    crit["Байес (ожидание)"] = [g.nodes[s]["value"] for s in crit.index]   # ожидание - из свёртки дерева
    crit["Риск-критерий J (β)"] = summary_df["objective_beta"]
    winners = {col: crit[col].idxmin() for col in crit.columns}

    # 5. Пороги (scipy.optimize.brentq)
    def diff_prob(k):
        a = sim.run(mix_for(strat["С1"]), "on_delivery", prob_scale=k)["cost"].mean()
        b = sim.run(mix_for(strat["С4"]), "advance", prob_scale=k)["cost"].mean()
        return a - b
    def diff_rate(r):
        a = sim.run(mix_for(strat["С1"]), "on_delivery", key_rate=r)["cost"].mean()
        b = sim.run(mix_for(strat["С4"]), "advance", key_rate=r)["cost"].mean()
        return a - b
    thresholds = {}
    k_max = min(1 / (v["probs"]["delay"] + v["probs"]["fail"])
                for c, m in mix_for(strat["С1"]).items() for v_name, sh in m.items() for v in [vendors[(c, v_name)]])
    try:
        thresholds["prob_scale_C1_eq_C4"] = float(brentq(diff_prob, 0.05, k_max * 0.999, xtol=1e-3))
    except ValueError:
        thresholds["prob_scale_C1_eq_C4"] = None
    try:
        thresholds["key_rate_C1_eq_C4"] = float(brentq(diff_rate, 0.0, 0.40, xtol=1e-4))
    except ValueError:
        thresholds["key_rate_C1_eq_C4"] = None

    # 6. Сохранение
    fx.to_csv(OUT / "fx_scenarios.csv", index=False, float_format="%.4f")
    summary_df.to_csv(OUT / "strategies.csv", float_format="%.0f")
    payoff_df.to_csv(OUT / "payoff_matrix.csv", float_format="%.0f")
    crit.to_csv(OUT / "criteria.csv", float_format="%.0f")
    pd.DataFrame([{"category": c, "vendor": v, **{k: d[k] for k in ("unit_cost", "exposure", "status", "repl")},
                   **d["probs"]} for (c, v), d in vendors.items()]).to_csv(OUT / "vendors_params.csv", index=False)
    draw_tree(g, fx, sprobs, list(strat), names, best, OUT / "decision_tree.png")
    summary = {
        "key_rate": key_rate, "key_rate_date": key_date, "contract_value": params["contract_value"],
        "fx": fx.to_dict("records"), "tree_best": best, "tree_best_value": best_value,
        "tree_values": {s: g.nodes[s]["value"] for s in strat}, "winners": winners,
        "optimization": opt, "thresholds": thresholds,
        "state_probs": sprobs, "strategies": summary_df.reset_index().to_dict("records"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("Сценарии курса:\n", fx.to_string(index=False))
    print(f"Ключевая ставка {key_rate:.2%} на {key_date}; цена договора {params['contract_value'] / 1e6:.1f} млн ₽")
    print(summary_df[["name", "mean", "std", "p95", "cvar95", "objective_beta", "p_в срок", "p_задержка", "p_срыв"]]
          .to_string(float_format=lambda v: f"{v:,.3f}" if abs(v) < 2 else f"{v / 1e6:,.3f}М"))
    print("Дерево: лучшая", best, f"{best_value / 1e6:.3f} млн;", {s: round(g.nodes[s]["value"] / 1e6, 3) for s in strat})
    print("Аналитические вероятности состояний:", {s: {k: round(v, 3) for k, v in p.items()} for s, p in sprobs.items()})
    print(crit.map(lambda v: round(v / 1e6, 3)).to_string())
    print("Победители по критериям:", winners)
    print("Оптимальная доля лидера:", opt)
    print("Пороги:", thresholds)


if __name__ == "__main__":
    main()
