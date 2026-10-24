"""Практика №2: АНР-модель выбора поставщика.

Вход:  data/processed/alternatives.csv  - сопоставимые позиции по поставщикам (открытые данные)
       config/ahp_criteria.json         - критерии и суждения ЛПР для матрицы парных сравнений
       config/quality_ratings.json      - оценки качества k2 (1-5) с обоснованием
Выход: data/processed/alternatives_scored.csv и файлы в outputs/p2/
Запуск: python3 scripts/p2_ahp.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sppr import ahp, ratings  # noqa: E402

OUT = ROOT / "outputs" / "p2"
CR_LIMIT = 0.10


def load_criteria():
    cfg = json.loads((ROOT / "config" / "ahp_criteria.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in cfg["criteria"]]
    judgments = {(ids.index(a), ids.index(b)): v for a, b, v in cfg["judgments"]}
    return cfg["criteria"], ahp.matrix_from_upper(len(ids), judgments)


def score_alternatives():
    df = pd.read_csv(ROOT / "data" / "processed" / "alternatives.csv", dtype=str).fillna("")
    quality = json.loads((ROOT / "config" / "quality_ratings.json").read_text(encoding="utf-8"))
    adjustments = json.loads((ROOT / "config" / "data_adjustments.json").read_text(encoding="utf-8"))
    rows = []
    for row in df.to_dict("records"):
        adj = adjustments.get(f"{row['category']}|{row['vendor']}")
        if adj:
            row.update({k: str(v) for k, v in adj.items() if k != "why"})
            row["adjustment_why"] = adj["why"]
        lead, lead_why = ratings.lead_time_model(row)
        warr, warr_why = ratings.warranty_model(row)
        k3, k3_why = ratings.reliability(row, lead)
        k6, k6_why = ratings.sanction_risk(row)
        k7, k7_why = ratings.russian_origin(row)
        q = quality[f"{row['category']}|{row['vendor']}"]
        row.update({
            "price_rub": float(row["price_rub"]) if row["price_rub"] else np.nan,
            "lead_time_weeks_model": lead, "lead_time_why": lead_why,
            "warranty_months_model": warr, "warranty_why": warr_why,
            "k2_quality": q["rating"], "k2_why": q["why"],
            "k3_reliability": k3, "k3_why": k3_why,
            "k6_sanction_risk": k6, "k6_why": k6_why,
            "k7_russian_origin": k7, "k7_why": k7_why,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def local_matrix(values, crit):
    if crit["type"] == "numeric":
        return ahp.matrix_from_values(values, crit["direction"])
    return ahp.matrix_from_ratings(values, crit["direction"])


def evaluate_category(group, criteria, weights):
    """Локальные приоритеты по каждому критерию и глобальный приоритет альтернатив категории."""
    local = np.zeros((len(group), len(criteria)))
    consistency_rows = []
    matrices = {}
    for k, crit in enumerate(criteria):
        values = group[crit["column"]].astype(float).to_numpy()
        m = local_matrix(values, crit)
        res = ahp.consistency(m)
        local[:, k] = res["weights"]
        matrices[crit["id"]] = m
        consistency_rows.append({"criterion": crit["id"], "n": res["n"], "lambda_max": res["lambda_max"],
                                 "ci": res["ci"], "cr": res["cr"]})
    glob = ahp.synthesize(weights, local)
    return local, glob, consistency_rows, matrices


def sensitivity(local_by_cat, weights, delta=0.25):
    """Меняем вес каждого критерия на ±delta (с перенормировкой) и смотрим, меняется ли лидер категории."""
    out = []
    for cat, (vendors, local) in local_by_cat.items():
        base_leader = vendors[int(np.argmax(local @ weights))]
        changes = []
        for k in range(len(weights)):
            for sign in (-1, 1):
                w = weights.copy()
                w[k] *= 1 + sign * delta
                w /= w.sum()
                leader = vendors[int(np.argmax(local @ w))]
                if leader != base_leader:
                    changes.append(f"k{k + 1}{'+' if sign > 0 else '-'}{int(delta * 100)}% -> {leader}")
        out.append({"category": cat, "leader": base_leader, "stable": not changes, "changes": "; ".join(changes)})
    return pd.DataFrame(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    criteria, A = load_criteria()
    crit_res = ahp.consistency(A)
    weights = crit_res["weights"]
    ids = [c["id"] for c in criteria]
    pd.DataFrame(A, index=ids, columns=ids).to_csv(OUT / "criteria_matrix.csv", float_format="%.4f")
    pd.DataFrame({"criterion": ids, "name": [c["name"] for c in criteria], "weight": weights,
                  "weight_geomean": ahp.geometric_mean_weights(A)}).to_csv(OUT / "criteria_weights.csv", index=False, float_format="%.4f")

    df = score_alternatives()
    if df["price_rub"].isna().any():
        missing = df.loc[df["price_rub"].isna(), ["category", "vendor"]].values.tolist()
        raise SystemExit(f"нет цены у альтернатив: {missing} - нужно решение (исключить или оценить)")
    df.to_csv(ROOT / "data" / "processed" / "alternatives_scored.csv", index=False)

    results, cons, local_rows, local_by_cat = [], [], [], {}
    for cat, group in df.groupby("category", sort=False):
        group = group.reset_index(drop=True)
        local, glob, cons_rows, _ = evaluate_category(group, criteria, weights)
        vendors = group["vendor"].tolist()
        local_by_cat[cat] = (vendors, local)
        order = np.argsort(-glob)
        for rank, i in enumerate(order, start=1):
            results.append({"category": cat, "rank": rank, "vendor": vendors[i], "model": group.loc[i, "model"],
                            "global_priority": glob[i]})
        for i, v in enumerate(vendors):
            local_rows.append({"category": cat, "vendor": v, **{ids[k]: local[i, k] for k in range(len(ids))}})
        for r in cons_rows:
            cons.append({"category": cat, **r})

    res_df, cons_df = pd.DataFrame(results), pd.DataFrame(cons)
    res_df.to_csv(OUT / "results.csv", index=False, float_format="%.4f")
    pd.DataFrame(local_rows).to_csv(OUT / "local_priorities.csv", index=False, float_format="%.4f")
    cons_df.to_csv(OUT / "consistency.csv", index=False, float_format="%.4f")
    sens = sensitivity(local_by_cat, weights)
    sens.to_csv(OUT / "sensitivity.csv", index=False)

    summary = {
        "criteria": {"lambda_max": crit_res["lambda_max"], "ci": crit_res["ci"], "cr": crit_res["cr"],
                     "weights": dict(zip(ids, map(float, weights)))},
        "alternatives_max_cr": float(cons_df["cr"].max()),
        "matrices_over_limit": cons_df[cons_df["cr"] > CR_LIMIT].to_dict("records"),
        "leaders": res_df[res_df["rank"] == 1][["category", "vendor", "global_priority"]].to_dict("records"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Критерии: λmax={crit_res['lambda_max']:.4f}  ИС={crit_res['ci']:.4f}  ОС={crit_res['cr']:.4f}")
    for i, c in enumerate(criteria):
        print(f"  {c['id']} {c['name']:32s} {weights[i]:.3f}")
    print(f"Макс. ОС по матрицам альтернатив: {cons_df['cr'].max():.4f} (порог {CR_LIMIT})")
    print(res_df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(sens.to_string(index=False))


if __name__ == "__main__":
    main()
