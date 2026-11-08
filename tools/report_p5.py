"""Текст практики №5 (база знаний) для паспорта СППР. Числа и выводы берутся из outputs/p5 и config/p5_kb.json."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "p5"
SHORT = {"HP (HPE Aruba)": "HP Aruba"}
TABLE_RULES = ["R1", "R2", "R3", "R3a", "R4", "R5", "R7", "R9", "R10", "R11", "R12", "R13", "R14"]


def num(x, d=3):
    return f"{x:.{d}f}".replace(".", ",")


def short(v):
    return SHORT.get(v, v)


def content():
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "config" / "p5_kb.json").read_text(encoding="utf-8"))
    p4 = json.loads((ROOT / "outputs" / "p4" / "summary.json").read_text(encoding="utf-8"))
    req = cfg["requirements"]
    st = s["ontology"]
    inf = pd.read_csv(OUT / "inference_base.csv").fillna("")
    trace = pd.read_csv(OUT / "trace_base.csv")
    scen = {r["id"]: r for r in s["scenarios"]}
    rules = {r["id"]: r for r in cfg["rules"]}

    # Таблица 9: правила и на ком они сработали (типовой комплекс; если не сработали - в каком сценарии)
    def fired(df, rid):
        if rules[rid]["kind"] == "flag":            # флаги показываем только для допустимых моделей
            df = df[df["admissible"].astype(str).str.lower() == "true"]
        col = df["exclusion_rules"].astype(str) + ", " + df["flag_rules"].astype(str)
        hit = df[col.str.split(", ").apply(lambda xs: rid in xs)]
        return [short(v) for v in hit["vendor"]]
    scen_tabs = {sc["id"]: pd.read_csv(OUT / f"inference_{sc['id']}.csv").fillna("") for sc in cfg["scenarios"]}
    scen_name = {"direct_ats": "при прямом питании от АВР", "high_load": "при нагрузке 2,2 кВт",
                 "import_substitution": "при импортозамещении"}
    t9 = [["№", "ЕСЛИ → ТО", "Сработало (типовой комплекс)"]]
    for rid in TABLE_RULES:
        if rid == "R13":
            who_base = [short(v) for v in inf.loc[inf.recommended, "vendor"]]
        elif rid == "R14":
            who_base = s["expand_suppliers_base"]
        else:
            who_base = fired(inf, rid)
        if who_base:
            cell = ", ".join(who_base)
            if rid == "R5":
                cell += " (2 порта вместо 4)"
            if rid == "R10":
                cell += f" (раунд {int(trace.loc[trace.rule == 'R10', 'step'].min())})"
        else:
            parts = []
            for sc_id, label in scen_name.items():
                if rid == "R14":
                    lst = [x.strip() for x in scen[sc_id]["expand_suppliers"].split(",") if x.strip()]
                    lst = ["ПК" if x == "ПК и серверы" else x for x in lst]
                else:
                    lst = fired(scen_tabs[sc_id], rid)
                if lst:
                    parts.append(f"{label}: " + (", ".join(lst) if len(lst) <= 3 else f"{len(lst)} моделей"))
            cell = "нет; " + "; ".join(parts) if parts else "нет"
        t9.append([rid, f"{rules[rid]['if']} → {rules[rid]['then']}", cell])

    r10_step = int(trace.loc[trace.rule == "R10", "step"].min())
    base, direct = scen["base"], scen["direct_ats"]
    plan = {v: int(c) for v, c in (part.rsplit(" ", 1) for part in base["plan"].split("; "))}

    blocks = [
        ("title", "ПАСПОРТ СППР"),
        ("subtitle", "Выбор поставщиков оборудования для диспетчерских комплексов"),
        ("author", "Выполнил: Новосельцев Андрей Алексеевич, группа К4241"),
        ("h1", "5 БАЗА ЗНАНИЙ"),
        ("h2", "5.1 Постановка"),
        ("p", "Задача - записать экспертные знания о допуске и рисках поставщиков в виде базы знаний, чтобы СППР сама отсеивала непригодное оборудование и объясняла выводы: АНР (метод анализа иерархий, практика № 2) сравнивает поставщиков по оценкам, но не проверяет соответствие комплексу. База знаний охватывает ИБП (источники бесперебойного питания), АВР (автоматический ввод резерва), КВМ-переключатели (управление несколькими компьютерами с одной клавиатуры, монитора и мыши), коммутаторы, ПК и серверы, а также требования типового комплекса (таблица 9)."),
        ("h2", "5.2 Метод"),
        ("p", f"Онтология на языке OWL (язык описания онтологий) построена в Python (библиотека owlready2) и открывается в Protégé: {st['classes']} класса, {st['object_properties']} связей и {st['data_properties']} атрибутов (основные понятия - таблица 9). Знания записаны {s['rules_total']} продукционными правилами ЕСЛИ - ТО (таблица 10); {s['rules_swrl']} из них продублированы на SWRL (языке правил для онтологий) для Protégé, а R13 и R14 требуют замкнутого мира и выполняются в Python. Вывод прямой: правила применяются раундами, пока появляются новые факты; у каждого заключения хранится правило и причина."),
        ("caption", "Таблица 9 – Основные понятия и связи онтологии"),
        ("table", "T8"),
        ("h2", "5.3 Результат"),
        ("caption", "Таблица 10 – Продукционные правила базы знаний и результаты вывода"),
        ("table", "T9"),
        ("p", f"Для типового комплекса вывод занял {s['inference_steps']} раунда и дал {s['derived_facts']} заключений (таблица 10); R10 сработало в раунде {r10_step} на факте, выведенном R9. Допуск передан в модель практики № 4: без MikroTik коммутаторы - Eltex {plan['Eltex']} и Cisco {plan['Cisco']}, ПК - Lenovo {plan['Lenovo']} и HP {plan['HP']}; U = {num(base['utility'])} вместо {num(p4['utility'])}, ожидаемые затраты {num(base['cost'] / 1e6, 2)} млн руб. При нагрузке 2,2 кВт и при импортозамещении допустимого плана нет - СППР требует расширить перечень поставщиков (R14)."),
        ("h2", "5.4 Интерпретация"),
        ("p", "База знаний добавляет в СППР проверку соответствия требованиям и объяснение решений: директор видит, что MikroTik отсеян технически, HP допустим только с его согласованием, для оборудования параллельного импорта нужен резерв ЗИП (запасного имущества и принадлежностей), для Eltena и Adder - запрос КП (коммерческого предложения). В прототипе (практика № 8) база знаний - фильтр допуска перед оптимизацией; файл kb/sppr_suppliers.owl открывается в Protégé."),
    ]
    t8 = [["Понятие (класс)", "Факты, свойства и связи"],
          ["Оборудование: ИБП, АВР, КВМ-переключатель, коммутатор, ПК и сервер",
           f"{st['models']} моделей; цена, срок, гарантия, оценки k2-k7, мощность, время переключения, порты SFP+, L3; связи: производится вендором, страна производства, замена при срыве"],
          ["Вендор", f"{st['vendors']} вендоров; связи: канал поставки, страна вендора"],
          ["Канал поставки в РФ", "российский производитель, официальный дистрибьютор, параллельный импорт (подкласс - исключён из перечня), статус не подтверждён"],
          ["Страна", f"{st['countries']} стран"],
          ["Комплекс (требования)", f"нагрузка стойки {num(req['rack_load_w'] / 1000, 1)} кВт, запас мощности ИБП {num((req['power_margin'] - 1) * 100, 0)} %, {req['sfp_plus_required']} порта SFP+ (гнёзда для модулей 10 Гбит/с), АВР перед ИБП, стоечный АВР, срок до {req['max_lead_weeks']} нед."],
          ["Выводимые классы", "недопустимая, допустимая, рекомендуемая; высокий санкционный риск; требует согласования, ЗИП, КП; только перед ИБП"]]
    tables = {
        "T8": {"cols": [150, 317.7], "rows": t8, "align": ["START", "START"]},
        "T9": {"cols": [32, 250, 185.7], "rows": t9, "align": ["CENTER", "START", "START"]},
    }
    return blocks, tables


if __name__ == "__main__":
    b, t = content()
    for k, v in b:
        print(k, "|", v[:300])
    for name, spec in t.items():
        print(name)
        for row in spec["rows"]:
            print("   ", row)
