"""Практика №8: сквозной прогон прототипа по сценариям ЛПР (те же вызовы, что делает интерфейс app/main.py).

Выход: outputs/p8/scenarios.csv, summary.json
Запуск: python scripts/p8_scenarios.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import p7_recommend  # noqa: E402

OUT = ROOT / "outputs" / "p8"
BASE = {"budget": 12.0, "t_max": 12, "share": 60, "load_kw": 1.5, "ats_before": True, "import_sub": False, "risk_mult": 1.0}
SCENARIOS = [
    ("base", "Типовой комплекс", {}),
    ("budget_13", "Бюджет 13 млн руб.", {"budget": 13.0}),
    ("direct_ats", "АВР без ИБП (напрямую)", {"ats_before": False}),
    ("risk_averse", "Осторожный директор", {"risk_mult": 1.5}),
    ("import_substitution", "Импортозамещение", {"import_sub": True}),
]


def context(name, v):
    """Контекст ЛПР - так же, как его собирает интерфейс из элементов управления."""
    return {"name": name,
            "kb_changes": {"rack_load_w": round(v["load_kw"] * 1000), "ats_before_ups": v["ats_before"],
                           "russian_origin_required": v["import_sub"], "max_lead_weeks": v["t_max"]},
            "weights": ({"k3": v["risk_mult"], "k6": v["risk_mult"]} if v["risk_mult"] != 1.0 else {})
                       | ({"k7": 2.0} if v["import_sub"] else {}),
            "params": {"budget_rub": v["budget"] * 1e6, "t_max_weeks": v["t_max"], "max_share": v["share"] / 100}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid, name, changes in SCENARIOS:
        r = p7_recommend.recommend_for("custom", context=context(name, {**BASE, **changes}))
        ok = r["plan_status"] == "Optimal"
        plan = r["plan"]
        rows.append({
            "id": sid, "name": name, "status": "план найден" if ok else "плана нет",
            "utility": r["utility"], "cost": r["cost"],
            "advance_mean": r["simulation"]["advance"]["mean"] if ok else None,
            "advance_cvar95": r["simulation"]["advance"]["cvar95"] if ok else None,
            "plan": "; ".join(f"{c}: " + ", ".join(f"{v} {int(k)}" for v, k in zip(g.sort_values("complexes", ascending=False)["vendor"],
                                                                               g.sort_values("complexes", ascending=False)["complexes"]))
                              for c, g in plan.groupby("category", sort=False)) if ok else "",
            "diag": r["plan_diag"] or "", "binding": ", ".join(r["binding"] or []) if ok else "",
            "first_action": r["actions"]["action"].iloc[0], "n_actions": len(r["actions"]),
            "inadmissible": ", ".join(r["kb_table"].loc[~r["kb_table"]["admissible"], "vendor"]),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "scenarios.csv", index=False, float_format="%.4f")
    (OUT / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    pd.set_option("display.width", 250, "display.max_colwidth", 70)
    print(df[["name", "status", "utility", "cost", "advance_mean", "inadmissible", "diag", "plan"]].to_string(index=False))


if __name__ == "__main__":
    main()
