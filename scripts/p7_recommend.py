"""Практика №7: рекомендательный модуль.

Вход:  результаты практик 2-6 (outputs/p2..p6), config/p5_kb.json, config/p7_recommend.json
Выход: outputs/p7/recommendations_<контекст>.csv, actions_<контекст>.csv, summary.json
Запуск: .venv/bin/python scripts/p7_recommend.py
Модуль можно вызывать из прототипа (практика №8): recommend_for(context_id) -> dict.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import p4_optimize  # noqa: E402
import p5_kb  # noqa: E402
from sppr import kb, recommend as rec  # noqa: E402

OUT = ROOT / "outputs" / "p7"


def load_json(*parts):
    return json.loads(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


def plan_for(admission, scored, utility_from_scored=True, changes=None):
    """План оптимизации практики №4 с допуском базы знаний и полезностями под контекст."""
    d = p4_optimize.load(admission=admission)
    if utility_from_scored:
        best = scored.groupby("category")["score"].transform("max")
        u = dict(zip(zip(scored["category"], scored["vendor"]), scored["score"] / best))
        d["tab"]["utility"] = [u.get((c, v), 0.0) for c, v in zip(d["tab"]["category"], d["tab"]["vendor"])]
    p = p4_optimize.params_from(d["cfg4"], changes)
    r = p4_optimize.run(d["tab"], d["n"], p)
    if r["status"] == "Optimal":
        r["simulation"] = p4_optimize.simulate(d["sim"], r["plan"], d["n"])
        r["binding"] = p4_optimize.binding(r, p, d["n"], p4_optimize.budget_limits(d["tab"], d["n"], p, r))
        return r, None
    return r, p4_optimize.diagnose(d["tab"], d["n"], p)


def recommend_for(context_id, cfg7=None, context=None):
    """context - произвольный контекст ЛПР: {"name", "kb_changes", "weights", "params"} (для прототипа)."""
    cfg7 = cfg7 or load_json("config", "p7_recommend.json")
    ctx = context or cfg7["contexts"][context_id]
    changes = ctx.get("params")
    cfg5 = load_json("config", "p5_kb.json")
    crit_cfg = load_json("config", "ahp_criteria.json")["criteria"]
    models, specs = p5_kb.load_models()
    _, _, _, _, meta, table = p5_kb.run_kb(models, specs, cfg5, ctx["kb_changes"])
    base_w = pd.read_csv(ROOT / "outputs" / "p2" / "criteria_weights.csv").set_index("criterion")["weight"]
    weights = rec.context_weights(base_w, ctx["weights"])
    local = pd.read_csv(ROOT / "outputs" / "p2" / "local_priorities.csv")
    scored = rec.rescore(local, weights, table)
    conf = rec.confidence(scored, weights, cfg7["confidence"]["kappa"], cfg7["confidence"]["samples"])
    attrib = rec.attribution(scored, weights)
    r, diag = plan_for(kb.admission(table), scored, changes=changes)
    plan = r["plan"] if diag is None else pd.DataFrame(columns=["category", "vendor", "complexes"])
    alts = pd.read_csv(ROOT / "data" / "processed" / "alternatives_scored.csv", dtype={"unavailable": str})
    recs = rec.supplier_recommendations(scored, plan, conf, attrib, alts, weights, crit_cfg)
    for cat in meta["expand_suppliers"]:                  # R14: категории без допустимых альтернатив
        recs.loc[len(recs)] = {"category": cat, "recommended": "-", "score": None, "allocation": "-", "backup": None,
                               "confidence": None, "why": "нет допустимых альтернатив (R14)", "note": "",
                               "counterfactual": "расширить перечень поставщиков", "counterfactual_cut": None}

    # сигналы для рекомендаций-действий
    s3 = load_json("outputs", "p3", "summary.json")
    s6 = load_json("outputs", "p6", "summary.json")
    fxf = pd.read_csv(ROOT / "outputs" / "p6" / "fx_forecast.csv", index_col=0)
    wk = cfg7["fx_check_week"]
    risk_gain = s3["tree_values"]["С1"] - s3["tree_values"]["С4"]
    timing = {"holding": s6["timing"][-1]["holding_cost_if_bought_now"]}
    whatif = None
    approval = [v for v, fr in zip(table["vendor"], table["flag_rules"]) if "R10" in str(fr).split(", ")]
    if diag is None and set(approval) & set(plan["vendor"]):
        t2 = table.copy()
        t2.loc[t2["vendor"].isin(approval), ["admissible", "exclusion_rules", "exclusion_reason"]] = [False, "ЛПР", "закупка не согласована"]
        scored2 = rec.rescore(local, weights, t2)
        r2, diag2 = plan_for(kb.admission(t2), scored2, changes=changes)
        if diag2 and "не хватает бюджета" in diag2:
            need = re.search(r"([\d.]+) млн", diag2).group(1).replace(".", ",")
            diag2 = f"план не укладывается в бюджет (нужно {need} млн руб.)"
        whatif = (diag2 if diag2 else
                  f"план без них: полезность {rec.num(r2['utility'], 3)}, ожидаемые затраты {rec.num(r2['cost'] / 1e6)} млн руб.")
    acts = rec.action_recommendations(plan, table, timing, risk_gain, (fxf.lo80.iloc[wk - 1], fxf.hi80.iloc[wk - 1]),
                                      approval_whatif=whatif)
    if meta["expand_suppliers"]:
        acts.insert(0, {"priority": 1, "action": "Расширить перечень поставщиков: " + ", ".join(meta["expand_suppliers"])
                        + " - при заданных требованиях допустимых альтернатив нет", "source": "база знаний R14"})
    return {"context": context_id, "name": ctx["name"], "weights": weights.to_dict(), "recommendations": recs,
            "actions": pd.DataFrame(acts), "plan_status": r["status"], "plan_diag": diag,
            "utility": r.get("utility"), "cost": r.get("cost"), "scored": scored, "plan": plan, "kb_table": table,
            "simulation": r.get("simulation"), "binding": r.get("binding"), "expand_suppliers": meta["expand_suppliers"]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg7 = load_json("config", "p7_recommend.json")
    summary = {}
    for cid in cfg7["contexts"]:
        res = recommend_for(cid, cfg7)
        res["recommendations"].to_csv(OUT / f"recommendations_{cid}.csv", index=False, float_format="%.4f")
        res["actions"].to_csv(OUT / f"actions_{cid}.csv", index=False)
        res["scored"].to_csv(OUT / f"scores_{cid}.csv", index=False, float_format="%.4f")
        summary[cid] = {"name": res["name"], "weights": res["weights"], "plan_status": res["plan_status"],
                        "plan_diag": res["plan_diag"], "utility": res["utility"], "cost": res["cost"],
                        "recommendations": res["recommendations"].to_dict("records"),
                        "actions": res["actions"].to_dict("records")}
        pd.set_option("display.width", 250, "display.max_colwidth", 90)
        print(f"\n=== {res['name']} | план: {res['plan_status']} {res['plan_diag'] or ''} U={res['utility']} cost={res['cost']}")
        print(res["recommendations"][["category", "recommended", "allocation", "backup", "confidence", "why", "counterfactual"]].to_string(index=False))
        print(res["actions"].to_string(index=False))
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
