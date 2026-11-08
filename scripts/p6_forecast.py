"""Практика №6: прогноз курса и цен оборудования, прогноз стоимости плана закупки, витрина данных для BI.

Вход:  data/raw/cbr_fx.csv (+ cbr_fx_update.csv - данные после 03.10.2026 для отложенной проверки),
       data/raw/cbr_key_rate.csv (+ _update), data/raw/rosstat_ppi.csv, config/p6_forecast.json,
       outputs/p4/plan_base.csv, outputs/p3/vendors_params.csv, outputs/p5/inference_base.csv
Выход: outputs/p6/*.csv, summary.json, fx_forecast.png, sppr_bi.db (SQLite-витрина для Superset)
Запуск: .venv/bin/python scripts/p6_forecast.py
"""
import json
import sqlite3
import sys
from pathlib import Path

import matplotlib
import matplotlib.ticker
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sppr import forecast as fc  # noqa: E402

OUT = ROOT / "outputs" / "p6"
RAW = ROOT / "data" / "raw"


def load_fx(cfg):
    base = pd.read_csv(RAW / "cbr_fx.csv", parse_dates=["date"])
    upd = pd.read_csv(RAW / "cbr_fx_update.csv", parse_dates=["date"])
    fx = pd.concat([base, upd]).drop_duplicates(["date", "currency"]).sort_values("date")
    cutoff = base["date"].max()                                   # конец снимка, на котором обучались практики 2-5
    wide = fx.pivot(index="date", columns="currency", values="rate_rub_per_unit").sort_index()
    counts = wide.resample(cfg["week_rule"]).count().min(axis=1)
    weekly = wide.resample(cfg["week_rule"]).mean().dropna()
    weekly = weekly[counts.reindex(weekly.index) >= cfg["min_obs_per_week"]]   # неполные недели (1-2 дня) не берём
    key = pd.concat([pd.read_csv(RAW / "cbr_key_rate.csv", parse_dates=["date"]),
                     pd.read_csv(RAW / "cbr_key_rate_update.csv", parse_dates=["date"])]).drop_duplicates("date")
    key = key.set_index("date")["key_rate_pct"].sort_index().resample(cfg["week_rule"]).last().ffill()
    weekly["key_rate"] = key.reindex(weekly.index).ffill()
    return weekly[weekly.index >= cfg["since"]], cutoff, fx


def load_ppi(codes):
    ppi = pd.read_csv(RAW / "rosstat_ppi.csv", parse_dates=["date"])
    out = {}
    for code in codes:
        s = ppi[ppi.indicator == f"ppi_mom_okved2_{code}"].set_index("date")["value"].sort_index()
        out[code] = 100 * (s / 100).cumprod()                       # уровень цен, январь 2021 = 100 (на конец месяца)
    return pd.DataFrame(out)


def backtest_and_select(y, factories, horizon, start, step, exog=None, dates=None, calib_share=0.6):
    bt = fc.rolling_backtest(y, factories, horizon, start, step, exog, dates)
    met = fc.metrics(bt)
    best = met.index[0]
    origins = sorted(bt.origin.unique())
    cut = origins[int(len(origins) * calib_share)]
    q_cal = fc.conformal_quantiles(bt[(bt.model == best) & (bt.origin < cut)])
    cov80 = fc.coverage(bt[(bt.model == best) & (bt.origin >= cut)], q_cal, 0.8)
    q_all = fc.conformal_quantiles(bt[bt.model == best])
    return bt, met, best, q_all, cov80, len(origins)


def plan_cost(plan, vend, fx_path, ppi_path, rate_price, ppi_price, cat_ppi):
    """Стоимость плана практики №4 при прогнозных курсе и ценах: часть, зависящая от курса (доля e из практики №3),
    пересчитывается по курсу, остальное - по индексу цен производителей соответствующей отрасли."""
    items = plan.merge(vend[["category", "vendor", "exposure"]], on=["category", "vendor"])
    out = []
    for i in range(len(fx_path)):
        row = {}
        for col in ("point", "lo80", "hi80"):
            total = 0.0
            for it in items.itertuples():
                code = cat_ppi[it.category]
                fx_ratio = fx_path[col].iloc[i] / rate_price
                ppi_ratio = ppi_path[code][col].iloc[i] / ppi_price[code]
                total += it.complexes * it.unit_cost * (it.exposure * fx_ratio + (1 - it.exposure) * ppi_ratio)
            row[col] = total
        out.append(row)
    return pd.DataFrame(out)


def draw_fx(hist, fut, holdout, path):
    plt.rcParams.update({"font.family": ["Arial", "DejaVu Sans"], "font.size": 8})
    fig, ax = plt.subplots(figsize=(6.2, 2.9), dpi=300)
    h = hist[hist.index >= hist.index.max() - pd.Timedelta(weeks=78)]
    ax.plot(h.index, h.values, color="black", lw=0.9, label="факт (ЦБ РФ)")
    ax.fill_between(fut.index, fut.lo95, fut.hi95, color="#e3e3e3", lw=0, label="интервал 95 %")
    ax.fill_between(fut.index, fut.lo80, fut.hi80, color="#bdbdbd", lw=0, label="интервал 80 %")
    ax.plot(fut.index, fut.point, color="black", lw=0.9, ls="--", label="прогноз")
    ax.plot(holdout.index, holdout.pred, "o", ms=2.5, mfc="white", mec="black", mew=0.7, label="проверка: прогноз от 02.10")
    comma = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}")
    ax.yaxis.set_major_formatter(comma)
    ax.set_ylabel("руб. за доллар США")
    ax.grid(True, color="#d9d9d9", lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=6.5, ncol=3, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / "config" / "p6_forecast.json").read_text(encoding="utf-8"))
    H = cfg["fx_horizon_weeks"]
    weekly, cutoff, fx_daily = load_fx(cfg)
    usd = weekly["USD"]
    train_mask = weekly.index <= cutoff
    y_train, k_train = usd[train_mask].values, weekly["key_rate"][train_mask].values
    factories = {"Случайное блуждание": fc.Naive, "Дрейф": fc.Drift, "Хольт с затухающим трендом": fc.HoltDamped,
                 "Градиентный бустинг": lambda: fc.GBReturns(H)}

    # 1. Курс USD: скользящая проверка на обучающем периоде
    bt, met, best, q, cov80, n_orig = backtest_and_select(
        y_train, factories, H, cfg["backtest_start_weeks"], cfg["backtest_step_weeks"], k_train, usd.index[train_mask])
    bt.to_csv(OUT / "fx_backtest.csv", index=False, float_format="%.5f")
    met.to_csv(OUT / "fx_metrics.csv", float_format="%.5f")

    # 2. Отложенная проверка: прогноз от последней недели снимка на недели после 03.10.2026
    hold_idx = usd.index[~train_mask]
    hold_rows = []
    for name, make in factories.items():
        pred = make().fit(y_train, k_train).predict(len(hold_idx))
        for i, d in enumerate(hold_idx):
            hold_rows.append({"date": d, "model": name, "h": i + 1, "actual": usd.loc[d], "pred": pred[i]})
    hold = pd.DataFrame(hold_rows)
    hold["err_pct"] = hold.actual / hold.pred - 1
    hb = hold[hold.model == best].set_index("date")
    hb["lo80"] = [p * (1 + q[h][0.8][0]) for p, h in zip(hb.pred, hb.h)]
    hb["hi80"] = [p * (1 + q[h][0.8][1]) for p, h in zip(hb.pred, hb.h)]
    hold_mape = hold.groupby("model")["err_pct"].apply(lambda s: float(s.abs().mean()))
    hold_cov = float(((hb.actual >= hb.lo80) & (hb.actual <= hb.hi80)).mean())
    hold.to_csv(OUT / "fx_holdout.csv", index=False, float_format="%.5f")

    # 3. Итоговый прогноз на H недель от последних данных
    model = factories[best]().fit(usd.values, weekly["key_rate"].values)
    fut_dates = pd.date_range(usd.index[-1], periods=H + 1, freq=cfg["week_rule"])[1:]
    fut = fc.with_intervals(model.predict(H), q).set_index(fut_dates)
    fut.to_csv(OUT / "fx_forecast.csv", float_format="%.4f")

    # 4. Индексы цен производителей (Росстат): месячный прогноз
    ppi = load_ppi(cfg["ppi_codes"].keys())
    Hm = cfg["ppi_horizon_months"]
    ppi_fac = {"Случайное блуждание": fc.Naive, "Дрейф": fc.Drift, "Хольт с затухающим трендом": fc.HoltDamped}
    ppi_fut, ppi_met = {}, []
    for code in cfg["ppi_codes"]:
        s = ppi[code].dropna()
        bt_p, met_p, best_p, q_p, cov_p, n_p = backtest_and_select(s.values, ppi_fac, Hm, cfg["ppi_backtest_start"], 1)
        m = ppi_fac[best_p]().fit(s.values)
        idx = pd.date_range(s.index[-1], periods=Hm + 1, freq="MS")[1:]
        ppi_fut[code] = fc.with_intervals(m.predict(Hm), q_p).set_index(idx)
        for name, r in met_p.iterrows():
            ppi_met.append({"okved": code, "model": name, "mape": r.mape, "mape_hmax": r.mape_hmax,
                            "selected": name == best_p, "coverage80_test": cov_p if name == best_p else None})
    ppi_met = pd.DataFrame(ppi_met)
    ppi_met.to_csv(OUT / "ppi_metrics.csv", index=False, float_format="%.5f")

    # 5. Стоимость плана практики №4: при цене на дату снимка цен и через 1-3 месяца
    plan = pd.read_csv(ROOT / "outputs" / "p4" / "plan_base.csv")
    vend = pd.read_csv(ROOT / "outputs" / "p3" / "vendors_params.csv")
    price_date = pd.Timestamp(cfg["price_snapshot_date"])
    rate_price = float(fx_daily[(fx_daily.currency == "USD") & (fx_daily.date <= price_date)].sort_values("date").iloc[-1].rate_rub_per_unit)
    ppi_month = lambda code, d: ppi_fut[code]["point"].asof(d.to_period("M").to_timestamp()) \
        if d > ppi[code].dropna().index[-1] else float(ppi[code].asof(d))
    ppi_price = {code: ppi_month(code, price_date) for code in cfg["ppi_codes"]}
    ppi_path = {code: pd.DataFrame({col: [ppi_fut[code][col].asof(d.to_period("M").to_timestamp()) for d in fut.index]
                                    for col in ("point", "lo80", "hi80")}) for code in cfg["ppi_codes"]}
    fx_path = fut[["point", "lo80", "hi80"]].reset_index(drop=True)
    snapshot_cost = float((plan.complexes * plan.unit_cost).sum())        # по ценам на дату проверки цен
    now_month = usd.index[-1].to_period("M").to_timestamp()
    now_path = pd.DataFrame({"point": [float(usd.iloc[-1])], "lo80": [float(usd.iloc[-1])], "hi80": [float(usd.iloc[-1])]})
    now_ppi = {code: pd.DataFrame({col: [ppi_month(code, usd.index[-1])] for col in ("point", "lo80", "hi80")})
               for code in cfg["ppi_codes"]}
    now_cost = float(plan_cost(plan, vend, now_path, now_ppi, rate_price, ppi_price, cfg["category_ppi"]).point.iloc[0])
    cost = plan_cost(plan, vend, fx_path, ppi_path, rate_price, ppi_price, cfg["category_ppi"])
    cost.index = fut.index
    cost.to_csv(OUT / "plan_cost_forecast.csv", float_format="%.0f")
    key_now = float(weekly["key_rate"].iloc[-1]) / 100
    timing = []
    for wk in cfg["report_weeks"]:
        c = cost.iloc[wk - 1]
        hold_cost = now_cost * key_now * wk / 52
        timing.append({"weeks": wk, "date": cost.index[wk - 1].date().isoformat(), "cost_point": c.point,
                       "cost_lo80": c.lo80, "cost_hi80": c.hi80, "change_pct": c.point / now_cost - 1,
                       "holding_cost_if_bought_now": hold_cost,
                       "buy_now_better": bool(c.point - now_cost > hold_cost)})
    timing = pd.DataFrame(timing)
    timing.to_csv(OUT / "plan_timing.csv", index=False, float_format="%.4f")

    draw_fx(usd, fut, hb, OUT / "fx_forecast.png")

    # 6. Витрина данных для Superset (SQLite)
    db = OUT / "sppr_bi.db"
    if db.exists():
        db.unlink()
    with sqlite3.connect(db) as con:
        hist = usd.rename("value").reset_index().rename(columns={"date": "week"})
        series = pd.concat([
            hist.assign(series="факт"),
            fut.reset_index().rename(columns={"index": "week"})[["week", "point"]].rename(columns={"point": "value"}).assign(series="прогноз"),
            fut.reset_index().rename(columns={"index": "week"})[["week", "lo80"]].rename(columns={"lo80": "value"}).assign(series="нижняя граница 80 %"),
            fut.reset_index().rename(columns={"index": "week"})[["week", "hi80"]].rename(columns={"hi80": "value"}).assign(series="верхняя граница 80 %"),
        ])
        series["week"] = series["week"].dt.strftime("%Y-%m-%d")
        series.to_sql("fx_usd", con, index=False)
        ppi_rows = []
        for code, label in cfg["ppi_codes"].items():
            for d, v in ppi[code].dropna().items():
                ppi_rows.append({"month": d.strftime("%Y-%m-%d"), "okved": label, "series": "факт", "value": v})
            for d, r in ppi_fut[code].iterrows():
                ppi_rows.append({"month": d.strftime("%Y-%m-%d"), "okved": label, "series": "прогноз", "value": r.point})
        pd.DataFrame(ppi_rows).to_sql("ppi_index", con, index=False)
        cst = cost.reset_index().rename(columns={"index": "week"})
        cst["week"] = cst["week"].dt.strftime("%Y-%m-%d")
        cst.rename(columns={"point": "cost_point", "lo80": "cost_lo80", "hi80": "cost_hi80"}).assign(
            cost_now=now_cost).to_sql("plan_cost", con, index=False)
        plan.assign(cost=plan.complexes * plan.unit_cost).to_sql("plan_items", con, index=False)
        flags = pd.read_csv(ROOT / "outputs" / "p5" / "inference_base.csv").fillna("")
        adm = flags["admissible"].astype(str).str.lower() == "true"
        flags["conclusion"] = np.where(~adm, "недопустима: " + flags["exclusion_reason"], flags["flags"])
        flags[flags.conclusion != ""][["category", "vendor", "conclusion"]].to_sql("kb_flags", con, index=False)
        met.reset_index().rename(columns={"index": "model"}).assign(
            holdout_mape=lambda df: df.model.map(hold_mape)).to_sql("model_metrics", con, index=False)
        kpi = {"usd_now": float(usd.iloc[-1]), "usd_h": float(fut.point.iloc[-1]), "usd_h_lo80": float(fut.lo80.iloc[-1]),
               "usd_h_hi80": float(fut.hi80.iloc[-1]), "plan_cost_now": now_cost,
               "plan_cost_3m": float(cost.point.iloc[-1]), "holdout_mape_pct": float(hold_mape[best] * 100),
               "coverage80_test_pct": cov80 * 100}
        pd.DataFrame([kpi]).to_sql("kpi", con, index=False)

    summary = {"cutoff": str(cutoff.date()), "last_week": str(usd.index[-1].date()), "weeks_train": int(train_mask.sum()),
               "holdout_weeks": len(hold_idx), "backtest_origins": n_orig, "best_model": best,
               "metrics": met.to_dict("index"), "coverage80_test": cov80, "holdout_mape": hold_mape.to_dict(),
               "holdout_coverage80": hold_cov, "holdout": hb[["actual", "pred", "lo80", "hi80"]].reset_index().assign(
                   date=lambda df: df.date.dt.date.astype(str)).to_dict("records"),
               "forecast_end": {"date": str(fut.index[-1].date()), **fut.iloc[-1].to_dict()},
               "usd_now": float(usd.iloc[-1]), "rate_price_date": rate_price, "plan_cost_now": now_cost,
               "plan_cost_snapshot": snapshot_cost, "key_rate_now": key_now,
               "timing": timing.to_dict("records"), "ppi_selected": ppi_met[ppi_met.selected].to_dict("records"),
               "ppi_forecast_end": {c: ppi_fut[c].iloc[-1].to_dict() for c in ppi_fut},
               "ppi_last": {c: {"date": str(ppi[c].dropna().index[-1].date()), "value": float(ppi[c].dropna().iloc[-1])} for c in ppi},
               "holt_params": {k: float(getattr(model, k)) for k in ("alpha", "beta", "phi")} if hasattr(model, "alpha") else None}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    pd.set_option("display.width", 200)
    print(f"Недель обучения: {summary['weeks_train']}, проверок: {n_orig}, отложенных недель: {len(hold_idx)}")
    print(met.to_string(float_format=lambda v: f"{v:.4f}"))
    print("Лучшая модель:", best, "| покрытие 80 % на проверочных точках:", round(cov80, 3))
    print("Отложенная проверка MAPE:", {k: round(v * 100, 2) for k, v in hold_mape.items()}, "| покрытие 80 %:", hold_cov)
    print(hb[["actual", "pred", "lo80", "hi80"]].round(2).to_string())
    print("Прогноз на конец горизонта:", summary["forecast_end"])
    print(ppi_met.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print(timing.to_string(index=False, float_format=lambda v: f"{v:.4f}" if abs(v) < 5 else f"{v / 1e6:.3f}"))


if __name__ == "__main__":
    main()
