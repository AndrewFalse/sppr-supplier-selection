"""Рекомендательный модуль (практика №7).

Гибридная схема: база знаний отбирает допустимых кандидатов (практика №5) -> ранжирование по полезности
АНР с весами, скорректированными под контекст ЛПР (практика №2) -> распределение объёма оптимизатором
(практика №4) -> рекомендации-действия по правилам из сигналов рисков, базы знаний и прогноза (практики №3, №5, №6).
Каждая рекомендация сопровождается объяснением: вклад критериев, уверенность (устойчивость к разбросу весов),
контрфактический сценарий (что должно измениться, чтобы рекомендация сменилась).
"""
import numpy as np
import pandas as pd

from sppr import ahp

def num(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


CRIT_NAMES = {"k1": "стоимость", "k2": "качество", "k3": "надёжность", "k4": "срок", "k5": "гарантия",
              "k6": "санкционный риск", "k7": "российское происхождение"}


def context_weights(base_weights, multipliers=None):
    """Веса АНР под контекст: множители по критериям (например, осторожный ЛПР - k3, k6 x1,5), затем нормировка."""
    w = pd.Series(base_weights, dtype=float).copy()
    for k, m in (multipliers or {}).items():
        w[k] *= m
    return w / w.sum()


def rescore(local, weights, admissible):
    """Полезность допустимых альтернатив: локальные приоритеты перенормируются внутри допустимых
    (матрицы сравнения строились по отношениям значений, поэтому отношения приоритетов сохраняются)."""
    crit = list(weights.index)
    df = local.merge(admissible[["category", "vendor", "admissible"]], on=["category", "vendor"])
    df = df[df["admissible"]].copy()
    df[crit] = df.groupby("category")[crit].transform(lambda s: s / s.sum())
    df["score"] = df[crit].values @ weights.values
    df["rank"] = df.groupby("category")["score"].rank(ascending=False, method="first").astype(int)
    return df.sort_values(["category", "rank"])


def confidence(scored, weights, kappa=50, n=3000, seed=0):
    """Доля случайных наборов весов (распределение Дирихле вокруг весов ЛПР), при которых лидер категории
    остаётся первым: чем выше, тем устойчивее рекомендация к неточности суждений."""
    rng = np.random.default_rng(seed)
    crit = list(weights.index)
    W = rng.dirichlet(kappa * weights.values, size=n)
    out = {}
    for cat, g in scored.groupby("category"):
        if len(g) == 1:
            out[cat] = 1.0
            continue
        leader = g.loc[g["rank"] == 1, "vendor"].iloc[0]
        wins = np.argmax(g[crit].values @ W.T, axis=0)
        out[cat] = float(np.mean(g["vendor"].values[wins] == leader))
    return out


def attribution(scored, weights):
    """Вклад критерия в преимущество лидера: w_k * (p_k(лидер) - среднее p_k по допустимым альтернативам)."""
    crit = list(weights.index)
    rows = []
    for cat, g in scored.groupby("category"):
        lead = g[g["rank"] == 1].iloc[0]
        contrib = {k: weights[k] * (lead[k] - g[k].mean()) for k in crit}
        rows.append({"category": cat, "vendor": lead["vendor"], **contrib})
    return pd.DataFrame(rows)


def explain_attribution(row, top=2, single=False):
    if single:
        return "единственная допустимая альтернатива"
    items = sorted(((k, v) for k, v in row.items() if k in CRIT_NAMES), key=lambda kv: -kv[1])
    plus = [CRIT_NAMES[k] for k, v in items[:top] if v > 0.002]
    minus = [CRIT_NAMES[k] for k, v in items[::-1][:1] if v < -0.002]
    text = "сильнее всего: " + ", ".join(plus) if plus else "преимущество по сумме критериев"
    if minus:
        text += "; слабее: " + minus[0]
    return text


def price_counterfactual(category, scored, alts, weights, crit_cfg, max_cut=0.6):
    """Насколько должен подешеветь второй по рангу поставщик, чтобы догнать лидера (пересчёт
    локальных приоритетов по цене тем же методом, что в практике №2). None - если ценой не догнать."""
    g = scored[scored["category"] == category]
    if len(g) < 2:
        return None
    leader, runner = g.iloc[0], g.iloc[1]
    vendors = list(g["vendor"])
    prices = alts.set_index(["category", "vendor"]).loc[[(category, v) for v in vendors], "price_rub"].astype(float).values
    k1 = next(c for c in crit_cfg if c["id"] == "k1")
    others = g[[k for k in weights.index if k != "k1"]].values @ weights.drop("k1").values

    def gap(cut):
        p = prices.copy()
        p[1] *= (1 - cut)
        pr, _ = ahp.priority_vector(ahp.matrix_from_values(p, k1["direction"]))
        s = others + weights["k1"] * pr
        return s[1] - s[0]

    if gap(0) >= 0:
        return 0.0
    if gap(max_cut) < 0:
        return None
    lo, hi = 0.0, max_cut
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if gap(mid) >= 0 else (mid, hi)
    return hi


def supplier_recommendations(scored, plan, conf, attrib, alts, weights, crit_cfg):
    """Рекомендации по категориям: кого выбрать, сколько (по плану оптимизации), резерв, уверенность, объяснение."""
    rows = []
    for cat, g in scored.groupby("category", sort=False):
        lead = g.iloc[0]
        backup = g.iloc[1]["vendor"] if len(g) > 1 else None
        alloc = plan[plan["category"] == cat].sort_values("complexes", ascending=False)
        cf = price_counterfactual(cat, scored, alts, weights, crit_cfg)
        att = attrib[attrib["category"] == cat].iloc[0].to_dict()
        major = alloc["vendor"].iloc[0] if len(alloc) else None
        note = (f"объём смещён к {major}: лидер дороже, бюджет ограничивает план" if major and major != lead["vendor"] else "")
        rows.append({
            "category": cat, "recommended": lead["vendor"], "score": float(lead["score"]),
            "allocation": ", ".join(f"{v} {int(c)}" for v, c in zip(alloc["vendor"], alloc["complexes"])),
            "backup": backup, "confidence": conf.get(cat, 1.0), "why": explain_attribution(att, single=len(g) == 1), "note": note,
            "counterfactual": ("нет альтернатив" if backup is None else
                               f"{backup} догонит лидера при снижении цены на {num(cf * 100, 0)} %" if cf is not None
                               else f"{backup} не догонит лидера даже при снижении цены на 60 %"),
            "counterfactual_cut": cf,
        })
    return pd.DataFrame(rows)


def action_recommendations(plan, kb_table, timing, risk_gain, fx_band, approval_whatif=None):
    """Рекомендации-действия по правилам. Возвращает список словарей с приоритетом и обоснованием."""
    in_plan = set(plan["vendor"])
    acts = []
    flags = kb_table.fillna("")

    def who(rule):
        return [v for v, fr in zip(flags["vendor"], flags["flag_rules"]) if rule in str(fr).split(", ") and v in in_plan]

    hp = who("R10")
    if hp:
        n = int(plan[plan["vendor"].isin(hp)]["complexes"].sum())
        txt = f"Согласовать закупку {', '.join(hp)} ({n} комплексов): вендор исключён из перечня параллельного импорта"
        if approval_whatif:
            txt += f"; без согласования {approval_whatif}"
        acts.append({"priority": 1, "action": txt, "source": "база знаний R9-R10, оптимизация"})
    acts.append({"priority": 2 if risk_gain > 0 else 4,
                 "action": (f"Закупить заранее: ожидаемая экономия {num(risk_gain / 1e6)} млн руб. с учётом хранения; "
                            f"курс по прогнозу не растёт, выгода - от снижения риска сроков"),
                 "source": "риски (практика 3), прогноз (практика 6)"})
    q = who("R12")
    if q:
        acts.append({"priority": 2, "action": f"Запросить коммерческие предложения у {', '.join(q)}: цена не подтверждена",
                     "source": "база знаний R12"})
    z = who("R11")
    if z:
        acts.append({"priority": 3, "action": f"Заложить резерв ЗИП для {', '.join(z)}: гарантия только продавца при параллельном импорте",
                     "source": "база знаний R11"})
    b = who("R3a")
    if b:
        acts.append({"priority": 3, "action": f"Устанавливать {', '.join(b)} только перед ИБП (переключение дольше 20 мс)",
                     "source": "база знаний R3a"})
    acts.append({"priority": 3, "action": (f"Пересмотреть решение, если курс через 4 недели выйдет за {num(fx_band[0], 1)}-{num(fx_band[1], 1)} руб./долл. "
                                           f"(интервал 80 % прогноза)"),
                 "source": "прогноз (практика 6)"})
    return sorted(acts, key=lambda a: a["priority"])
