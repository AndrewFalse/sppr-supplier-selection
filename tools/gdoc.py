"""Низкоуровневые помощники для Google Docs API (паспорт СППР)."""
import os, re
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Ключ сервисного аккаунта и ID документа задаются переменными окружения (в репозиторий не попадают)
KEY = os.environ.get("SPPR_GOOGLE_KEY", str(Path(__file__).with_name("credentials.json")))
DOC = os.environ.get("SPPR_DOC_ID", "")
_creds = service_account.Credentials.from_service_account_file(
    KEY, scopes=["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"])
docs = build("docs", "v1", credentials=_creds, cache_discovery=False)
drive = build("drive", "v3", credentials=_creds, cache_discovery=False)

FONT = "Times New Roman"
IND = 1.25 / 2.54 * 72            # абзацный отступ 1,25 см, pt
MM = 72 / 25.4
BLACK = {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}}

def pt(v):
    return {"magnitude": v, "unit": "PT"}

def get():
    return docs.documents().get(documentId=DOC).execute()

def batch(reqs):
    if not reqs:
        return {"replies": []}
    return docs.documents().batchUpdate(documentId=DOC, body={"requests": reqs}).execute()

def parse(s):
    """Мини-разметка: **жирный**, _{подстрочный}, ^{надстрочный}."""
    out, spans, pos = [], [], 0
    for m in re.finditer(r'\*\*(.+?)\*\*|_\{(.+?)\}|\^\{(.+?)\}', s):
        out.append(s[pos:m.start()])
        cur = sum(len(x) for x in out)
        for g, kind in ((1, "bold"), (2, "sub"), (3, "sup")):
            if m.group(g) is not None:
                out.append(m.group(g)); spans.append((cur, cur + len(m.group(g)), kind))
        pos = m.end()
    out.append(s[pos:])
    return "".join(out), spans

def ptext(el):
    return "".join(r.get("textRun", {}).get("content", "") for r in el["paragraph"]["elements"])

def cell_text(cell):
    return "".join(ptext(ce) for ce in cell["content"] if "paragraph" in ce).rstrip("\n")

def body_paragraphs(d=None):
    d = d or get()
    return [ptext(el).rstrip("\n") for el in d["body"]["content"] if "paragraph" in el]

def export_pdf(path):
    data = drive.files().export_media(fileId=DOC, mimeType="application/pdf").execute()
    open(path, "wb").write(data)
    return path
