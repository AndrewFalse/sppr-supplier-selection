"""Правила перевода открытых сведений о поставщике в оценки 1-5 и модельные значения.

Все оценки - экспертные оценки аналитика по явным правилам (не фактические измерения).
Каждая функция возвращает (значение, пояснение), чтобы в отчёте было видно происхождение цифры.
"""

RUSSIAN = "russian_manufacturer"
OFFICIAL = "official_distributor"
PARALLEL = "left_ru_parallel_import"
EXCLUDED = "left_ru_excluded_from_parallel_import"

# Модельный срок поставки (недели), если продавец срок не указал
DEFAULT_LEAD_WEEKS = {RUSSIAN: 3, OFFICIAL: 3, PARALLEL: 8, EXCLUDED: 12, "unknown": 6}
DEFAULT_WARRANTY_MONTHS = 12


MAX_LEAD_WEEKS = 12


def is_russia(text):
    return (text or "").strip().lower().startswith(("россия", "рф", "russia"))


def lead_time_model(row):
    if row.get("unavailable") == "yes":
        return float(MAX_LEAD_WEEKS), "товар фактически недоступен - верхняя граница срока"
    weeks, basis = row.get("lead_time_weeks"), row.get("lead_time_basis")
    if weeks not in (None, "") and basis in ("stated", "in_stock"):
        return float(weeks), "указано продавцом"
    status = row.get("ru_status") or "unknown"
    return float(DEFAULT_LEAD_WEEKS.get(status, 6)), f"модельное значение для канала «{status}»"


def warranty_model(row):
    months = row.get("warranty_months")
    if months not in (None, ""):
        return float(months), "указано " + ("вендором" if row.get("warranty_basis") == "vendor" else "продавцом")
    return float(DEFAULT_WARRANTY_MONTHS), "модельное значение (типовая гарантия продавца)"


def reliability(row, lead_weeks):
    """k3: надёжность поставщика (max). Наличие и срок + официальность канала."""
    if row.get("unavailable") == "yes":
        return 1, "товар фактически недоступен у продавцов"
    trusted = row.get("ru_status") in (RUSSIAN, OFFICIAL)
    if lead_weeks <= 1:
        r = 5 if trusted else 4
    elif lead_weeks <= 4:
        r = 4 if trusted else 3
    elif lead_weeks <= 8:
        r = 3 if trusted else 2
    else:
        r = 2 if trusted else 1
    canal = "официальный/российский канал" if trusted else "неофициальный канал"
    return r, f"срок {lead_weeks:g} нед., {canal}"


def sanction_risk(row):
    """k6: санкционный риск канала (min): 1 - нет риска, 5 - очень высокий."""
    mapping = {
        RUSSIAN: (1, "российский производитель"),
        OFFICIAL: (2, "иностранный вендор с официальным дистрибьютором в РФ"),
        PARALLEL: (4, "вендор ушёл из РФ, поставки через параллельный импорт"),
        EXCLUDED: (5, "вендор ушёл из РФ, продукция исключена из перечня параллельного импорта"),
    }
    return mapping.get(row.get("ru_status"), (3, "статус в РФ не подтверждён"))


def russian_origin(row):
    """k7: российское происхождение (max)."""
    vendor_ru = is_russia(row.get("vendor_country"))
    prod_ru = is_russia(row.get("production_country"))
    if vendor_ru and prod_ru and row.get("registry_ru") == "yes":
        return 5, "российский производитель, запись в реестре"
    if vendor_ru and prod_ru:
        return 4, "российский производитель, производство в РФ"
    if vendor_ru:
        return 3, "российский бренд, производство за рубежом"
    return 1, "иностранный вендор"
