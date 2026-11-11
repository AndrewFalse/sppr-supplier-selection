"""Прототип СППР выбора поставщиков (практика №8): интерфейс ЛПР.

Объединяет модули практик 2-7: АНР, риски, оптимизацию, базу знаний, прогноз и рекомендации.
Запуск: streamlit run app/main.py   (или docker compose up)
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import p7_recommend  # noqa: E402
from sppr.recommend import CRIT_NAMES  # noqa: E402

SUPERSET_URL = os.environ.get("SUPERSET_PUBLIC_URL", "http://localhost:8088") + "/superset/dashboard/sppr/"
PRESETS = {
    "Типовой комплекс": {},
    "Осторожный директор": {"risk_mult": 1.5},
    "Импортозамещение": {"import_sub": True},
}

st.set_page_config(page_title="СППР: выбор поставщиков", layout="wide")


def num(x, d=2):
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def mln(x, d=2):
    return num(x / 1e6, d)


def load_json(*parts):
    return json.loads(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Пересчёт: база знаний, ранжирование, оптимизация...")
def compute(context_json):
    res = p7_recommend.recommend_for("custom", context=json.loads(context_json))
    res["weights"] = dict(res["weights"])
    return res


@st.cache_data
def static_data():
    with sqlite3.connect(ROOT / "outputs" / "p6" / "sppr_bi.db") as con:
        fx = pd.read_sql("select * from fx_usd", con, parse_dates=["week"])
    return {
        "fx": fx,
        "fxf": pd.read_csv(ROOT / "outputs" / "p6" / "fx_forecast.csv", index_col=0, parse_dates=True),
        "cost": pd.read_csv(ROOT / "outputs" / "p6" / "plan_cost_forecast.csv", index_col=0, parse_dates=True),
        "fx_metrics": pd.read_csv(ROOT / "outputs" / "p6" / "fx_metrics.csv"),
        "s6": load_json("outputs", "p6", "summary.json"),
        "strategies": pd.read_csv(ROOT / "outputs" / "p3" / "strategies.csv"),
        "criteria3": pd.read_csv(ROOT / "outputs" / "p3" / "criteria.csv", index_col=0),
        "pareto": pd.read_csv(ROOT / "outputs" / "p4" / "pareto.csv"),
        "base_w": pd.read_csv(ROOT / "outputs" / "p2" / "criteria_weights.csv"),
        "cr": load_json("outputs", "p2", "summary.json")["criteria"],
        "rules": load_json("config", "p5_kb.json")["rules"],
        "req": load_json("config", "p5_kb.json")["requirements"],
        "cfg4": load_json("config", "p4_optimization.json"),
        "alts": pd.read_csv(ROOT / "data" / "processed" / "alternatives_scored.csv"),
    }


D = static_data()

# ---------------------------------------------------------------- панель ЛПР
st.sidebar.header("Параметры директора")
preset = st.sidebar.selectbox("Сценарий", list(PRESETS), help="Готовые наборы параметров; ниже их можно изменить")
pv = PRESETS[preset]
budget = st.sidebar.slider("Бюджет закупки, млн руб.", 10.5, 14.0, D["cfg4"]["budget_rub"] / 1e6, 0.1, key=f"b_{preset}")
t_max = st.sidebar.slider("Срок поставки не более, недель", 6, 13, int(D["cfg4"]["t_max_weeks"]), key=f"t_{preset}")
share = st.sidebar.slider("Доля одного поставщика не более, %", 50, 100, int(D["cfg4"]["max_share"] * 100), 10, key=f"s_{preset}")
st.sidebar.subheader("Требования к комплексу")
load_kw = st.sidebar.slider("Нагрузка стойки, кВт", 1.0, 2.5, D["req"]["rack_load_w"] / 1000, 0.1, key=f"l_{preset}")
ats_before = st.sidebar.checkbox("АВР установлен перед ИБП", value=True, key=f"a_{preset}")
import_sub = st.sidebar.checkbox("Требуется импортозамещение", value=pv.get("import_sub", False), key=f"i_{preset}")
st.sidebar.subheader("Отношение к риску")
risk_mult = st.sidebar.slider("Важность надёжности и санкционного риска, ×", 1.0, 2.0, pv.get("risk_mult", 1.0), 0.1, key=f"r_{preset}")

context = {
    "name": preset,
    "kb_changes": {"rack_load_w": round(load_kw * 1000), "ats_before_ups": ats_before,
                   "russian_origin_required": import_sub, "max_lead_weeks": t_max},
    "weights": ({"k3": risk_mult, "k6": risk_mult} if risk_mult != 1.0 else {}) | ({"k7": 2.0} if import_sub else {}),
    "params": {"budget_rub": budget * 1e6, "t_max_weeks": t_max, "max_share": share / 100},
}
R = compute(json.dumps(context, sort_keys=True, ensure_ascii=False))
recs, acts, plan, kbt = R["recommendations"], R["actions"], R["plan"], R["kb_table"]
ok = R["plan_status"] == "Optimal"

st.title("СППР: выбор поставщиков оборудования для диспетчерских комплексов")
st.caption("Проект: 10 типовых комплексов. ЛПР - директор. Данные: открытые источники (цены на 13.10.2026, курсы ЦБ РФ, Росстат); "
           "оценки 1-5 - экспертные оценки аналитика.")

tabs = st.tabs(["Рекомендация", "Критерии и рейтинг", "Риски", "Оптимальный план", "База знаний", "Прогноз и дашборд", "О системе"])

# ---------------------------------------------------------------- 1. рекомендация
with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    if ok:
        sim = R["simulation"]
        c1.metric("Полезность плана", num(R["utility"], 3))
        c2.metric("Ожидаемые затраты, млн руб.", mln(R["cost"]))
        c3.metric("При закупке заранее, млн руб.", mln(sim["advance"]["mean"]),
                  delta=f"{mln(sim['advance']['mean'] - sim['on_delivery']['mean'])} к оплате по факту", delta_color="inverse")
        c4.metric("Худшие 5 % исходов, млн руб.", mln(sim["advance"]["cvar95"]))
        st.success("План закупки найден. Ограничения, определяющие план: " + ", ".join(R["binding"] or ["нет"]) + ".")
    else:
        st.error(f"Допустимого плана нет: {R['plan_diag']}. Измените параметры слева или расширьте перечень поставщиков.")
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Кого выбрать")
        view = recs.copy()
        view["confidence"] = view["confidence"].map(lambda v: "-" if pd.isna(v) else num(v, 2))
        view["why"] = view["why"] + view["note"].fillna("").map(lambda n: f"; {n}" if n else "")
        view = view.rename(columns={"category": "Категория", "recommended": "Лидер", "allocation": "План (комплексов из 10)",
                                    "backup": "Резерв", "confidence": "Уверенность", "why": "Почему",
                                    "counterfactual": "Что изменит выбор"})
        st.dataframe(view[["Категория", "Лидер", "План (комплексов из 10)", "Резерв", "Уверенность", "Почему", "Что изменит выбор"]],
                     hide_index=True, width="stretch")
        st.caption("Уверенность - доля случайных наборов весов критериев, при которых лидер остаётся первым.")
    with right:
        st.subheader("Что сделать директору")
        for i, a in enumerate(acts.itertuples(), start=1):
            st.markdown(f"**{i}.** {a.action}  \n<span style='color:#777;font-size:0.85em'>основание: {a.source}</span>",
                        unsafe_allow_html=True)

# ---------------------------------------------------------------- 2. АНР
with tabs[1]:
    st.subheader("Веса критериев (метод анализа иерархий)")
    w = pd.DataFrame({"Критерий": [f"{k} {CRIT_NAMES[k]}" for k in R["weights"]],
                      "с учётом сценария": list(R["weights"].values()), "базовые": D["base_w"]["weight"].values})
    wl = w.melt("Критерий", var_name="Веса", value_name="Вес")
    st.altair_chart(alt.Chart(wl).mark_bar().encode(
        y=alt.Y("Критерий:N", sort=None, title=None), x=alt.X("Вес:Q"), yOffset="Веса:N",
        color=alt.Color("Веса:N", scale=alt.Scale(range=["#9E9E9E", "#1F4E79"])), tooltip=["Критерий", "Веса", alt.Tooltip("Вес:Q", format=".3f")]
    ).properties(height=300), width="stretch")
    st.caption(f"Согласованность суждений: отношение согласованности ОС = {num(D['cr']['cr'], 3)} (допустимо до 0,10).")
    st.subheader("Рейтинг допустимых поставщиков")
    sc = R["scored"].copy()
    st.altair_chart(alt.Chart(sc).mark_bar(color="#1F4E79").encode(
        x=alt.X("score:Q", title="Полезность (приоритет)"), y=alt.Y("vendor:N", sort="-x", title=None),
        row=alt.Row("category:N", title=None, header=alt.Header(labelAngle=0, labelAlign="left")),
        tooltip=["vendor", alt.Tooltip("score:Q", format=".3f")]
    ).resolve_scale(y="independent").properties(height=70), width="stretch")

# ---------------------------------------------------------------- 3. риски
with tabs[2]:
    st.subheader("Стратегии закупки в условиях неопределённости")
    s = D["strategies"].merge(D["criteria3"].reset_index().rename(columns={"index": "strategy"}), on="strategy")
    tbl = pd.DataFrame({"Стратегия": s["strategy"] + " " + s["name"], "Ожидаемые затраты": s["mean"].map(mln),
                        "Худшие 5 % (CVaR95)": s["cvar95"].map(mln), "Вальд": s["Вальд (худший случай)"].map(mln),
                        "Сэвидж": s["Сэвидж (макс. сожаление)"].map(mln), "Гурвиц": s["Гурвиц"].map(mln)})
    st.dataframe(tbl, hide_index=True, width="stretch")
    st.caption("млн руб.; лучшая по ожиданию, Вальду, Гурвицу и CVaR95 - С4 (опережающая закупка).")
    a, b = st.columns([3, 2])
    a.image(str(ROOT / "outputs" / "p3" / "decision_tree.png"), caption="Дерево решений, ожидаемые затраты в млн руб. (раскрыта стратегия С1)")
    with b:
        st.markdown("**Текущий план при двух способах закупки**")
        if ok:
            sm = R["simulation"]
            st.dataframe(pd.DataFrame({"Закупка": ["оплата по факту поставки", "заранее, со страховым запасом"],
                                       "Ожидаемые затраты": [mln(sm["on_delivery"]["mean"]), mln(sm["advance"]["mean"])],
                                       "Худшие 5 %": [mln(sm["on_delivery"]["cvar95"]), mln(sm["advance"]["cvar95"])],
                                       "Разброс": [mln(sm["on_delivery"]["std"]), mln(sm["advance"]["std"])]}),
                         hide_index=True, width="stretch")
            st.caption("Имитация методом Монте-Карло: 200 тыс. сценариев курса и исходов поставки, млн руб.")
        else:
            st.info("Нет допустимого плана для имитации.")

# ---------------------------------------------------------------- 4. оптимизация
with tabs[3]:
    st.subheader("Оптимальный план закупки")
    if ok:
        a, b = st.columns([2, 3])
        p = plan.sort_values(["category", "complexes"], ascending=[True, False])
        a.dataframe(pd.DataFrame({"Категория": p["category"], "Поставщик": p["vendor"], "Комплексов": p["complexes"],
                                  "Затраты, млн руб.": p["exp_cost"].map(mln)}), hide_index=True, width="stretch")
        b.altair_chart(alt.Chart(p).mark_bar().encode(
            x=alt.X("category:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("exp_cost:Q", title="Ожидаемые затраты, руб."),
            color=alt.Color("vendor:N", title="Поставщик"), tooltip=["vendor", "complexes", alt.Tooltip("exp_cost:Q", format=",.0f")]
        ).properties(height=330), width="stretch")
    else:
        st.error(f"Задача не имеет допустимого решения: {R['plan_diag']}.")
    st.subheader("Граница «затраты - полезность» (базовые требования)")
    layers = [alt.Chart(D["pareto"]).mark_line(point=True, interpolate="step-after", color="#555").encode(
        x=alt.X("cost:Q", title="Ожидаемые затраты, руб.", scale=alt.Scale(zero=False)),
        y=alt.Y("utility:Q", title="Полезность плана", scale=alt.Scale(zero=False)), tooltip=["plan", alt.Tooltip("cost:Q", format=",.0f"), "utility"])]
    if ok:
        layers.append(alt.Chart(pd.DataFrame({"cost": [R["cost"]], "utility": [R["utility"]], "т": ["текущий план"]})).mark_point(
            size=160, filled=True, color="#C0392B").encode(x="cost:Q", y="utility:Q", tooltip=["т"]))
    st.altair_chart(alt.layer(*layers).properties(height=280), width="stretch")
    st.caption("Красная точка - текущий план при выбранных слева параметрах. Модель: смешанное целочисленное программирование (PuLP, решатель CBC).")

# ---------------------------------------------------------------- 5. база знаний
with tabs[4]:
    st.subheader("Заключения базы знаний при текущих требованиях")
    k = kbt.copy()
    k["Допуск"] = k["admissible"].map({True: "допустима", False: "недопустима"})
    k["Заключение"] = k.apply(lambda r: r["exclusion_reason"] if not r["admissible"] else (r["flags"] or "замечаний нет"), axis=1)
    k["Правила"] = k.apply(lambda r: r["exclusion_rules"] if not r["admissible"] else r["flag_rules"], axis=1)
    k["Допуск"] = k["Допуск"].map({"допустима": "✓ допустима", "недопустима": "✗ недопустима"})
    st.dataframe(k.rename(columns={"category": "Категория", "vendor": "Поставщик"})[["Категория", "Поставщик", "Допуск", "Заключение", "Правила"]],
                 hide_index=True, width="stretch", height=560)
    if R["expand_suppliers"]:
        st.warning("Нет допустимых альтернатив в категориях: " + ", ".join(R["expand_suppliers"]) + " (правило R14).")
    with st.expander("Продукционные правила (ЕСЛИ - ТО)"):
        st.dataframe(pd.DataFrame([{"№": r["id"], "ЕСЛИ": r["if"], "ТО": r["then"], "SWRL": r["swrl"] or "выполняется в Python (замкнутый мир)"}
                                   for r in D["rules"]]), hide_index=True, width="stretch")
    st.download_button("Скачать онтологию для Protégé (OWL)", (ROOT / "kb" / "sppr_suppliers.owl").read_bytes(), "sppr_suppliers.owl")

# ---------------------------------------------------------------- 6. прогноз
with tabs[5]:
    s6 = D["s6"]
    c1, c2, c3, c4 = st.columns(4)
    end = s6["forecast_end"]
    c1.metric("Курс USD сейчас, руб.", num(s6["usd_now"]))
    c2.metric("Прогноз через 13 недель", num(end["point"]), delta=f"{num(end['lo80'], 1)} - {num(end['hi80'], 1)} (80 %)", delta_color="off")
    c3.metric("Стоимость плана сейчас, млн руб.", mln(s6["plan_cost_now"]))
    c4.metric("Ошибка прогноза (отложенная проверка)", num(s6["holdout_mape"][s6["best_model"]] * 100, 1) + " %")
    fx = D["fx"]
    hist = fx[(fx.series == "факт") & (fx.week >= fx.week.max() - pd.Timedelta(weeks=95))]
    f = D["fxf"].reset_index().rename(columns={"index": "week"})
    base = alt.Chart(f).encode(x=alt.X("week:T", title=None))
    chart = alt.layer(
        base.mark_area(opacity=0.25, color="#9E9E9E").encode(y=alt.Y("lo95:Q", title="руб. за доллар США", scale=alt.Scale(zero=False)), y2="hi95:Q"),
        base.mark_area(opacity=0.45, color="#9E9E9E").encode(y="lo80:Q", y2="hi80:Q"),
        base.mark_line(color="#C0392B", strokeDash=[5, 3]).encode(y="point:Q"),
        alt.Chart(hist).mark_line(color="#1F4E79").encode(x="week:T", y="value:Q"),
    ).properties(height=300)
    a, b = st.columns([3, 2])
    a.markdown("**Курс USD/RUB: факт ЦБ РФ и прогноз с интервалами 80 и 95 %**")
    a.altair_chart(chart, width="stretch")
    b.markdown("**Точность моделей (скользящая проверка)**")
    m = D["fx_metrics"]
    b.dataframe(pd.DataFrame({"Модель": m["model"], "MAPE, 1-13 нед.": (m["mape"] * 100).map(lambda v: num(v, 1) + " %"),
                              "MAPE, 13 нед.": (m["mape_hmax"] * 100).map(lambda v: num(v, 1) + " %"), "MAE, руб.": m["mae"].map(num)}),
                hide_index=True, width="stretch")
    t = s6["timing"][-1]
    b.info(f"Стоимость плана через 13 недель: {mln(t['cost_point'])} млн руб. (интервал 80 %: {mln(t['cost_lo80'])} - {mln(t['cost_hi80'])}). "
           "Курс по прогнозу не растёт: закупка заранее оправдана снижением риска сроков.")
    st.link_button("Открыть дашборд в Apache Superset", SUPERSET_URL)

# ---------------------------------------------------------------- 7. о системе
with tabs[6]:
    st.subheader("Архитектура прототипа")
    st.dataframe(pd.DataFrame([
        ["Данные", "data/", "курсы и ставка ЦБ РФ, индексы Росстата, цены и статус поставщиков", "все модули"],
        ["Многокритериальный анализ", "sppr/ahp.py", "веса критериев, приоритеты поставщиков", "рейтинг, оптимизация"],
        ["Риски и неопределённость", "sppr/risk.py", "дерево решений, Монте-Карло, критерии выбора стратегии", "затраты с учётом риска"],
        ["Оптимизация", "sppr/optimize.py", "план закупки при ограничениях (PuLP, CBC)", "рекомендации"],
        ["База знаний", "sppr/kb.py, kb/*.owl", "онтология, 15 правил, логический вывод с объяснениями", "допуск для оптимизации"],
        ["Прогноз и BI", "sppr/forecast.py, bi/", "прогноз курса и цен, дашборд Apache Superset", "порог пересмотра решения"],
        ["Рекомендации", "sppr/recommend.py", "выбор, объём, действия, объяснения", "интерфейс ЛПР"],
    ], columns=["Компонент", "Где", "Что делает", "Кому передаёт"]), hide_index=True, width="stretch")
    st.markdown("Изменение параметров слева запускает цепочку: **база знаний → ранжирование → оптимизация → имитация рисков → рекомендации**.  \n"
                "Ограничения прототипа: цены - публичные ориентиры, а не коммерческие предложения; вероятности исходов поставки и оценки 1-5 - экспертные; "
                "одна типовая модель на поставщика; прогноз курса близок к случайному блужданию.")
    st.markdown("Репозиторий: https://github.com/AndrewFalse/sppr-supplier-selection")
