"""Практика №4: оптимизационная модель закупки (PuLP + CBC).

Вход:  config/p4_optimization.json, config/p3_risk.json, outputs/p2/results.csv,
       outputs/p3/vendors_params.csv, outputs/p3/summary.json, data/processed/alternatives_scored.csv
Выход: outputs/p4/*.csv, summary.json, model_base.lp, pareto.png
Запуск: .venv/bin/python scripts/p4_optimize.py
"""
import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.ticker
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import p3_risk  # noqa: E402  загрузка данных и параметров практики №3
from sppr import optimize as opt, risk  # noqa: E402

OUT = ROOT / "outputs" / "p4"
PARAM_KEYS = ("budget_rub", "t_max_weeks", "max_share", "max_suppliers", "min_lot", "high_risk_k6", "max_high_risk_share")


def load(admission=None):
    """Все входы модели. admission - допуск альтернатив (например, вывод базы знаний практики №5)."""
    cfg3, fx, key_rate, key_date, alts, ranks = p3_risk.load()
    cfg4 = json.loads((ROOT / "config" / "p4_optimization.json").read_text(encoding="utf-8"))
    summ3 = json.loads((ROOT / "outputs" / "p3" / "summary.json").read_text(encoding="utf-8"))
    vend = pd.read_csv(ROOT / "outputs" / "p3" / "vendors_params.csv")
    n = cfg3["project"]["n_complexes"]
    costs, e_delta, day_cost = opt.expected_unit_costs(
        vend, fx, cfg3["supply"], n, summ3["contract_value"], key_rate,
        cfg3["penalty"]["key_rate_divisor"], cfg3["project"]["crew_cost_per_day"])
    scored = pd.read_csv(ROOT / "data" / "processed" / "alternatives_scored.csv", dtype={"unavailable": str})
    tab = opt.build_table(costs, ranks, scored, admission)
    # имитационная модель практики №3 для проверки найденных планов
    vendors3 = p3_risk.build_vendors(cfg3, alts, ranks)
    pr, sup = cfg3["project"], cfg3["supply"]
    params3 = {**pr, "delay_days": sup["delay_days"], "fail_days": sup["fail_days"],
               "urgency_premium": sup["urgency_premium"], "key_rate": key_rate,
               "key_rate_divisor": cfg3["penalty"]["key_rate_divisor"], "contract_value": summ3["contract_value"]}
    sim = risk.Simulator(vendors3, fx, params3, cfg3["analysis"]["mc_samples"], cfg3["analysis"]["seed"])
    return {"cfg3": cfg3, "cfg4": cfg4, "tab": tab, "n": n, "sim": sim, "e_delta": e_delta, "day_cost": day_cost,
            "key_rate": key_rate}


def params_from(cfg4, changes=None):
    p = {k: cfg4[k] for k in PARAM_KEYS}
    p.update(changes or {})
    return p


def run(tab, n, p, objective="utility"):
    return opt.solve(tab, n, budget=p["budget_rub"], max_share=p["max_share"], max_suppliers=p["max_suppliers"],
                     min_lot=p["min_lot"], t_max=p["t_max_weeks"], max_high_risk_share=p["max_high_risk_share"],
                     high_risk_k6=p["high_risk_k6"], objective=objective)


def simulate(sim, plan, n):
    """Проверка плана имитацией практики №3: оплата при поставке и опережающая закупка."""
    mix = opt.plan_to_mix(plan, n)
    out = {}
    for mode in ("on_delivery", "advance"):
        c = sim.run(mix, mode)["cost"]
        out[mode] = {"mean": float(c.mean()), "cvar95": risk.cvar(c, 0.95), "std": float(c.std())}
    return out


def plan_str(plan):
    return "; ".join(f"{p.vendor} {p.complexes}" for p in plan.itertuples())


def binding(res, p, n, limited_by_budget=False):
    """Какие ограничения определяют найденный план."""
    b = []
    if limited_by_budget:
        b.append("бюджет")
    if res["slack"].get("high_risk") is not None and res["slack"]["high_risk"] < 1:
        b.append("доля высокого риска")
    caps = res["categories"]
    if any(caps[r.category]["share_cap"] < 1 and r.complexes == int(np.floor(caps[r.category]["share_cap"] * n + 1e-9))
           for r in res["plan"].itertuples()):
        b.append("доля поставщика 60 %")
    single = [c for c, v in caps.items() if v["single"]]
    if single:
        b.append("один допустимый поставщик: " + ", ".join(single))
    return b


def diagnose(tab, n, p):
    """Причина несовместности: нет допустимых поставщиков или не хватает бюджета."""
    r_nb = run(tab, n, {**p, "budget_rub": None}, objective="cost")
    if r_nb["status"] == "Optimal":
        return f"не хватает бюджета: минимальные ожидаемые затраты {r_nb['cost'] / 1e6:.2f} млн руб."
    if r_nb.get("empty_categories"):
        return "нет допустимых поставщиков: " + ", ".join(r_nb["empty_categories"])
    return "ограничения несовместны"


def budget_limits(tab, n, p, res):
    """Бюджет ограничивает план, если без него достижима большая полезность."""
    if p["budget_rub"] is None:
        return False
    r_nb = run(tab, n, {**p, "budget_rub": None})
    return r_nb["status"] == "Optimal" and r_nb["utility"] > res["utility"] + 1e-9


def draw_pareto(front, base, path):
    """Граница Парето «ожидаемые затраты - полезность» в стиле отчётов ПО (ч/б, без заголовка)."""
    plt.rcParams.update({"font.family": ["Arial", "DejaVu Sans"], "font.size": 8})
    fig, ax = plt.subplots(figsize=(6.0, 3.2), dpi=300)
    x, yv = front["cost"] / 1e6, front["utility"]
    ax.step(x, yv, where="post", color="black", lw=0.8)
    ax.plot(x, yv, "o", ms=3.5, mfc="white", mec="black", mew=0.8)
    ax.plot([base["cost"] / 1e6], [base["utility"]], "s", ms=5, mfc="black", mec="black")
    ax.annotate("план при бюджете\n12 млн руб.", (base["cost"] / 1e6, base["utility"]), xytext=(8, -22),
                textcoords="offset points", fontsize=7)
    comma = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.2f}".replace(".", ","))
    ax.xaxis.set_major_formatter(comma)
    ax.yaxis.set_major_formatter(comma)
    ax.set_xlabel("Ожидаемые затраты с учётом риска, млн руб.")
    ax.set_ylabel("Полезность плана U")
    ax.grid(True, color="#d0d0d0", lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = load()
    tab, n, cfg4, sim = d["tab"], d["n"], d["cfg4"], d["sim"]
    tab.to_csv(OUT / "alternatives_table.csv", index=False, float_format="%.4f")
    base_p = params_from(cfg4)

    # 1. Базовое решение
    base = run(tab, n, base_p)
    if base["status"] != "Optimal":
        raise SystemExit(f"базовая задача не решена: {base['status']}")
    base["problem"].writeLP(str(OUT / "model_base.lp"))
    base_plan = base["plan"].merge(tab[["category", "vendor", "unit_cost", "exp_cost"]].rename(
        columns={"exp_cost": "exp_unit_cost"}), on=["category", "vendor"])
    base_plan.to_csv(OUT / "plan_base.csv", index=False, float_format="%.2f")

    # 2. Сценарии (чувствительность к параметрам ЛПР)
    rows = []
    for sc in cfg4["scenarios"]:
        p = params_from(cfg4, sc["changes"])
        r = run(tab, n, p)
        row = {"id": sc["id"], "name": sc["name"], "status": r["status"]}
        if r["status"] == "Optimal":
            mc = simulate(sim, r["plan"], n)
            row.update({"utility": r["utility"], "cost": r["cost"], "base_cost": r["base_cost"], "plan": plan_str(r["plan"]),
                        "binding": ", ".join(binding(r, p, n, budget_limits(tab, n, p, r))),
                        "mc_mean": mc["on_delivery"]["mean"],
                        "mc_cvar95": mc["on_delivery"]["cvar95"], "mc_mean_advance": mc["advance"]["mean"],
                        "mc_cvar95_advance": mc["advance"]["cvar95"]})
        else:
            row["binding"] = diagnose(tab, n, p)
        rows.append(row)
    scen = pd.DataFrame(rows)
    scen.to_csv(OUT / "scenarios.csv", index=False, float_format="%.4f")

    # 3. Граница Парето (ε-ограничение по бюджету)
    p_nb = params_from(cfg4, {"budget_rub": None})
    lo = run(tab, n, p_nb, objective="cost")["cost"]
    hi = run(tab, n, p_nb)["cost"]
    step = cfg4["pareto_step_rub"]
    budgets = list(np.arange(np.ceil(lo / step) * step, hi + step, step)) + [hi + 1]
    front = opt.pareto(tab, n, budgets, max_share=base_p["max_share"], max_suppliers=base_p["max_suppliers"],
                       min_lot=base_p["min_lot"], t_max=base_p["t_max_weeks"],
                       max_high_risk_share=base_p["max_high_risk_share"], high_risk_k6=base_p["high_risk_k6"])
    front.to_csv(OUT / "pareto.csv", index=False, float_format="%.4f")
    draw_pareto(front, base, OUT / "pareto.png")

    base_mc = simulate(sim, base["plan"], n)
    summary = {
        "n_complexes": n, "expected_fx_change": d["e_delta"], "delay_day_cost_per_complex": d["day_cost"],
        "params": base_p, "status": base["status"], "gap_rel": base["gap_rel"], "solve_time_s": base["solve_time"],
        "utility": base["utility"], "cost": base["cost"], "base_cost": base["base_cost"], "slack": base["slack"],
        "binding": binding(base, base_p, n, budget_limits(tab, n, base_p, base)), "plan": base_plan.to_dict("records"),
        "simulation": base_mc,
        "n_variables": len(base["problem"].variables()), "n_constraints": len(base["problem"].constraints()),
        "pareto_points": len(front), "min_cost": lo, "max_utility_cost": hi,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    pd.set_option("display.width", 220)
    print(f"Базовый план: U = {base['utility']:.4f}, ожидаемые затраты {base['cost'] / 1e6:.3f} млн, "
          f"по текущим ценам {base['base_cost'] / 1e6:.3f} млн; переменных {summary['n_variables']}, "
          f"ограничений {summary['n_constraints']}, разрыв {base['gap_rel']}")
    print(base_plan[["category", "vendor", "complexes", "share", "exp_cost"]].to_string(index=False))
    print("Активные ограничения:", summary["binding"], "| запас:", base["slack"])
    print("Имитация (практика №3):", {k: {m: round(v / 1e6, 3) for m, v in x.items()} for k, x in base_mc.items()})
    print(scen[["id", "status", "utility", "cost", "mc_mean", "mc_cvar95", "binding", "plan"]].to_string(
        index=False, float_format=lambda v: f"{v:.4f}" if abs(v) < 2 else f"{v / 1e6:.3f}"))
    print(front.to_string(index=False, float_format=lambda v: f"{v:.4f}" if abs(v) < 2 else f"{v / 1e6:.3f}"))


if __name__ == "__main__":
    main()
