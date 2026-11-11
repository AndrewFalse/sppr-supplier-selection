"""Сборка дашборда ЛПР в Apache Superset через REST API (практика №6).

Создаёт подключение к витрине outputs/p6/sppr_bi.db, наборы данных, графики и дашборд,
проверяет, что каждый график возвращает данные, и сохраняет экспорт дашборда в bi/dashboard_export.zip.
Запуск: автоматически сервисом dashboard-init (docker compose up) или вручную:
    python bi/build_dashboard.py   (Superset на localhost:8088, учётные данные - из bi/.env)
"""
import json
import os
from pathlib import Path

import requests

BI = Path(__file__).resolve().parent
URL = os.environ.get("SUPERSET_URL", "http://localhost:8088")
DB_NAME = "СППР: витрина практики 6"
DB_URI = "sqlite:////app/sppr_data/sppr_bi.db"
TITLE = "СППР: прогноз курса, цены и план закупки"
SLUG = "sppr"

# наборы данных: таблица -> (временная колонка, подписи колонок)
DATASETS = {
    "kpi": (None, {}),
    "fx_usd": ("week", {"week": "Неделя", "value": "Курс, руб./долл.", "series": "Ряд"}),
    "ppi_index": ("month", {"month": "Месяц", "value": "Индекс цен (янв. 2021 = 100)", "okved": "Отрасль", "series": "Ряд"}),
    "plan_cost": ("week", {"week": "Неделя"}),
    "plan_items": (None, {"category": "Категория", "vendor": "Поставщик", "complexes": "Комплексов", "cost": "Стоимость, руб."}),
    "kb_flags": (None, {"category": "Категория", "vendor": "Поставщик", "conclusion": "Заключение базы знаний"}),
    "model_metrics": (None, {"model": "Модель", "mape": "MAPE, проверка", "mape_hmax": "MAPE, 13 недель",
                             "holdout_mape": "MAPE, отложенная проверка", "mae": "MAE, руб."}),
}


def env():
    """Учётные данные: из bi/.env, переменные окружения имеют приоритет (запуск в контейнере)."""
    vals = {}
    f = BI / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    for k in ("SUPERSET_ADMIN_USER", "SUPERSET_ADMIN_PASSWORD"):
        if os.environ.get(k):
            vals[k] = os.environ[k]
    return vals


def session():
    e = env()
    s = requests.Session()
    tok = s.post(f"{URL}/api/v1/security/login", json={"username": e.get("SUPERSET_ADMIN_USER", "admin"),
                                                      "password": e["SUPERSET_ADMIN_PASSWORD"], "provider": "db",
                                                      "refresh": True}, timeout=60).json()["access_token"]
    s.headers.update({"Authorization": f"Bearer {tok}", "Referer": URL})
    csrf = s.get(f"{URL}/api/v1/security/csrf_token/", timeout=60).json()["result"]
    s.headers.update({"X-CSRFToken": csrf})
    return s


def call(s, method, path, **kw):
    r = s.request(method, f"{URL}{path}", timeout=120, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:500]}")
    return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r


def find(s, resource, col, value):
    q = f"(filters:!((col:{col},opr:eq,value:'{value}')))"
    res = call(s, "GET", f"/api/v1/{resource}/", params={"q": q})["result"]
    return res[0]["id"] if res else None


def metric(sql, label):
    return {"expressionType": "SQL", "sqlExpression": sql, "label": label}


def main():
    s = session()
    # 1. удалить прежний дашборд и графики, чтобы повторный запуск не дублировал объекты
    old = find(s, "dashboard", "slug", SLUG)
    if old:
        charts = call(s, "GET", f"/api/v1/dashboard/{old}/charts")["result"]
        call(s, "DELETE", f"/api/v1/dashboard/{old}")
        for c in charts:
            call(s, "DELETE", f"/api/v1/chart/{c['id']}")
    db_id = find(s, "database", "database_name", DB_NAME) or call(s, "POST", "/api/v1/database/", json={
        "database_name": DB_NAME, "sqlalchemy_uri": DB_URI, "expose_in_sqllab": True})["id"]

    # 2. наборы данных
    ds = {}
    for table, (dttm, labels) in DATASETS.items():
        existing = call(s, "GET", "/api/v1/dataset/", params={"q": f"(filters:!((col:table_name,opr:eq,value:{table})))"})["result"]
        existing = [d for d in existing if d.get("database", {}).get("id") == db_id]
        did = existing[0]["id"] if existing else call(s, "POST", "/api/v1/dataset/", json={"database": db_id, "table_name": table})["id"]
        call(s, "PUT", f"/api/v1/dataset/{did}/refresh")
        info = call(s, "GET", f"/api/v1/dataset/{did}")["result"]
        cols = [{"id": c["id"], "column_name": c["column_name"], "type": c.get("type"),
                 "is_dttm": c["column_name"] == dttm, "python_date_format": "%Y-%m-%d" if c["column_name"] == dttm else None,
                 "verbose_name": labels.get(c["column_name"]), "filterable": True, "groupby": True}
                for c in info["columns"]]
        call(s, "PUT", f"/api/v1/dataset/{did}", json={"columns": cols, "main_dttm_col": dttm})
        ds[table] = did

    # 3. дашборд и графики
    dash = call(s, "POST", "/api/v1/dashboard/", json={"dashboard_title": TITLE, "slug": SLUG, "published": True})["id"]
    def chart(name, viz, table, params):
        form = {"viz_type": viz, "datasource": f"{ds[table]}__table", **params}
        return call(s, "POST", "/api/v1/chart/", json={"slice_name": name, "viz_type": viz, "datasource_id": ds[table],
                                                       "datasource_type": "table", "params": json.dumps(form, ensure_ascii=False),
                                                       "dashboards": [dash]})["id"]
    big = lambda col, label, fmt, sub: {"metric": metric(f"MAX({col})", label), "subheader": sub, "y_axis_format": fmt,
                                        "header_font_size": 0.3, "subheader_font_size": 0.15}
    c = {}
    c["usd_now"] = chart("Курс USD сейчас", "big_number_total", "kpi", big("usd_now", "Курс", ",.2f", "руб. за доллар, неделя ЦБ"))
    c["usd_h"] = chart("Прогноз курса через 13 недель", "big_number_total", "kpi", big("usd_h", "Прогноз", ",.2f", "руб. за доллар (интервал 80 % - на графике)"))
    c["cost_now"] = chart("Стоимость сейчас", "big_number_total", "kpi", big("plan_cost_now / 1e6", "Стоимость", ",.2f", "млн руб., план практики 4"))
    c["cost_3m"] = chart("Через 3 месяца", "big_number_total", "kpi", big("plan_cost_3m / 1e6", "Стоимость", ",.2f", "млн руб., прогноз стоимости плана"))
    c["mape"] = chart("Ошибка прогноза", "big_number_total", "kpi", big("holdout_mape_pct", "MAPE", ",.1f", "%, отложенная проверка (5 недель)"))
    line_common = {"x_axis": "week", "time_grain_sqla": "P1W", "groupby": ["series"], "row_limit": 10000,
                   "show_legend": True, "legendOrientation": "top", "rich_tooltip": True, "y_axis_format": ",.1f",
                   "markerEnabled": False, "zoomable": True, "truncateYAxis": True, "y_axis_bounds": [None, None]}
    c["fx"] = chart("Курс USD/RUB: факт и прогноз с интервалом 80 %", "echarts_timeseries_line", "fx_usd",
                    {**line_common, "metrics": [metric("MAX(value)", "руб./долл.")]})
    c["ppi"] = chart("Индексы цен производителей: факт и прогноз", "echarts_timeseries_line", "ppi_index",
                     {**line_common, "x_axis": "month", "time_grain_sqla": "P1M", "groupby": ["okved", "series"],
                      "metrics": [metric("MAX(value)", "индекс")]})
    c["cost"] = chart("Прогноз стоимости плана, млн руб.", "echarts_timeseries_line", "plan_cost",
                      {**line_common, "groupby": [], "metrics": [metric("MAX(cost_point) / 1e6", "прогноз"),
                                                                 metric("MAX(cost_lo80) / 1e6", "нижняя граница 80 %"),
                                                                 metric("MAX(cost_hi80) / 1e6", "верхняя граница 80 %"),
                                                                 metric("MAX(cost_now) / 1e6", "покупка сейчас")],
                       "y_axis_format": ",.2f"})
    c["plan"] = chart("План закупки практики 4: стоимость по категориям", "echarts_timeseries_bar", "plan_items",
                      {"x_axis": "category", "metrics": [metric("SUM(cost) / 1e6", "млн руб.")], "groupby": ["vendor"],
                       "stack": "Stack", "row_limit": 1000, "show_legend": True, "legendOrientation": "top",
                       "y_axis_format": ",.2f", "x_axis_sort_asc": True, "orientation": "vertical"})
    c["kb"] = chart("Предупреждения базы знаний (практика 5)", "table", "kb_flags",
                    {"query_mode": "raw", "all_columns": ["category", "vendor", "conclusion"], "row_limit": 100,
                     "include_search": False, "page_length": 0})
    c["metrics"] = chart("Точность моделей прогноза курса", "table", "model_metrics",
                         {"query_mode": "raw", "all_columns": ["model", "mape", "mape_hmax", "holdout_mape", "mae"],
                          "row_limit": 10, "column_config": {k: {"d3NumberFormat": ".1%"} for k in ("mape", "mape_hmax", "holdout_mape")} |
                          {"mae": {"d3NumberFormat": ",.2f"}}})

    # 4. раскладка: строка показателей, два графика, план и стоимость, таблицы
    rows = [[("usd_now", 3), ("usd_h", 3), ("cost_now", 2), ("cost_3m", 2), ("mape", 2)],
            [("fx", 7), ("cost", 5)], [("plan", 6), ("ppi", 6)], [("kb", 7), ("metrics", 5)]]
    heights = [26, 60, 60, 55]
    pos = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": TITLE}}}
    for i, (row, hgt) in enumerate(zip(rows, heights), start=1):
        rid = f"ROW-{i}"
        pos["GRID_ID"]["children"].append(rid)
        pos[rid] = {"type": "ROW", "id": rid, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                    "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for key, width in row:
            cid = f"CHART-{key}"
            pos[rid]["children"].append(cid)
            pos[cid] = {"type": "CHART", "id": cid, "children": [], "parents": ["ROOT_ID", "GRID_ID", rid],
                        "meta": {"chartId": c[key], "width": width, "height": hgt}}
    grey, blue, orange = "#9E9E9E", "#4C78A8", "#F58518"
    label_colors = {"факт": blue, "прогноз": orange, "нижняя граница 80 %": grey, "верхняя граница 80 %": grey,
                    "покупка сейчас": blue}
    call(s, "PUT", f"/api/v1/dashboard/{dash}", json={"position_json": json.dumps(pos, ensure_ascii=False),
                                                     "json_metadata": json.dumps({"color_scheme": "", "refresh_frequency": 0,
                                                                                  "label_colors": label_colors}, ensure_ascii=False)})

    # 5. проверка: запрос данных с показателями и группировками каждого графика должен выполниться без ошибок
    report = {}
    for key, cid in c.items():
        form = json.loads(call(s, "GET", f"/api/v1/chart/{cid}")["result"]["params"])
        metrics = form.get("metrics") or ([form["metric"]] if form.get("metric") else [])
        columns = [x for x in [form.get("x_axis")] + form.get("groupby", []) if x] or form.get("all_columns", [])
        q = {"datasource": {"id": int(form["datasource"].split("__")[0]), "type": "table"},
             "queries": [{"metrics": metrics, "columns": columns, "row_limit": 10000, "orderby": []}],
             "result_format": "json", "result_type": "full"}
        res = call(s, "POST", "/api/v1/chart/data", json=q)["result"][0]
        report[key] = {"rows": res.get("rowcount"), "error": res.get("error")}
    zip_bytes = s.get(f"{URL}/api/v1/dashboard/export/", params={"q": f"!({dash})"}, timeout=120).content
    (BI / "dashboard_export.zip").write_bytes(zip_bytes)
    print(json.dumps({"dashboard_id": dash, "url": f"{URL}/superset/dashboard/{SLUG}/", "charts": report},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
