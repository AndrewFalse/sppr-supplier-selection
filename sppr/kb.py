"""База знаний (практика №5): онтология предметной области + продукционные правила.

- build_ontology - онтология OWL (классы, свойства, индивиды, требования комплекса, правила SWRL)
  для просмотра и проверки в Protégé; имена латиницей, подписи (rdfs:label) на русском;
- extract_facts  - факты о моделях, считанные из онтологии;
- infer          - прямой логический вывод (forward chaining) до насыщения с объяснением каждого вывода,
                   затем правила замкнутого мира R13-R14 (недоступны в OWL из-за открытого мира);
- admission      - допуск альтернатив для оптимизационной модели практики №4.
"""
import re

import pandas as pd
from owlready2 import (DataProperty, FunctionalProperty, Imp, ObjectProperty, Thing, World, locstr)

BASE_IRI = "https://github.com/AndrewFalse/sppr-supplier-selection/ontology"
CAT_CLASS = {"ИБП": "UPS", "АВР": "ATS", "КВМ": "KVMSwitch", "Коммутаторы": "NetworkSwitch", "ПК и серверы": "PCServerKit"}
CAT_LABEL = {"UPS": "ИБП (источник бесперебойного питания)", "ATS": "АВР (автоматический ввод резерва)",
             "KVMSwitch": "КВМ-переключатель", "NetworkSwitch": "Коммутатор", "PCServerKit": "Комплект ПК и сервер"}
CHANNELS = {  # статус в РФ -> (индивид, класс, подпись)
    "russian_manufacturer": ("ch_russian_manufacturer", "RussianManufacturerChannel", "российский производитель"),
    "official_distributor": ("ch_official_distributor", "OfficialDistributorChannel", "официальный дистрибьютор"),
    "left_ru_parallel_import": ("ch_parallel_import", "ParallelImportChannel", "параллельный импорт"),
    "left_ru_excluded_from_parallel_import": ("ch_excluded", "ExcludedFromParallelImport",
                                              "исключён из перечня параллельного импорта"),
    "unknown": ("ch_unconfirmed", "UnconfirmedChannel", "статус в РФ не подтверждён"),
}
COUNTRIES = [("росси", "russia", "Россия"), ("сша", "usa", "США"), ("франц", "france", "Франция"),
             ("тайван", "taiwan", "Тайвань"), ("великобр", "uk", "Великобритания"), ("латв", "latvia", "Латвия"),
             ("кита", "china", "Китай")]
INFERRED = {  # предикат вывода -> (класс, подпись)
    "inadmissible": ("InadmissibleAlternative", "Недопустимая альтернатива"),
    "only_before_ups": ("OnlyBeforeUps", "Допустима только перед ИБП"),
    "high_sanction_risk": ("HighSanctionRisk", "Высокий санкционный риск"),
    "requires_approval": ("RequiresApproval", "Требует согласования ЛПР"),
    "requires_spare_parts": ("RequiresSpareParts", "Требует резерва ЗИП"),
    "requires_quote": ("RequiresQuote", "Требует запроса КП"),
    "admissible": ("AdmissibleAlternative", "Допустимая альтернатива"),
    "recommended": ("RecommendedAlternative", "Рекомендуемая альтернатива"),
}
TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                     "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(text):
    t = "".join(TRANSLIT.get(ch, ch) for ch in str(text).lower())
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def country_of(text):
    low = str(text).lower()
    for key, code, label in COUNTRIES:
        if key in low:
            return code, label
    return "unknown", "не указано"


def build_ontology(models, specs, req, rules, world=None):
    """models: alternatives_scored + приоритет АНР (ahp_priority); specs: technical_specs.csv;
    req: требования комплекса; rules: список правил из config/p5_kb.json."""
    world = world or World()
    onto = world.get_ontology(BASE_IRI + "#")
    ru = lambda s: [locstr(s, lang="ru")]
    with onto:
        class Equipment(Thing): pass
        Equipment.label = ru("Оборудование (альтернатива)")
        for cls, lab in CAT_LABEL.items():
            c = type(cls, (Equipment,), {})
            c.label = ru(lab)
        class Vendor(Thing): pass
        Vendor.label = ru("Вендор (производитель)")
        class Country(Thing): pass
        Country.label = ru("Страна")
        class SupplyChannel(Thing): pass
        SupplyChannel.label = ru("Канал поставки в РФ")
        for key, (_, cls, lab) in CHANNELS.items():       # «исключён из перечня» - подкласс параллельного импорта
            parent = onto.ParallelImportChannel if cls == "ExcludedFromParallelImport" else SupplyChannel
            c = type(cls, (parent,), {})
            c.label = ru(lab)
        class Complex(Thing): pass
        Complex.label = ru("Типовой диспетчерский комплекс (требования)")
        for pred, (cls, lab) in INFERRED.items():
            c = type(cls, (Equipment,), {})
            c.label = ru(lab)

        def obj_prop(name, dom, rng, label):
            p = type(name, (ObjectProperty, FunctionalProperty), {"domain": [dom], "range": [rng]})
            p.label = ru(label)

        def data_prop(name, dom, rng, label):
            p = type(name, (DataProperty, FunctionalProperty), {"domain": [dom], "range": [rng]})
            p.label = ru(label)

        obj_prop("madeBy", Equipment, Vendor, "производится вендором")
        obj_prop("producedIn", Equipment, Country, "страна производства")
        obj_prop("hasChannel", Vendor, SupplyChannel, "канал поставки")
        obj_prop("vendorCountry", Vendor, Country, "страна вендора")
        obj_prop("replacement", Equipment, Equipment, "замена при срыве поставки")
        for name, rng, lab in [("modelName", str, "модель"), ("priceRub", float, "цена, руб."),
                               ("leadWeeks", float, "срок поставки, нед."), ("warrantyMonths", float, "гарантия, мес."),
                               ("ahpPriority", float, "приоритет АНР"), ("qualityScore", int, "оценка k2 (качество)"),
                               ("reliabilityScore", int, "оценка k3 (надёжность)"),
                               ("sanctionRiskScore", int, "оценка k6 (санкционный риск)"),
                               ("russianOriginScore", int, "оценка k7 (российское происхождение)"),
                               ("unavailable", bool, "недоступна у продавцов"),
                               ("priceConfirmed", bool, "цена подтверждена"),
                               ("sellerWarrantyOnly", bool, "гарантия только продавца"),
                               ("activePowerW", float, "активная мощность, Вт"),
                               ("switchTimeMs", float, "время переключения, мс"),
                               ("ratedCurrentA", float, "номинальный ток, А"), ("rackMount", bool, "стоечное исполнение"),
                               ("sfpPlusPorts", int, "портов SFP+"), ("l3Routing", bool, "маршрутизация L3")]:
            data_prop(name, Equipment, rng, lab)
        for name, rng, lab in [("rackLoadW", float, "нагрузка стойки, Вт"), ("powerMargin", float, "запас мощности ИБП"),
                               ("sfpPlusRequired", int, "требуется портов SFP+"),
                               ("atsBeforeUps", bool, "АВР стоит перед ИБП"),
                               ("maxAtsSwitchMs", float, "допустимое время переключения АВР, мс"),
                               ("rackMountAtsRequired", bool, "требуется стоечный АВР"),
                               ("l3Required", bool, "требуется маршрутизация L3"),
                               ("russianOriginRequired", bool, "требуется импортозамещение"),
                               ("minRussianOriginScore", int, "минимальная оценка k7"),
                               ("maxLeadWeeks", float, "допустимый срок поставки, нед.")]:
            data_prop(name, Complex, rng, lab)

        # индивиды: каналы, страны, вендоры, модели, комплекс
        channels = {}
        for key, (ind, cls, lab) in CHANNELS.items():
            channels[key] = getattr(onto, cls)(ind)
            channels[key].label = ru(lab)
        countries = {}

        def country(text):
            code, label = country_of(text)
            if code not in countries:
                countries[code] = Country(f"country_{code}")
                countries[code].label = ru(label)
            return countries[code]

        spec = {(r["category"], r["vendor"]): r for r in specs.to_dict("records")}
        vendors, inds = {}, {}
        for r in models.to_dict("records"):
            vkey = r["vendor"]
            if vkey not in vendors:
                v = Vendor(f"v_{slug(vkey)}")
                v.label = ru(vkey)
                v.hasChannel = channels.get(r["ru_status"], channels["unknown"])
                v.vendorCountry = country(r["vendor_country"])
                vendors[vkey] = v
            m = getattr(onto, CAT_CLASS[r["category"]])(f"m_{slug(CAT_CLASS[r['category']])}_{slug(vkey)}")
            m.label = ru(f"{vkey} {r['model']}")
            m.modelName = str(r["model"])
            m.madeBy = vendors[vkey]
            m.producedIn = country(r["production_country"])
            m.priceRub = float(r["price_rub"])
            m.leadWeeks = float(r["lead_time_weeks_model"])
            m.warrantyMonths = float(r["warranty_months_model"])
            m.ahpPriority = float(r["ahp_priority"])
            m.qualityScore, m.reliabilityScore = int(r["k2_quality"]), int(r["k3_reliability"])
            m.sanctionRiskScore, m.russianOriginScore = int(r["k6_sanction_risk"]), int(r["k7_russian_origin"])
            m.unavailable = str(r.get("unavailable", "")).lower() == "yes"
            m.priceConfirmed = str(r["price_status"]).startswith(("verified", "snapshot"))
            s = spec.get((r["category"], vkey), {})
            m.sellerWarrantyOnly = str(s.get("seller_warranty_only", "")).lower() == "true"
            for col, prop, cast in [("active_power_w", "activePowerW", float), ("switch_time_ms", "switchTimeMs", float),
                                    ("rated_current_a", "ratedCurrentA", float), ("sfp_plus_ports", "sfpPlusPorts", int)]:
                if pd.notna(s.get(col)) and s.get(col) != "":
                    setattr(m, prop, cast(float(s[col])))
            for col, prop in [("rack_mount", "rackMount"), ("l3_routing", "l3Routing")]:
                if pd.notna(s.get(col)) and s.get(col) != "":
                    setattr(m, prop, str(s[col]).lower() == "true")
            inds[(r["category"], vkey)] = m
        for r in models.to_dict("records"):
            if r.get("repl") and (r["category"], r["repl"]) in inds:
                inds[(r["category"], r["vendor"])].replacement = inds[(r["category"], r["repl"])]
        k = Complex("typical_complex")
        k.label = ru("Типовой диспетчерский комплекс")
        k.rackLoadW, k.powerMargin = float(req["rack_load_w"]), float(req["power_margin"])
        k.sfpPlusRequired, k.atsBeforeUps = int(req["sfp_plus_required"]), bool(req["ats_before_ups"])
        k.maxAtsSwitchMs, k.rackMountAtsRequired = float(req["max_ats_switch_ms"]), bool(req["rack_mount_ats_required"])
        k.l3Required, k.russianOriginRequired = bool(req["l3_required"]), bool(req["russian_origin_required"])
        k.minRussianOriginScore, k.maxLeadWeeks = int(req["min_russian_origin_score"]), float(req["max_lead_weeks"])

        for rule in rules:
            if rule.get("swrl"):
                imp = Imp(f"rule_{rule['id']}")
                imp.set_as_rule(rule["swrl"])
                imp.label = ru(f"{rule['id']}: ЕСЛИ {rule['if']} ТО {rule['then']}")
    return onto


def extract_facts(onto):
    """Факты о моделях из онтологии (то, над чем работает логический вывод)."""
    rev_cat = {v: k for k, v in CAT_CLASS.items()}
    rev_ch = {v[1]: k for k, v in CHANNELS.items()}
    facts = []
    for cls_name, cat in rev_cat.items():
        for m in getattr(onto, cls_name).instances():
            ch_cls = [c.name for c in m.madeBy.hasChannel.is_a if c.name in rev_ch]
            facts.append({
                "id": m.name, "category": cat, "vendor": str(m.madeBy.label[0]), "model": m.modelName,
                "channel": rev_ch[ch_cls[0]] if ch_cls else "unknown",
                "unavailable": bool(m.unavailable), "price_confirmed": bool(m.priceConfirmed),
                "seller_warranty_only": bool(m.sellerWarrantyOnly), "lead_weeks": m.leadWeeks,
                "k7": m.russianOriginScore, "ahp": m.ahpPriority, "active_power_w": m.activePowerW,
                "switch_time_ms": m.switchTimeMs, "rack_mount": m.rackMount, "sfp_plus_ports": m.sfpPlusPorts,
                "l3_routing": m.l3Routing,
            })
    return facts


def _num(x):
    return f"{x:g}".replace(".", ",")


# Продукционные правила: функция(факты модели, требования, выведенное) -> (предикат, объяснение) или None
def _r1(m, q, d):
    return ("inadmissible", "модель недоступна у продавцов") if m["unavailable"] else None


def _r2(m, q, d):
    if m["category"] == "АВР" and q["rack_mount_ats_required"] and m["rack_mount"] is False:
        return "inadmissible", "АВР щитовой, а требуется стоечный"


def _r3(m, q, d):
    t = m["switch_time_ms"]
    if m["category"] == "АВР" and t is not None and t > q["max_ats_switch_ms"] and not q["ats_before_ups"]:
        return "inadmissible", f"переключение {_num(t)} мс > {_num(q['max_ats_switch_ms'])} мс при прямом питании нагрузки"


def _r3a(m, q, d):
    t = m["switch_time_ms"]
    if m["category"] == "АВР" and t is not None and t > q["max_ats_switch_ms"] and q["ats_before_ups"]:
        return "only_before_ups", f"переключение {_num(t)} мс допустимо только перед ИБП"


def _r4(m, q, d):
    p = m["active_power_w"]
    need = q["rack_load_w"] * q["power_margin"]
    if m["category"] == "ИБП" and p is not None and p < need:
        return "inadmissible", f"мощность {_num(p)} Вт < {_num(q['rack_load_w'])} × {_num(q['power_margin'])} = {_num(need)} Вт"


def _r5(m, q, d):
    n = m["sfp_plus_ports"]
    if m["category"] == "Коммутаторы" and n is not None and n < q["sfp_plus_required"]:
        return "inadmissible", f"{n} порта SFP+ < {q['sfp_plus_required']}"


def _r6(m, q, d):
    if m["category"] == "Коммутаторы" and q["l3_required"] and m["l3_routing"] is False:
        return "inadmissible", "нет маршрутизации L3"


def _r7(m, q, d):
    if q["russian_origin_required"] and m["k7"] < q["min_russian_origin_score"]:
        return "inadmissible", f"k7 = {m['k7']} < {q['min_russian_origin_score']} (не российское производство)"


def _r8(m, q, d):
    if m["lead_weeks"] > q["max_lead_weeks"]:
        return "inadmissible", f"срок {_num(m['lead_weeks'])} нед. > {_num(q['max_lead_weeks'])}"


def _r9(m, q, d):
    if m["channel"] == "left_ru_excluded_from_parallel_import":
        return "high_sanction_risk", "вендор исключён из перечня параллельного импорта"


def _r10(m, q, d):
    if "high_sanction_risk" in d:
        return "requires_approval", "высокий санкционный риск - закупка по согласованию ЛПР"


def _r11(m, q, d):
    if m["channel"] in ("left_ru_parallel_import", "left_ru_excluded_from_parallel_import") and m["seller_warranty_only"]:
        return "requires_spare_parts", "параллельный импорт и гарантия только продавца - резерв ЗИП"


def _r12(m, q, d):
    return ("requires_quote", "цена не подтверждена открытой страницей - запросить КП") if not m["price_confirmed"] else None


RULE_FUNCS = {"R1": _r1, "R2": _r2, "R3": _r3, "R3a": _r3a, "R4": _r4, "R5": _r5, "R6": _r6, "R7": _r7, "R8": _r8,
              "R9": _r9, "R10": _r10, "R11": _r11, "R12": _r12}


def infer(facts, req, rules):
    """Прямой вывод до насыщения + правила замкнутого мира. Возвращает (derived, trace, meta)."""
    derived = {m["id"]: {} for m in facts}
    trace = []
    active = [r for r in rules if r["id"] in RULE_FUNCS]
    step = 0
    while True:                       # раунды: правила видят факты, известные к началу раунда
        step += 1
        snapshot = {mid: {pred: list(v) for pred, v in d.items()} for mid, d in derived.items()}
        new = []
        for rule in active:
            for m in facts:
                res = RULE_FUNCS[rule["id"]](m, req, snapshot[m["id"]])
                if not res:
                    continue
                pred, why = res
                if rule["id"] not in [r for r, _ in derived[m["id"]].get(pred, [])]:
                    new.append((m, rule["id"], pred, why))
        if not new:                   # насыщение: новых фактов нет
            step -= 1
            break
        for m, rid, pred, why in new:
            derived[m["id"]].setdefault(pred, []).append((rid, why))
            trace.append({"step": step, "rule": rid, "model": m["id"], "vendor": m["vendor"],
                          "category": m["category"], "fact": pred, "why": why})
    meta = {"expand_suppliers": []}
    for cat in dict.fromkeys(m["category"] for m in facts):     # замкнутый мир: R13, R14
        ok = [m for m in facts if m["category"] == cat and "inadmissible" not in derived[m["id"]]]
        for m in ok:
            derived[m["id"]]["admissible"] = [("closed-world", "ни одно правило недопуска не сработало")]
        if ok:
            best = max(ok, key=lambda m: m["ahp"])
            derived[best["id"]]["recommended"] = [("R13", f"наибольший приоритет АНР среди допустимых ({_num(round(best['ahp'], 3))})")]
            trace.append({"step": step + 1, "rule": "R13", "model": best["id"], "vendor": best["vendor"], "category": cat,
                          "fact": "recommended", "why": derived[best["id"]]["recommended"][0][1]})
        else:
            meta["expand_suppliers"].append(cat)
            trace.append({"step": step + 1, "rule": "R14", "model": "", "vendor": "", "category": cat,
                          "fact": "expand_suppliers", "why": "в категории нет допустимых альтернатив"})
    return derived, trace, meta


def result_table(facts, derived):
    rows = []
    for m in facts:
        d = derived[m["id"]]
        rows.append({"category": m["category"], "vendor": m["vendor"], "admissible": "inadmissible" not in d,
                     "exclusion_rules": ", ".join(r for r, _ in d.get("inadmissible", [])),
                     "exclusion_reason": "; ".join(w for _, w in d.get("inadmissible", [])),
                     "flags": ", ".join(INFERRED[p][1] for p in ("only_before_ups", "high_sanction_risk", "requires_approval",
                                                                  "requires_spare_parts", "requires_quote") if p in d),
                     "flag_rules": ", ".join(r for p in ("only_before_ups", "high_sanction_risk", "requires_approval",
                                                         "requires_spare_parts", "requires_quote") for r, _ in d.get(p, [])),
                     "recommended": "recommended" in d})
    return pd.DataFrame(rows)


def admission(table):
    """Допуск для оптимизационной модели практики №4."""
    adm = table[["category", "vendor", "admissible"]].copy()
    adm["reason"] = [("" if a else f"база знаний: {rules} - {why}")
                     for a, rules, why in zip(table["admissible"], table["exclusion_rules"], table["exclusion_reason"])]
    return adm


def assert_inferred(onto, derived):
    """Записывает выведенные факты в онтологию как утверждения (для просмотра в Protégé без запуска рассуждателя)."""
    with onto:
        for mid, d in derived.items():
            ind = getattr(onto, mid)
            for pred in d:
                cls = getattr(onto, INFERRED[pred][0])
                if cls not in ind.is_a:
                    ind.is_a.append(cls)
    return onto


def stats(onto):
    count = lambda cls: len(list(getattr(onto, cls).instances()))
    return {"classes": len(list(onto.classes())), "object_properties": len(list(onto.object_properties())),
            "data_properties": len(list(onto.data_properties())),
            "models": count("Equipment"), "vendors": count("Vendor"), "channels": count("SupplyChannel"),
            "countries": count("Country"), "complexes": count("Complex"), "swrl_rules": len(list(onto.rules()))}
