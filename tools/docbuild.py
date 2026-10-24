"""Сборка раздела паспорта СППР в ПУСТОМ (или своём) Google Doc из описания блоков.

Блоки: ("title"|"subtitle"|"author"|"h1"|"h2"|"p"|"p0"|"caption"|"formula"|"note", текст) и ("table", имя).
Таблицы: {имя: {"cols": [ширины pt], "rows": [[ячейки]], "align": [START|CENTER по колонкам]}}.
Разметка в тексте: **жирный**, _{подстрочный}, ^{надстрочный}.
ВНИМАНИЕ: build() очищает документ целиком - только для документа, который мы ведём сами
и в котором нет правок пользователя (проверять перед запуском).
"""
import gdoc
from gdoc import BLACK, FONT, IND, MM, batch, get, parse, pt, ptext, cell_text

BORDER = {"color": {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}}, "width": pt(0.5), "dashStyle": "SOLID"}
FIG_RESERVE = {"pt": 0}   # временный резерв высоты рисунка для проверки вёрстки


def set_fig_reserve(prefix, reserve_pt):
    """Меняет верхний отступ абзаца-заглушки рисунка (по началу текста)."""
    reqs = []
    for el in get()["body"]["content"]:
        if "paragraph" in el and ptext(el).startswith(prefix):
            reqs.append({"updateParagraphStyle": {"range": {"startIndex": el["startIndex"], "endIndex": el["endIndex"]},
                         "paragraphStyle": {"spaceAbove": pt(6 + reserve_pt)}, "fields": "spaceAbove"}})
    batch(reqs)
    return len(reqs)


def _span_reqs(start, spans):
    reqs = []
    for a, b, kind in spans:
        style, field = ({"bold": True}, "bold") if kind == "bold" else \
            ({"baselineOffset": "SUBSCRIPT" if kind == "sub" else "SUPERSCRIPT"}, "baselineOffset")
        reqs.append({"updateTextStyle": {"range": {"startIndex": start + a, "endIndex": start + b},
                                         "textStyle": style, "fields": field}})
    return reqs


def _text_stage(blocks):
    d = get()
    end = d["body"]["content"][-1]["endIndex"]
    if end > 2:
        batch([{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}}])
    paras, pos, texts = [], 1, []
    for kind, raw in blocks:
        plain, spans = (f"[[{raw}]]", []) if kind == "table" else parse(raw)
        paras.append({"kind": kind, "start": pos, "end": pos + len(plain) + 1, "spans": spans})
        pos += len(plain) + 1
        texts.append(plain)
    full = "\n".join(texts)
    body_end = 1 + len(full) + 1
    reqs = [{"updateDocumentStyle": {"documentStyle": {
        "pageSize": {"width": pt(595.28), "height": pt(841.89)},
        "marginLeft": pt(30 * MM), "marginRight": pt(15 * MM), "marginTop": pt(20 * MM), "marginBottom": pt(20 * MM)},
        "fields": "pageSize,marginLeft,marginRight,marginTop,marginBottom"}},
        {"insertText": {"location": {"index": 1}, "text": full}}]
    for p in paras:
        if p["kind"] in ("h1", "h2"):
            reqs.append({"updateParagraphStyle": {"range": {"startIndex": p["start"], "endIndex": p["end"]},
                "paragraphStyle": {"namedStyleType": "HEADING_1" if p["kind"] == "h1" else "HEADING_2"}, "fields": "namedStyleType"}})
    R = {"startIndex": 1, "endIndex": body_end}
    reqs += [
        {"updateTextStyle": {"range": R, "textStyle": {"weightedFontFamily": {"fontFamily": FONT}, "fontSize": pt(12),
            "foregroundColor": BLACK, "bold": False, "italic": False, "underline": False},
            "fields": "weightedFontFamily,fontSize,foregroundColor,bold,italic,underline"}},
        {"updateParagraphStyle": {"range": R, "paragraphStyle": {"alignment": "JUSTIFIED", "lineSpacing": 150,
            "indentFirstLine": pt(IND), "indentStart": pt(0), "spaceAbove": pt(0), "spaceBelow": pt(0)},
            "fields": "alignment,lineSpacing,indentFirstLine,indentStart,spaceAbove,spaceBelow"}},
    ]

    def pst(p, style):
        reqs.append({"updateParagraphStyle": {"range": {"startIndex": p["start"], "endIndex": p["end"]},
                     "paragraphStyle": style, "fields": ",".join(style)}})

    for p in paras:
        k = p["kind"]
        if k in ("title", "subtitle", "author"):
            pst(p, {"alignment": "CENTER", "indentFirstLine": pt(0), "lineSpacing": 100 if k == "title" else 150,
                    "spaceBelow": pt(12 if k == "author" else 6)})
            if k == "title":
                reqs.append({"updateTextStyle": {"range": {"startIndex": p["start"], "endIndex": p["end"] - 1},
                             "textStyle": {"bold": True}, "fields": "bold"}})
        elif k in ("h1", "h2"):
            pst(p, {"alignment": "START", "indentFirstLine": pt(IND), "keepWithNext": True,
                    "spaceAbove": pt(12 if k == "h1" else 6), "spaceBelow": pt(6 if k == "h1" else 0), "lineSpacing": 150})
            reqs.append({"updateTextStyle": {"range": {"startIndex": p["start"], "endIndex": p["end"] - 1},
                "textStyle": {"bold": True, "weightedFontFamily": {"fontFamily": FONT}, "fontSize": pt(12),
                              "foregroundColor": BLACK, "italic": False},
                "fields": "bold,weightedFontFamily,fontSize,foregroundColor,italic"}})
        elif k == "caption":
            pst(p, {"alignment": "START", "indentFirstLine": pt(0), "keepWithNext": True, "lineSpacing": 100,
                    "spaceAbove": pt(6), "spaceBelow": pt(3)})
        elif k == "formula":
            pst(p, {"alignment": "CENTER", "indentFirstLine": pt(0), "spaceAbove": pt(3), "spaceBelow": pt(3)})
        elif k == "fig":
            # место под рисунок: высота резервируется отступом reserve (pt), чтобы проверить вёрстку
            pst(p, {"alignment": "CENTER", "indentFirstLine": pt(0), "keepWithNext": True, "lineSpacing": 100,
                    "spaceAbove": pt(6 + FIG_RESERVE.get("pt", 0))})
        elif k == "figcap":
            pst(p, {"alignment": "CENTER", "indentFirstLine": pt(0), "lineSpacing": 100,
                    "spaceAbove": pt(3), "spaceBelow": pt(6)})
        elif k == "p0":
            pst(p, {"indentFirstLine": pt(0)})
        elif k == "table":
            pst(p, {"indentFirstLine": pt(0), "lineSpacing": 100})
        reqs += _span_reqs(p["start"], p["spans"])
    batch(reqs)


def _tables(d):
    return [el for el in d["body"]["content"] if "table" in el]


def _insert_tables(blocks, tables):
    names = [raw for kind, raw in blocks if kind == "table"]
    for name in reversed(names):
        spec = tables[name]
        d = get()
        ph = next(el for el in d["body"]["content"] if "paragraph" in el and ptext(el) == f"[[{name}]]\n")
        s, e = ph["startIndex"], ph["endIndex"]
        batch([{"deleteContentRange": {"range": {"startIndex": s, "endIndex": e - 1}}},
               {"insertTable": {"location": {"index": s}, "rows": len(spec["rows"]), "columns": len(spec["cols"])}}])
        # перед таблицей API создаёт пустой абзац: удаляем перевод строки подписи, сливая её с ним
        body = get()["body"]["content"]
        i = next(i for i, el in enumerate(body) if "table" in el and el["startIndex"] > s - 1)
        stray, cap = body[i - 1], body[i - 2]
        if ptext(stray) == "\n" and ptext(cap).startswith("Таблица"):
            batch([{"deleteContentRange": {"range": {"startIndex": cap["endIndex"] - 1, "endIndex": cap["endIndex"]}}}])
    return names


def _fill_and_style(idx, spec):
    rows, ncols = spec["rows"], len(spec["cols"])
    t = _tables(get())[idx]
    reqs = []
    for r in range(len(rows) - 1, -1, -1):
        for c in range(ncols - 1, -1, -1):
            plain = parse(rows[r][c])[0]
            if plain:
                reqs.append({"insertText": {"location": {"index": t["table"]["tableRows"][r]["tableCells"][c]["content"][0]["startIndex"]},
                                            "text": plain}})
    batch(reqs)
    t = _tables(get())[idx]
    ts = t["startIndex"]
    reqs = [{"updateTableCellStyle": {"tableRange": {"tableCellLocation": {"tableStartLocation": {"index": ts}, "rowIndex": 0,
             "columnIndex": 0}, "rowSpan": len(rows), "columnSpan": ncols},
             "tableCellStyle": {"borderTop": BORDER, "borderBottom": BORDER, "borderLeft": BORDER, "borderRight": BORDER,
                                "paddingTop": pt(1.5), "paddingBottom": pt(1.5), "paddingLeft": pt(3), "paddingRight": pt(3),
                                "contentAlignment": "MIDDLE"},
             "fields": "borderTop,borderBottom,borderLeft,borderRight,paddingTop,paddingBottom,paddingLeft,paddingRight,contentAlignment"}},
            {"pinTableHeaderRows": {"tableStartLocation": {"index": ts}, "pinnedHeaderRowsCount": 1}}]
    for ci, w in enumerate(spec["cols"]):
        reqs.append({"updateTableColumnProperties": {"tableStartLocation": {"index": ts}, "columnIndices": [ci],
                     "tableColumnProperties": {"widthType": "FIXED_WIDTH", "width": pt(w)}, "fields": "widthType,width"}})
    batch(reqs)
    t = _tables(get())[idx]
    ts, te = t["startIndex"], t["endIndex"]
    fsize = spec.get("font_size", 12)
    batch([{"updateTextStyle": {"range": {"startIndex": ts, "endIndex": te}, "textStyle": {
              "weightedFontFamily": {"fontFamily": FONT}, "fontSize": pt(fsize), "foregroundColor": BLACK, "bold": False},
              "fields": "weightedFontFamily,fontSize,foregroundColor,bold"}},
           {"updateParagraphStyle": {"range": {"startIndex": ts, "endIndex": te}, "paragraphStyle": {
              "alignment": "START", "lineSpacing": 100, "indentFirstLine": pt(0), "indentStart": pt(0),
              "spaceAbove": pt(0), "spaceBelow": pt(0)},
              "fields": "alignment,lineSpacing,indentFirstLine,indentStart,spaceAbove,spaceBelow"}}])
    t = _tables(get())[idx]
    align = spec.get("align", ["START"] * ncols)
    reqs = []
    for r, row in enumerate(rows):
        for c, raw in enumerate(row):
            cellj = t["table"]["tableRows"][r]["tableCells"][c]
            a, b = cellj["content"][0]["startIndex"], cellj["content"][-1]["endIndex"]
            al = "CENTER" if r == 0 else align[c]
            if al != "START":
                reqs.append({"updateParagraphStyle": {"range": {"startIndex": a, "endIndex": b},
                             "paragraphStyle": {"alignment": al}, "fields": "alignment"}})
            if r == 0 or (spec.get("bold_first_col") and c == 0):
                reqs.append({"updateTextStyle": {"range": {"startIndex": a, "endIndex": b},
                             "textStyle": {"bold": True}, "fields": "bold"}})
            reqs += _span_reqs(a, parse(raw)[1])
    batch(reqs)
    body = get()["body"]["content"]
    pos = [i for i, el in enumerate(body) if "table" in el][idx]
    cap, after = body[pos - 1], body[pos + 1]
    reqs = [{"updateParagraphStyle": {"range": {"startIndex": after["startIndex"], "endIndex": after["endIndex"]},
             "paragraphStyle": {"indentFirstLine": pt(0), "lineSpacing": 100, "spaceAbove": pt(0), "spaceBelow": pt(0)},
             "fields": "indentFirstLine,lineSpacing,spaceAbove,spaceBelow"}},
            {"updateTextStyle": {"range": {"startIndex": after["startIndex"], "endIndex": after["endIndex"]},
             "textStyle": {"fontSize": pt(2)}, "fields": "fontSize"}}]
    if ptext(cap).startswith("Таблица"):
        reqs += [{"updateParagraphStyle": {"range": {"startIndex": cap["startIndex"], "endIndex": cap["endIndex"]},
                  "paragraphStyle": {"alignment": "START", "indentFirstLine": pt(0), "keepWithNext": True, "lineSpacing": 100,
                                     "spaceAbove": pt(6), "spaceBelow": pt(3)},
                  "fields": "alignment,indentFirstLine,keepWithNext,lineSpacing,spaceAbove,spaceBelow"}},
                 {"updateTextStyle": {"range": {"startIndex": cap["startIndex"], "endIndex": cap["endIndex"] - 1},
                  "textStyle": {"bold": False}, "fields": "bold"}}]
    batch(reqs)


def verify(tables, names):
    tb = _tables(get())
    bad = 0
    for idx, name in enumerate(names):
        for r, row in enumerate(tables[name]["rows"]):
            for c, raw in enumerate(row):
                got = cell_text(tb[idx]["table"]["tableRows"][r]["tableCells"][c])
                if got != parse(raw)[0]:
                    bad += 1
                    print(f"  расхождение {name} r{r}c{c}: {got!r}")
    return bad


def page_break_before(prefixes):
    reqs = []
    for el in get()["body"]["content"]:
        if "paragraph" in el and any(ptext(el).startswith(x) for x in prefixes):
            reqs.append({"updateParagraphStyle": {"range": {"startIndex": el["startIndex"], "endIndex": el["endIndex"]},
                         "paragraphStyle": {"pageBreakBefore": True}, "fields": "pageBreakBefore"}})
    batch(reqs)


def build(doc_id, blocks, tables, breaks=()):
    gdoc.DOC = doc_id
    _text_stage(blocks)
    names = _insert_tables(blocks, tables)
    for idx, name in enumerate(names):
        _fill_and_style(idx, tables[name])
    if breaks:
        page_break_before(breaks)
    bad = verify(tables, names)
    print("таблиц:", len(names), "| расхождений в ячейках:", bad)
    return bad
