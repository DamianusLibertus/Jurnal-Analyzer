# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
#
# Application: Aplikasi Analisis Jurnal & Selisih Laporan
# Owner: Damianus Libertus
# Unauthorized copying, modification, or distribution of
# this file via any medium is strictly prohibited.
# =========================================================

import os
import re
import io
import json
import uuid
import base64
import asyncio
from io import BytesIO
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ---------- Konfigurasi & konstanta ----------
CURRENT_YEAR = datetime.now().year
APP_TITLE = "Aplikasi Analisis Jurnal & Selisih Laporan"
OWNER = "Damianus Libertus"
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
VISION_MODEL = "gpt-5.4"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""
    <style>
    div[data-testid="stMetricValue"] {
        color: #0f172a !important;
        font-weight: bold !important;
        background-color: #ffffff !important;
        padding: 4px 8px !important;
        border-radius: 4px !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #334155 !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMetric"] {
        background-color: #ffffff !important;
        padding: 12px !important;
        border-radius: 8px !important;
        border: 1px solid #cbd5e1 !important;
        box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.05) !important;
    }
    </style>
""", unsafe_allow_html=True)

# ---------- MongoDB (history) ----------
@st.cache_resource(show_spinner=False)
def get_db():
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2500)
        client.admin.command("ping")
        return client[DB_NAME]
    except Exception:
        return None


def save_history(record: dict) -> bool:
    db = get_db()
    if db is None:
        return False
    try:
        db["analisis_history"].insert_one(record)
        return True
    except Exception:
        return False


def load_history(limit: int = 50):
    db = get_db()
    if db is None:
        return []
    try:
        cur = db["analisis_history"].find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
        return list(cur)
    except Exception:
        return []


def delete_history(record_id: str) -> bool:
    db = get_db()
    if db is None:
        return False
    try:
        db["analisis_history"].delete_one({"id": record_id})
        return True
    except Exception:
        return False


def clear_history() -> bool:
    db = get_db()
    if db is None:
        return False
    try:
        db["analisis_history"].delete_many({})
        return True
    except Exception:
        return False


# ---------- LLM helper (Emergent Universal Key) ----------
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _llm_call(system_message: str, text: str, images_b64=None, timeout: int = 600) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=str(uuid.uuid4()),
        system_message=system_message,
    ).with_model("openai", VISION_MODEL)
    contents = [ImageContent(image_base64=b) for b in (images_b64 or [])]
    msg = UserMessage(text=text, file_contents=contents) if contents else UserMessage(text=text)
    resp = await asyncio.wait_for(chat.send_message(msg), timeout=timeout)
    return resp if isinstance(resp, str) else str(resp)


def llm_call(system_message: str, text: str, images_b64=None, timeout: int = 600) -> str:
    return run_async(_llm_call(system_message, text, images_b64, timeout))


def friendly_error(e) -> str:
    m = str(e)
    low = m.lower()
    if "budget" in low or "exceeded" in low:
        return "kuota AI (Universal Key) habis — silakan isi ulang saldo"
    if "timeout" in low or "timed out" in low:
        return "melebihi batas waktu pemrosesan"
    if "cannot identify image" in low or "unidentified" in low:
        return "file gambar tidak valid atau rusak"
    if "rate limit" in low or "429" in low:
        return "layanan AI sedang sibuk, coba lagi sebentar"
    leak_tokens = ("litellm", "openaiexception", "badrequesterror", "traceback",
                   "anthropic", "geminiexception", "current cost", "max budget")
    if any(tok in low for tok in leak_tokens):
        return "terjadi kendala pada layanan AI — silakan coba lagi"
    return m[:160]


# ---------- Utilitas ----------
def to_num(x) -> float:
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        try:
            return float(x)
        except Exception:
            return 0.0
    s = str(x).strip()
    neg = "(" in s and ")" in s
    s = re.sub(r"[^\d,.\-]", "", s)
    if s in ("", "-", ".", ","):
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[-1]) == 3):
            s = s.replace(".", "")
    try:
        v = float(s)
        return -abs(v) if neg else v
    except Exception:
        return 0.0


def rupiah(v: float) -> str:
    try:
        return f"Rp {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)


def img_to_b64(raw_bytes: bytes) -> str:
    from PIL import Image
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    max_dim = 2200
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def pdf_to_b64_images(raw_bytes: bytes, max_pages: int = 6):
    import fitz 
    out = []
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    for page in doc[:max_pages]:
        pix = page.get_pixmap(dpi=150)
        out.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return out


HEADER_COL_KW = ("akun", "uraian", "keterangan", "perkiraan", "nama akun", "debet",
                 "debit", "kredit", "credit", "target", "realisasi", "item", "pos",
                 "anggaran", "nominal")
SIGN_KW = ("mengetahui", "menyetujui", "disetujui", "mengesahkan", "dibuat oleh",
           "diperiksa", "disusun", "penyusun", "ketua", "wakil", "manajer", "manager",
           "direktur", "direktris", "bendahara", "sekretaris", "kepala", "pimpinan",
           "atasan", "nip", "nik", "tanda tangan", "ttd", "hormat kami", "stempel",
           "materai", "pejabat", "auditor", "akuntan publik", "an.", "a.n.", "u.b.",
           "mengesyahkan")
CLOSING_KW = ("catatan:", "keterangan:", "demikian", "laporan ini", "dibuat dengan",
              "*)", "**)", "disclaimer")
HEADING_KW = ("halaman", "jurnal", "laporan", "periode", "page", "tanggal", "dibuat",
              "perusahaan", "neraca", "buku besar", "hal.", "per ", "pemerintah",
              "kementerian", "dinas", "yayasan", "koperasi", "cv ", "pt ", "ud ")
MONTH_KW = ("januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus",
            "september", "oktober", "november", "desember", "january", "february",
            "march", "june", "july", "august", "october", "december")
ROW_NOISE_KW = ("total", "jumlah", "saldo awal", "saldo akhir", "sub total", "subtotal",
                "grand total", "saldoawal", "saldoakhir", "mengetahui", "menyetujui",
                "disetujui", "mengesahkan", "dibuat oleh", "diperiksa", "disusun",
                "penyusun", "direktur", "bendahara", "sekretaris", "pimpinan",
                "tanda tangan", "hormat kami", "nip", "nik")


def _despace(s: str) -> str:
    return re.sub(r"(?:\b[A-Za-z]\b\s*){2,}",
                  lambda m: m.group(0).replace(" ", ""), str(s))


def is_noise_label(label) -> bool:
    low = _despace(str(label)).strip().lower()
    if low in ("", "nan", "none"):
        return True
    return any(k in low for k in ROW_NOISE_KW)


def clean_header(name) -> str:
    s = str(name if name is not None else "").replace("\n", " ").strip()
    tokens = s.split()
    out, buf = [], []
    for tok in tokens:
        if len(tok) == 1 and tok.isalpha():
            buf.append(tok)
        else:
            if buf:
                out.append("".join(buf)); buf = []
            out.append(tok)
    if buf:
        out.append("".join(buf))
    return " ".join(out).strip()


DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
CODE_RE = re.compile(r"\b(?:JU|TAB|OB|COA|BKK|BKM|KK|KM|ACC[-.]?\w*|TAB\.?\w*|[A-Z]{2,4}[-.]?\d[\w-]*)\b")


def _clean_label(line: str) -> str:
    s = DATE_RE.sub(" ", str(line))
    s = CODE_RE.sub(" ", s)
    s = re.sub(r"\(?-?\d[\d.,]*\)?", " ", s)
    s = re.sub(r"[|:]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .-,")


def _is_noise_line(low: str) -> bool:
    low = _despace(low).lower()
    if any(k in low for k in HEADING_KW):
        return True
    if any(k in low for k in ("total", "jumlah", "saldo akhir", "saldo awal", "saldoakhir", "saldoawal")):
        return True
    if any(k in low for k in SIGN_KW) or any(k in low for k in CLOSING_KW):
        return True
    if any(m in low for m in MONTH_KW) and re.search(r"\b\d{4}\b", low):
        return True
    return False


def parse_text_rows(text: str, mode: str) -> pd.DataFrame:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    num_re = re.compile(r"\(?-?[\d][\d.,]*\)?")
    start = 0
    for i, ln in enumerate(lines):
        if sum(1 for k in HEADER_COL_KW if k in ln.lower()) >= 2:
            start = i + 1
            break

    rows = []
    pending = []
    for raw_line in lines[start:]:
        line = raw_line
        if not line:
            continue
        low = line.lower()
        nums = num_re.findall(line)
        amts = [to_num(t) for t in nums if is_amount_token(t)]

        if not amts:
            if _is_noise_line(low):
                pending = []
            else:
                desc = _clean_label(line)
                if desc:
                    pending.append(desc)
            continue

        line_label = _clean_label(line)
        lbl_ds = _despace(line_label).lower().strip()
        if lbl_ds in ("total", "jumlah", "saldo", "saldo akhir", "saldo awal",
                      "saldoakhir", "saldoawal") or (
            any(lbl_ds.startswith(k) for k in ("total", "jumlah", "saldo")) and len(lbl_ds) <= 14):
            pending = []
            continue

        strong = len(re.sub(r"[^A-Za-z]", "", line_label)) >= 4
        if strong:
            label = (line_label + " " + " ".join(pending)).strip() if pending else line_label
        else:
            label = " ".join(pending).strip() or line_label or "(tanpa keterangan)"
        pending = []
        label = label[:150]

        if mode == "jurnal":
            if len(amts) >= 3:
                debet, kredit = amts[-3], amts[-2]
            elif len(amts) == 2:
                debet, kredit = amts[-2], amts[-1]
            else:
                debet, kredit = amts[0], 0.0
            if debet == 0 and kredit == 0:
                continue
            rows.append({"Akun": label, "Debet": debet, "Kredit": kredit})
        else:
            if len(amts) >= 2:
                target, real = amts[-2], amts[-1]
            else:
                target, real = amts[0], 0.0
            if target == 0 and real == 0:
                continue
            rows.append({"Item": label, "Target": target, "Realisasi": real})
    return pd.DataFrame(rows)


def is_amount_token(tok: str) -> bool:
    t = str(tok).strip().strip("()")
    if t in ("0", "-0"):
        return True
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d+", t):
        return True
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        return True
    if re.fullmatch(r"-?\d+,\d+", t):
        return True
    return False


def pdf_extract_direct(raw_bytes: bytes, mode: str, max_pages: int = 30) -> pd.DataFrame:
    import pdfplumber
    text_accum = []
    table_frames = []
    with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
        for page in pdf.pages[:max_pages]:
            txt = page.extract_text() or ""
            if txt:
                text_accum.append(txt)
            for tbl in (page.extract_tables() or []):
                if not tbl or len(tbl) < 2:
                    continue
                header = [str(c).strip() if c else "" for c in tbl[0]]
                body = [r for r in tbl[1:] if any(c not in (None, "") for c in r)]
                if body:
                    table_frames.append(pd.DataFrame(body, columns=header))

    text_df = parse_text_rows("\n".join(text_accum), mode)
    if text_df is not None and not text_df.empty:
        return text_df.reset_index(drop=True)

    parts = []
    for f in table_frames:
        nf = normalize_df(f, mode)
        if nf is not None and not nf.empty:
            parts.append(nf)
    if parts:
        return pd.concat(parts, ignore_index=True)
    return pd.DataFrame()


def has_tesseract() -> bool:
    import shutil
    return shutil.which("tesseract") is not None


def ocr_image_direct(raw_bytes: bytes, mode: str) -> pd.DataFrame:
    import pytesseract
    from PIL import Image
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    text = pytesseract.image_to_string(img, lang="ind+eng")
    return parse_text_rows(text, mode)


def extract_json(text: str):
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"
