"""Текст практики №4 (оптимизационная модель) для паспорта СППР. Числа берутся из outputs/p4."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "p4"
SHORT = {"HP (HPE Aruba)": "HP Aruba"}


def num(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def mln(x, d=2):
    return num(x / 1e6, d)


def vendors_of(plan_str):
    """'Piton 6; Eltena 4' -> {'Piton': 6, 'Eltena': 4} (имена как в данных)"""
    out = {}
    for part in str(plan_str).split("; "):
        name, cnt = part.rsplit(" ", 1)
        out[name] = int(cnt)
    return out


CAT_SHORT = {"ИБП": "ИБП", "АВР": "АВР", "КВМ": "КВМ", "Коммутаторы": "коммутаторы", "ПК и серверы": "ПК"}


def describe(base, other, cat_of, leaders):
    """Чем план сценария отличается от базового - по категориям."""
    b, o = vendors_of(base), vendors_of(other)
    by_cat = {}
    for v, k in o.items():
        by_cat.setdefault(cat_of[v], {})[v] = k
    base_cat = {}
    for v, k in b.items():
        base_cat.setdefault(cat_of[v], {})[v] = k
    changed = [c for c in by_cat if by_cat[c] != base_cat.get(c)]
    if not changed:
        return "план не меняется"
    only_leader = [c for c in changed if list(by_cat[c]) == [leaders[c]]]
    parts = []
    splits = [c for c in changed if c not in only_leader]
    if only_leader and set(only_leader) | set(splits) == set(by_cat):
        parts.append(f"лидеры по {sum(by_cat[only_leader[0]].values())}")
    elif only_leader:
        parts.append("только лидер: " + ", ".join(CAT_SHORT[c] for c in only_leader))
    for c in changed:
        if c in only_leader:
            continue
        items = sorted(by_cat[c].items(), key=lambda kv: -kv[1])
        parts.append(f"{CAT_SHORT[c]}: " + ", ".join(f"{SHORT.get(v, v)} {k}" for v, k in items))
    return "; ".join(parts)


def swap_text(base, other):
    """Одна замена поставщика: 'HP Aruba вместо MikroTik'."""
    b, o = vendors_of(base), vendors_of(other)
    removed = [v for v in b if v not in o]
    added = [v for v in o if v not in b]
    if len(removed) == 1 and len(added) == 1:
        return f"{SHORT.get(added[0], added[0])} вместо {SHORT.get(removed[0], removed[0])}"
    return describe(base, other, {}, {})


def content():
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    cfg4 = json.loads((ROOT / "config" / "p4_optimization.json").read_text(encoding="utf-8"))
    scen = pd.read_csv(OUT / "scenarios.csv")
    front = pd.read_csv(OUT / "pareto.csv")
    plan = pd.DataFrame(s["plan"])
    p = s["params"]
    n = s["n_complexes"]
    sim = s["simulation"]
    base_row = scen[scen["id"] == "base"].iloc[0]

    # Таблица 7: план по категориям
    t7 = [["Категория", "Поставщики (комплексов из 10)", "Затраты, млн руб."]]
    for cat, g in plan.groupby("category", sort=False):
        g = g.sort_values("complexes", ascending=False)
        t7.append([cat, ", ".join(f"{SHORT.get(v, v)} - {c}" for v, c in zip(g["vendor"], g["complexes"])),
                   mln(g["exp_cost"].sum())])
    t7.append(["Итого", f"U = {num(s['utility'], 3)}", mln(s["cost"])])

    # Таблица 8: сценарии
    alt = pd.read_csv(OUT / "alternatives_table.csv")
    cat_of = dict(zip(alt["vendor"], alt["category"]))
    ranks = pd.read_csv(ROOT / "outputs" / "p2" / "results.csv")
    leaders = dict(zip(ranks[ranks["rank"] == 1]["category"], ranks[ranks["rank"] == 1]["vendor"]))
    t8 = [["Сценарий", "U", "Затраты", "Изменение плана / причина"]]
    for r in scen.itertuples():
        sc = next(x for x in cfg4["scenarios"] if x["id"] == r.id)
        t_max = sc["changes"].get("t_max_weeks")
        late = []
        if t_max is not None:
            late = [SHORT.get(v, v) for v, lw, ok in zip(alt["vendor"], alt["lead_weeks"], alt["admissible"]) if ok and lw > t_max]
        late_txt = ("не успевают: " + ", ".join(late) + "; ") if late else ""
        if r.status == "Optimal":
            change = "-" if r.id == "base" else describe(base_row["plan"], r.plan, cat_of, leaders)
            if "доля высокого риска" in str(r.binding) and r.id != "base":
                change = "план тот же, ограничение активно" if change == "план не меняется" else change + " (ограничение активно)"
            t8.append([r.name, num(r.utility, 3), mln(r.cost), late_txt + change])
        else:
            reason = str(r.binding)
            if "млн" in reason:
                reason = "не хватает бюджета: нужно " + reason.split("затраты ")[-1].replace(".", ",", 1)
            elif "ПК и серверы" in reason:
                reason = "нет допустимых поставщиков ПК и серверов"
            t8.append([r.name, "-", "-", late_txt + reason])

    nb = scen[scen["id"] == "no_budget"].iloc[0]
    nsc = scen[scen["id"] == "no_share_cap"].iloc[0]
    jump = front.iloc[(front["utility"].diff()).idxmax()]
    first = front.iloc[0]
    last, prev = front.iloc[-1], front.iloc[-2]

    blocks = [
        ("title", "ПАСПОРТ СППР"),
        ("subtitle", "Выбор поставщиков оборудования для диспетчерских комплексов"),
        ("author", "Выполнил: Новосельцев Андрей Алексеевич, группа К4241"),
        ("h1", "4 ОПТИМИЗАЦИОННАЯ МОДЕЛЬ"),
        ("h2", "4.1 Постановка"),
        ("p", f"Задача - определить, сколько из {n} типовых комплексов комплектовать у каждого поставщика в пяти категориях: ИБП (источник бесперебойного питания), АВР (автоматический ввод резерва), КВМ-переключатели (управление несколькими компьютерами с одной клавиатуры, монитора и мыши), коммутаторы, ПК и серверы. Цель - наибольшая полезность плана по оценкам АНР (метода анализа иерархий, практика № 2) при ограничениях практики № 1 и с учётом рисков практики № 3. Параметры задаёт ЛПР (лицо, принимающее решение, - директор): бюджет B = {mln(p['budget_rub'], 0)} млн руб., срок поставки не более {p['t_max_weeks']} недель, не более {p['max_suppliers']} поставщиков в категории, минимальная партия - {p['min_lot']} комплекса, доля оборудования с высоким санкционным риском (оценка k_{{6}} ≥ {p['high_risk_k6']}) не более {num(p['max_high_risk_share'] * 100, 0)} %."),
        ("h2", "4.2 Метод"),
        ("p", f"Переменные: y_{{cj}} - число комплексов категории c у поставщика j (целое, 0-{n}); z_{{cj}} - выбран ли поставщик (0 или 1). Целевая функция:"),
        ("formula", "U = Σ_{c} Σ_{j} r_{cj} · y_{cj} / (N · |C|) → max,"),
        ("p0", f"где r_{{cj}} - приоритет АНР поставщика, отнесённый к лидеру категории; N = {n}, |C| = 5. Ограничения: Σ_{{j}} y_{{cj}} = N (спрос); Σ_{{c}} Σ_{{j}} ĉ_{{cj}} · y_{{cj}} ≤ B (бюджет); y_{{cj}} ≤ {num(p['max_share'], 1)} · N · z_{{cj}} (доля поставщика; снимается, если допустимый поставщик один); y_{{cj}} ≥ {p['min_lot']} · z_{{cj}} (партия); Σ_{{j}} z_{{cj}} ≤ {p['max_suppliers']}; z_{{cj}} = 0 при сроке поставки больше {p['t_max_weeks']} недель или недопуске; доля оборудования с k_{{6}} ≥ {p['high_risk_k6']} не более {num(p['max_high_risk_share'] * 100, 0)} %. Ожидаемые затраты на комплекс ĉ_{{cj}} включают закупку с учётом ожидаемого изменения курса (+{num(s['expected_fx_change'] * 100, 1)} %), доплату за замену при срыве поставки, пени и простой бригады из практики № 3 (линейная оценка)."),
        ("p", f"Модель - СЦЛП (смешанное целочисленное линейное программирование): {s['n_variables']} переменных, {s['n_constraints']} ограничения; решена в PuLP решателем CBC (метод ветвей и отсечений). Граница Парето построена методом ε-ограничений: бюджет от {mln(s['min_cost'], 1)} до {mln(s['max_utility_cost'], 1)} млн руб. с шагом 0,1 млн. Найденный план проверен имитационной моделью практики № 3."),
        ("h2", "4.3 Результат"),
        ("caption", f"Таблица 7 – Оптимальный план закупки (бюджет {mln(p['budget_rub'], 0)} млн руб.)"),
        ("table", "T7"),
        ("p", f"Оптимум найден менее чем за 0,1 с с нулевым разрывом: U = {num(s['utility'], 3)} при ожидаемых затратах {mln(s['cost'])} млн руб. Активны ограничения доли {num(p['max_share'] * 100, 0)} % и бюджета: следующий по полезности план ({swap_text(base_row['plan'], nb['plan'])}) стоит {mln(nb['cost'])} млн руб. Имитация практики № 3 даёт E = {mln(sim['on_delivery']['mean'])} млн руб. и CVaR95 = {mln(sim['on_delivery']['cvar95'])} млн руб. (средние затраты в 5 % худших исходов) при оплате по факту поставки и {mln(sim['advance']['mean'])} / {mln(sim['advance']['cvar95'])} млн руб. при опережающей закупке - лучше всех стратегий практики № 3."),
        ("caption", "Таблица 8 – Чувствительность решения к параметрам ЛПР (затраты в млн руб.)"),
        ("table", "T8"),
        ("h2", "4.4 Интерпретация"),
        ("p", f"Директору рекомендуется комплектовать у лидеров АНР по {int(p['max_share'] * n)} комплексов и у вторых поставщиков по {n - int(p['max_share'] * n)}, а закупку проводить заранее (вывод практики № 3). Граница Парето показывает убывающую отдачу: от {mln(first['cost'])} до {mln(jump['cost'])} млн руб. полезность растёт с {num(first['utility'], 3)} до {num(jump['utility'], 3)}, а последний шаг (+{mln(last['cost'] - prev['cost'])} млн руб.) даёт лишь +{num(last['utility'] - prev['utility'], 3)}. Ограничение доли {num(p['max_share'] * 100, 0)} % снижает полезность на {num(nsc['utility'] - s['utility'], 2)}, но уменьшает CVaR95 на {mln(nsc['mc_cvar95'] - base_row['mc_cvar95'])} млн руб. Самое жёсткое ограничение - сроки: при сжатом графике не хватает бюджета или допустимых поставщиков ПК. Технические требования (порты, мощность, схема питания) проверяет база знаний практики № 5."),
    ]
    tables = {
        "T7": {"cols": [100, 247.7, 120], "rows": t7, "align": ["START", "START", "CENTER"]},
        "T8": {"cols": [112, 40, 56, 259.7], "rows": t8, "align": ["START", "CENTER", "CENTER", "START"]},
    }
    return blocks, tables


if __name__ == "__main__":
    b, t = content()
    for k, v in b:
        print(k, "|", v[:400])
    for name, spec in t.items():
        print(name)
        for row in spec["rows"]:
            print("   ", row)
