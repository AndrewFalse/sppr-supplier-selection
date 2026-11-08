"""Оптимизационная модель закупки (практика №4).

Смешанное целочисленное линейное программирование (СЦЛП), PuLP + решатель CBC.
Переменные: y[c, j] - сколько комплексов (из N) комплектуется в категории c у поставщика j (целое);
            z[c, j] - выбран ли поставщик j в категории c (0/1).
Цель: максимум полезности плана U = Σ r[c, j] · y[c, j] / (N · |C|), где r - приоритет АНР,
      отнесённый к лидеру категории (практика №2).
Ограничения: спрос, бюджет по ожидаемым затратам с учётом риска (практика №3), доля одного
      поставщика, число поставщиков в категории, минимальная партия, срок поставки, допуск,
      доля оборудования с высоким санкционным риском.
"""
import math

import numpy as np
import pandas as pd
import pulp

CAT_CODES = {"ИБП": "ups", "АВР": "ats", "КВМ": "kvm", "Коммутаторы": "sw", "ПК и серверы": "pc"}


def expected_unit_costs(vendors, fx, supply, n_complexes, contract_value, key_rate, key_rate_divisor, crew_cost_per_day):
    """Ожидаемые затраты на один комплекс-эквивалент у поставщика (линейная оценка по параметрам практики №3):
    закупка с учётом ожидаемого изменения курса + ожидаемая доплата за замену при срыве
    + ожидаемые пени и простой бригады за дни задержки (консервативно: задержки категорий суммируются)."""
    e_delta = float((fx["prob"] * fx["delta"]).sum() / fx["prob"].sum())
    day_cost = contract_value / n_complexes * key_rate / key_rate_divisor + crew_cost_per_day / n_complexes
    rows = []
    for r in vendors.itertuples():
        base = r.unit_cost * (1 + r.exposure * e_delta)
        rep = vendors[(vendors.category == r.category) & (vendors.vendor == r.repl)].iloc[0]
        repl = rep.unit_cost * (1 + supply["urgency_premium"]) * (1 + rep.exposure * e_delta)
        replacement = r.fail * (repl - base)
        days = r.delay * supply["delay_days"] + r.fail * supply["fail_days"]
        rows.append({"category": r.category, "vendor": r.vendor, "unit_cost": r.unit_cost,
                     "fx_part": base - r.unit_cost, "replacement_part": replacement,
                     "delay_part": days * day_cost, "exp_cost": base + replacement + days * day_cost})
    return pd.DataFrame(rows), e_delta, day_cost


def build_table(costs, ahp_results, scored, admission=None):
    """Сводная таблица альтернатив: затраты, полезность r (АНР, относительно лидера категории),
    срок, санкционный риск, допуск. admission: DataFrame(category, vendor, admissible, reason) - если
    задан (например, вывод базы знаний), заменяет допуск по умолчанию."""
    tab = costs.merge(ahp_results[["category", "vendor", "global_priority"]], on=["category", "vendor"])
    tab["utility"] = tab["global_priority"] / tab.groupby("category")["global_priority"].transform("max")
    sc = scored[["category", "vendor", "lead_time_weeks_model", "k6_sanction_risk", "unavailable"]].copy()
    tab = tab.merge(sc, on=["category", "vendor"])
    tab = tab.rename(columns={"lead_time_weeks_model": "lead_weeks", "k6_sanction_risk": "k6"})
    if admission is None:
        tab["admissible"] = tab["unavailable"].astype(str).str.lower() != "yes"
        tab["reason"] = np.where(tab["admissible"], "", "товар фактически недоступен у продавцов")
    else:
        tab = tab.merge(admission[["category", "vendor", "admissible", "reason"]], on=["category", "vendor"], how="left")
        tab["admissible"] = tab["admissible"].fillna(False).astype(bool)
        tab["reason"] = tab["reason"].fillna("нет вывода базы знаний")
    return tab.drop(columns=["unavailable"]).reset_index(drop=True)


def solve(tab, n, budget=None, max_share=0.6, max_suppliers=2, min_lot=2, t_max=None,
          max_high_risk_share=None, high_risk_k6=4, objective="utility"):
    """Решает задачу. objective: "utility" - максимум полезности (при равенстве - дешевле),
    "cost" - минимум ожидаемых затрат (при равенстве - полезнее). Возвращает dict с планом."""
    cats = list(dict.fromkeys(tab["category"]))
    sense = pulp.LpMaximize if objective == "utility" else pulp.LpMinimize
    prob = pulp.LpProblem("procurement", sense)
    codes = {c: CAT_CODES.get(c, f"c{k}") for k, c in enumerate(cats)}   # латинские коды для имён в модели
    y, z, ok = {}, {}, {}
    for i, r in tab.iterrows():
        allowed = bool(r["admissible"]) and (t_max is None or r["lead_weeks"] <= t_max)
        ok[i] = allowed
        code = f"{codes[r['category']]}_{i}"
        y[i] = prob.add_variable(f"y_{code}", 0, n if allowed else 0, pulp.LpInteger)
        z[i] = prob.add_variable(f"z_{code}", 0, 1 if allowed else 0, pulp.LpBinary)
    # целевая функция в удобном масштабе: сумма r·y (полезность U = это / (N·|C|)) и затраты в тыс. руб.
    util_sum = pulp.lpSum(round(float(tab.at[i, "utility"]), 6) * y[i] for i in y)
    cost = pulp.lpSum(float(tab.at[i, "exp_cost"]) * y[i] for i in y)
    cost_k = pulp.lpSum(round(float(tab.at[i, "exp_cost"]) / 1000, 3) * y[i] for i in y)
    if objective == "utility":
        prob += 1000 * util_sum - 1e-4 * cost_k   # лексикографически: полезность, затем затраты
    else:
        prob += cost_k - 1e-4 * util_sum          # затраты, затем полезность
    caps = {}
    for c in cats:
        idx = list(tab.index[tab["category"] == c])
        n_ok = sum(ok[i] for i in idx)
        share = max_share if n_ok >= 2 else 1.0  # единственный допустимый поставщик - ограничение доли снимается
        caps[c] = {"admissible": n_ok, "share_cap": share, "single": n_ok == 1}
        code = codes[c]
        prob += pulp.lpSum(y[i] for i in idx) == n, f"demand_{code}"
        prob += pulp.lpSum(z[i] for i in idx) <= max_suppliers, f"suppliers_{code}"
        for i in idx:
            prob += y[i] <= math.floor(share * n + 1e-9) * z[i], f"share_{code}_{i}"
            prob += y[i] >= min_lot * z[i], f"lot_{code}_{i}"
    if budget is not None:
        prob += cost <= budget, "budget"
    if max_high_risk_share is not None:
        risky = [i for i in y if tab.at[i, "k6"] >= high_risk_k6]
        prob += pulp.lpSum(y[i] for i in risky) <= max_high_risk_share * n * len(cats), "high_risk"
    res = prob.solve(pulp.COIN_CMD(msg=False, gapRel=0.0, gapAbs=1e-9))
    gap = getattr(res, "gap_rel", None)
    proven = res.status == pulp.LpSolveStatus.Optimal or (
        bool(getattr(res, "has_solution", False)) and gap is not None and abs(gap) <= 1e-6)
    status = "Optimal" if proven else str(getattr(res, "status_str", res.status))
    out = {"status": status, "categories": caps, "problem": prob, "gap_rel": gap,
           "solver_status": str(getattr(res, "solver_status", "")), "solve_time": getattr(res, "time", None)}
    if status != "Optimal":
        out["empty_categories"] = [c for c, v in caps.items() if v["admissible"] == 0]
        return out
    plan = tab[["category", "vendor"]].copy()
    plan["complexes"] = [int(round(y[i].value() or 0)) for i in tab.index]
    plan["share"] = plan["complexes"] / n
    plan["exp_cost"] = plan["complexes"] * tab["exp_cost"]
    plan["utility_contrib"] = plan["complexes"] * tab["utility"] / (n * len(cats))
    out["plan"] = plan[plan["complexes"] > 0].reset_index(drop=True)
    out["utility"] = float(plan["utility_contrib"].sum())
    out["cost"] = float(plan["exp_cost"].sum())
    out["base_cost"] = float((plan["complexes"] * tab["unit_cost"]).sum())
    slack = {}
    for con in prob.constraints():
        if con.name in ("budget", "high_risk"):
            slack[con.name] = float(-con.value()) if con.value() is not None else None
    out["slack"] = slack
    return out


def pareto(tab, n, budgets, **kw):
    """ε-ограничение по бюджету: для каждого бюджета - максимум полезности. Возвращает недоминируемые точки."""
    pts = []
    for b in budgets:
        r = solve(tab, n, budget=b, **kw)
        if r["status"] == "Optimal":
            pts.append({"budget": b, "cost": r["cost"], "utility": r["utility"],
                        "plan": "; ".join(f"{p.vendor} {p.complexes}" for p in r["plan"].itertuples())})
    df = pd.DataFrame(pts)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["plan"]).sort_values("cost").reset_index(drop=True)
    keep = df["utility"].cummax() == df["utility"]
    return df[keep & ~df["utility"].duplicated()].reset_index(drop=True)


def plan_to_mix(plan, n):
    """План -> доли поставщиков по категориям (для имитационной модели практики №3)."""
    mix = {}
    for p in plan.itertuples():
        mix.setdefault(p.category, {})[p.vendor] = p.complexes / n
    return mix
