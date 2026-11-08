"""Практика №5: база знаний (онтология OWL + продукционные правила) и её связь с оптимизацией практики №4.

Вход:  config/p5_kb.json, data/processed/alternatives_scored.csv, data/processed/technical_specs.csv,
       outputs/p2/results.csv, outputs/p3/vendors_params.csv
Выход: kb/sppr_suppliers.owl - онтология с правилами SWRL (открывается в Protégé);
       kb/sppr_suppliers_inferred.owl - то же с выведенными фактами базового сценария;
       outputs/p5/*.csv, summary.json
Запуск: .venv/bin/python scripts/p5_kb.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import p4_optimize  # noqa: E402  оптимизационная модель практики №4
from sppr import kb  # noqa: E402

OUT = ROOT / "outputs" / "p5"
KB_DIR = ROOT / "kb"


def load_models():
    scored = pd.read_csv(ROOT / "data" / "processed" / "alternatives_scored.csv", dtype={"unavailable": str})
    ranks = pd.read_csv(ROOT / "outputs" / "p2" / "results.csv")[["category", "vendor", "global_priority"]]
    repl = pd.read_csv(ROOT / "outputs" / "p3" / "vendors_params.csv")[["category", "vendor", "repl"]]
    models = (scored.merge(ranks.rename(columns={"global_priority": "ahp_priority"}), on=["category", "vendor"])
              .merge(repl, on=["category", "vendor"], how="left"))
    specs = pd.read_csv(ROOT / "data" / "processed" / "technical_specs.csv", dtype=str)
    return models, specs


def requirements(cfg, changes):
    req = {k: v for k, v in cfg["requirements"].items() if not k.startswith("_")}
    req.update(changes)
    return req


def run_kb(models, specs, cfg, changes):
    req = requirements(cfg, changes)
    onto = kb.build_ontology(models, specs, req, cfg["rules"])
    facts = kb.extract_facts(onto)
    derived, trace, meta = kb.infer(facts, req, cfg["rules"])
    return onto, facts, derived, trace, meta, kb.result_table(facts, derived)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    KB_DIR.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / "config" / "p5_kb.json").read_text(encoding="utf-8"))
    models, specs = load_models()
    pd.DataFrame(cfg["rules"]).to_csv(OUT / "rules.csv", index=False)

    # 1. Базовый сценарий: онтология для Protégé, вывод и объяснения
    onto, facts, derived, trace, meta, table = run_kb(models, specs, cfg, {})
    onto.save(file=str(KB_DIR / "sppr_suppliers.owl"), format="rdfxml")
    st = kb.stats(onto)
    kb.assert_inferred(onto, derived)
    onto.save(file=str(KB_DIR / "sppr_suppliers_inferred.owl"), format="rdfxml")
    table.to_csv(OUT / "inference_base.csv", index=False)
    pd.DataFrame(trace).to_csv(OUT / "trace_base.csv", index=False)

    # 2. Сценарии требований -> допуск -> оптимизация практики №4
    rows, tables = [], {}
    for sc in cfg["scenarios"]:
        _, _, _, tr, mt, tab = run_kb(models, specs, cfg, sc["changes"])
        tables[sc["id"]] = tab
        tab.assign(scenario=sc["id"]).to_csv(OUT / f"inference_{sc['id']}.csv", index=False)
        d = p4_optimize.load(admission=kb.admission(tab))
        p = p4_optimize.params_from(d["cfg4"])
        r = p4_optimize.run(d["tab"], d["n"], p)
        row = {"id": sc["id"], "name": sc["name"],
               "inadmissible": "; ".join(f"{v} ({rl})" for v, rl in zip(tab.loc[~tab.admissible, "vendor"],
                                                                        tab.loc[~tab.admissible, "exclusion_rules"])),
               "n_inadmissible": int((~tab.admissible).sum()), "expand_suppliers": ", ".join(mt["expand_suppliers"]),
               "recommended": ", ".join(tab.loc[tab.recommended, "vendor"]), "status": r["status"]}
        if r["status"] == "Optimal":
            mc = p4_optimize.simulate(d["sim"], r["plan"], d["n"])
            row.update({"utility": r["utility"], "cost": r["cost"], "plan": p4_optimize.plan_str(r["plan"]),
                        "mc_mean_advance": mc["advance"]["mean"], "mc_cvar95_advance": mc["advance"]["cvar95"],
                        "binding": ", ".join(p4_optimize.binding(r, p, d["n"], p4_optimize.budget_limits(d["tab"], d["n"], p, r)))})
        else:
            row["binding"] = p4_optimize.diagnose(d["tab"], d["n"], p)
        rows.append(row)
    scen = pd.DataFrame(rows)
    scen.to_csv(OUT / "scenarios.csv", index=False, float_format="%.4f")

    flags = table[table["flags"] != ""][["category", "vendor", "flags", "flag_rules"]]
    summary = {"ontology": st, "rules_total": len(cfg["rules"]),
               "rules_swrl": sum(1 for r in cfg["rules"] if r.get("swrl")),
               "inference_steps": max(t["step"] for t in trace), "derived_facts": len(trace),
               "base_inadmissible": table.loc[~table.admissible, ["vendor", "exclusion_rules", "exclusion_reason"]].to_dict("records"),
               "base_flags": flags.to_dict("records"), "expand_suppliers_base": meta["expand_suppliers"],
               "recommended_base": table.loc[table.recommended, ["category", "vendor"]].to_dict("records"),
               "scenarios": scen.to_dict("records")}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    pd.set_option("display.width", 230)
    print("Онтология:", st, "| правил:", summary["rules_total"], "(SWRL:", summary["rules_swrl"], ")",
          "| шагов вывода:", summary["inference_steps"], "| выведено фактов:", summary["derived_facts"])
    print(table.to_string(index=False))
    print(scen.drop(columns=["recommended"]).to_string(index=False, float_format=lambda v: f"{v:.4f}" if abs(v) < 2 else f"{v / 1e6:.3f}"))


if __name__ == "__main__":
    main()
