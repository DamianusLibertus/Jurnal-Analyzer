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
    /* Paksa warna teks label dan nilai pada st.metric agar terlihat kontras & jelas */
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


# ---------- LLM helper ----------
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
    """Konversi string angka (termasuk format Indonesia 1.000.000,50) ke float."""
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        try:
            return float(x)
        except Exception:
            return 0.0
    s = str(x).strip()
    if s in ("", "-", "--", "nil", "null", "nan", "none", "."):
        return 0.0
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
    import fitz  # PyMuPDF
    out = []
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    for page in doc[:max_pages]:
        pix = page.get_pixmap(dpi=150)
        out.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return out


# ---------- Ekstraksi Teks & Tabel PDF ----------
HEADER_COL_KW = ("akun", "uraian", "keterangan", "perkiraan", "nama akun", "debet",
                 "debit", "kredit", "credit", "target", "realisasi", "item", "pos",
                 "anggaran", "nominal")
SIGN_KW = ("mengetahui", "menyetujui", "disetujui", "mengesahkan", "dibuat oleh",
           "diperiksa", "disusun", "penyusun", "ketua", "wakil", "manajer", "manager",
           "direktur", "direktris", "bendahara", "sekretaris", "kepala", "pimpinan",
           "atasan", "nip", "nik", "tanda tangan", "ttd", "hormat kami", "stempel")
CLOSING_KW = ("catatan:", "keterangan:", "demikian", "laporan ini", "dibuat dengan")
HEADING_KW = ("halaman", "jurnal", "laporan", "periode", "page", "tanggal", "dibuat",
              "perusahaan", "neraca", "buku besar", "hal.", "koperasi", "cv ", "pt ")
ROW_NOISE_KW = ("total", "jumlah", "saldo awal", "saldo akhir", "sub total", "subtotal",
                "grand total", "saldoawal", "saldoakhir", "mengetahui", "menyetujui")


def _despace(s: str) -> str:
    return re.sub(r"(?:\b[A-Za-z]\b\s*){2,}", lambda m: m.group(0).replace(" ", ""), str(s))


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


def pdf_extract_direct(raw_bytes: bytes, mode: str, max_pages: int = 50) -> pd.DataFrame:
    """Ekstrak tabel PDF secara terstruktur berbasis Grid/Tabel presisi tinggi."""
    import pdfplumber

    extracted_frames = []

    with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
        for page in pdf.pages[:max_pages]:
            # Coba ekstraksi tabel bawaan pdfplumber
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
            }) or page.extract_tables()

            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                
                # Temukan baris header
                df_raw = pd.DataFrame(tbl)
                header_idx = None
                for idx, row in df_raw.iterrows():
                    row_str = " ".join([str(c or "").lower() for c in row])
                    if sum(1 for kw in HEADER_COL_KW if kw in row_str) >= 2:
                        header_idx = idx
                        break
                
                if header_idx is not None:
                    headers = [clean_header(c) for c in df_raw.iloc[header_idx]]
                    body = df_raw.iloc[header_idx + 1:].copy()
                    body.columns = headers
                else:
                    body = df_raw.copy()

                norm = normalize_df(body, mode)
                if norm is not None and not norm.empty:
                    extracted_frames.append(norm)

    if extracted_frames:
        combined = pd.concat(extracted_frames, ignore_index=True)
        if mode == "jurnal":
            combined = combined[(combined["Debet"].abs() > 0) | (combined["Kredit"].abs() > 0)]
        else:
            combined = combined[(combined["Target"].abs() > 0) | (combined["Realisasi"].abs() > 0)]
        
        if not combined.empty:
            return combined.reset_index(drop=True)

    return pd.DataFrame()


def has_tesseract() -> bool:
    import shutil
    return shutil.which("tesseract") is not None


def ocr_image_direct(raw_bytes: bytes, mode: str) -> pd.DataFrame:
    import pytesseract
    from PIL import Image
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    text = pytesseract.image_to_string(img, lang="ind+eng")
    # Parsing teks sederhana untuk OCR Tesseract
    lines = text.splitlines()
    rows = []
    for line in lines:
        parts = line.split()
        nums = [to_num(p) for p in parts if re.search(r"\d", p)]
        if mode == "jurnal" and len(nums) >= 2:
            label = " ".join([p for p in parts if not re.search(r"\d", p)])
            rows.append({"Akun": label or "Transaksi OCR", "Debet": nums[0], "Kredit": nums[1]})
    return normalize_df(pd.DataFrame(rows), mode)


def extract_json(text: str):
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ---------- Ekstraksi AI Vision ----------
def vision_extract(images_b64, mode: str, timeout: int = 600) -> pd.DataFrame:
    if mode == "jurnal":
        schema = '{"rows": [{"akun": "string nama akun", "debet": angka, "kredit": angka}]}'
        cols = "Akun, Debet, Kredit"
    else:
        schema = '{"rows": [{"item": "string nama item/pos", "target": angka, "realisasi": angka}]}'
        cols = "Item, Target, Realisasi"
    system = (
        "Anda adalah mesin OCR akuntansi presisi tinggi (target akurasi 99%). "
        "Anda ahli membaca tabel laporan keuangan, jurnal, nama akun, serta posisi "
        "nilai Debet dan Kredit secara tepat."
    )
    prompt = (
        f"Baca dokumen akuntansi pada gambar. Ekstrak SETIAP baris tabel ke kolom: {cols}.\n"
        "Aturan:\n"
        "- Kembalikan angka murni (tanpa 'Rp', tanpa pemisah ribuan). Gunakan titik untuk desimal.\n"
        "- Jika sel kosong / bernilai - / nihil, isi 0.\n"
        "- Jangan sertakan baris Total/Jumlah dalam rows.\n"
        f"Balas HANYA dengan JSON valid format:\n{schema}"
    )
    raw = llm_call(system, prompt, images_b64=images_b64, timeout=timeout)
    data = extract_json(raw)
    rows = (data or {}).get("rows", []) if isinstance(data, dict) else []
    return normalize_df(pd.DataFrame(rows), mode)


def process_files(files, mode: str, progress_cb=None, timeout: int = 600):
    frames = []
    messages = []
    total = len(files)
    for idx, f in enumerate(files, start=1):
        name = f.get("name", f"file-{idx}")
        kind = f.get("kind")
        data = f.get("data")
        if progress_cb:
            progress_cb(idx, total, name)
        try:
            if kind in ("excel", "csv"):
                raw_df = pd.read_excel(BytesIO(data)) if kind == "excel" else pd.read_csv(BytesIO(data))
                part = normalize_df(raw_df, mode)
                frames.append(part)
                messages.append(("ok", f"✅ {name}: {len(part)} baris terbaca."))

            elif kind == "pdf":
                part = None
                try:
                    part = pdf_extract_direct(data, mode)
                except Exception as ex:
                    part = None
                
                if part is not None and not part.empty:
                    frames.append(part)
                    messages.append(("ok", f"✅ {name}: {len(part)} baris terstruktur diekstrak dari PDF."))
                    continue
                
                # Fallback AI Vision jika PDF berupa Hasil Scan
                if not EMERGENT_LLM_KEY:
                    messages.append(("warn", f"⚠️ {name}: PDF tampak scan/gambar dan AI Vision belum diset."))
                    continue
                pages = pdf_to_b64_images(data)
                page_frames = []
                for pno, page_img in enumerate(pages, start=1):
                    if progress_cb:
                        progress_cb(idx, total, f"{name} — OCR AI hal. {pno}/{len(pages)}")
                    try:
                        page_frames.append(vision_extract([page_img], mode, timeout=timeout))
                    except Exception as e:
                        pass
                if page_frames:
                    part = pd.concat(page_frames, ignore_index=True)
                    frames.append(part)
                    messages.append(("ok", f"✅ {name}: {len(part)} baris via OCR AI Vision."))

            elif kind == "image":
                part = None
                if has_tesseract():
                    try:
                        part = ocr_image_direct(data, mode)
                    except Exception:
                        part = None
                if part is not None and not part.empty:
                    frames.append(part)
                    messages.append(("ok", f"✅ {name}: {len(part)} baris via OCR Tesseract."))
                    continue
                
                if EMERGENT_LLM_KEY:
                    part = vision_extract([img_to_b64(data)], mode, timeout=timeout)
                    frames.append(part)
                    messages.append(("ok", f"✅ {name}: {len(part)} baris via AI Vision."))

        except Exception as e:
            messages.append(("error", f"❌ {name}: gagal — {friendly_error(e)}"))

    if not frames:
        return None, messages
    return pd.concat(frames, ignore_index=True), messages


# ---------- Normalisasi Dataframe ----------
def _find_col(cols, keywords):
    low = {c: str(c).lower() for c in cols}
    for c, l in low.items():
        for kw in keywords:
            if kw in l:
                return c
    return None


def normalize_df(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    if df is None or df.empty:
        if mode == "jurnal":
            return pd.DataFrame([{"Akun": "", "Debet": 0.0, "Kredit": 0.0}])
        return pd.DataFrame([{"Item": "", "Target": 0.0, "Realisasi": 0.0}])

    df = df.rename(columns={c: clean_header(c) for c in df.columns})
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    cols = list(df.columns)

    if mode == "jurnal":
        c_deb = _find_col(cols, ["debet", "debit"])
        c_kre = _find_col(cols, ["kredit", "credit"])
        kw_label = _find_col(cols, ["uraian", "keterangan", "akun", "account",
                                    "deskripsi", "description", "perkiraan", "nama"])

        # Pemetaan adaptif jika nama kolom header tidak berlabel jelas
        if (not c_deb or not c_kre) and len(cols) >= 3:
            c_deb = cols[-3] if len(cols) >= 4 else cols[-2]
            c_kre = cols[-2] if len(cols) >= 4 else cols[-1]

        c_akun = kw_label if kw_label else cols[0]

        out = pd.DataFrame()
        out["Akun"] = df[c_akun].astype(str).str.replace("\n", " ", regex=False).str.strip() if c_akun in df else ""
        out["Debet"] = df[c_deb].map(to_num) if c_deb in df else 0.0
        out["Kredit"] = df[c_kre].map(to_num) if c_kre in df else 0.0

        out = out[~out["Akun"].map(is_noise_label)]
        out = out[(out["Debet"].abs() > 0) | (out["Kredit"].abs() > 0)].reset_index(drop=True)
        return out if not out.empty else pd.DataFrame([{"Akun": "", "Debet": 0.0, "Kredit": 0.0}])
    else:
        c_tar = _find_col(cols, ["target", "anggaran", "budget", "rencana", "pagu"])
        c_real = _find_col(cols, ["realisasi", "realization", "aktual", "actual", "realized"])
        kw_label = _find_col(cols, ["item", "uraian", "keterangan", "pos", "akun", "nama"])
        
        if (not c_tar or not c_real) and len(cols) >= 3:
            c_tar = cols[-2]
            c_real = cols[-1]

        c_item = kw_label if kw_label else cols[0]

        out = pd.DataFrame()
        out["Item"] = df[c_item].astype(str).str.replace("\n", " ", regex=False).str.strip() if c_item in df else ""
        out["Target"] = df[c_tar].map(to_num) if c_tar in df else 0.0
        out["Realisasi"] = df[c_real].map(to_num) if c_real in df else 0.0

        out = out[~out["Item"].map(is_noise_label)]
        out = out[(out["Target"].abs() > 0) | (out["Realisasi"].abs() > 0)].reset_index(drop=True)
        return out if not out.empty else pd.DataFrame([{"Item": "", "Target": 0.0, "Realisasi": 0.0}])


# ---------- Perhitungan Analisis ----------
def compute(df: pd.DataFrame, mode: str):
    df = df.copy()
    if mode == "jurnal":
        df["Debet"] = df["Debet"].map(to_num)
        df["Kredit"] = df["Kredit"].map(to_num)
        df["Selisih"] = (df["Debet"] - df["Kredit"]).round(2)
        total_debet = float(df["Debet"].sum())
        total_kredit = float(df["Kredit"].sum())
        diff = round(total_debet - total_kredit, 2)
        balanced = abs(diff) < 0.01
        totals = {
            "total_debet": total_debet,
            "total_kredit": total_kredit,
            "selisih": diff,
            "balanced": balanced,
        }
        imbalanced = df[df["Selisih"].abs() > 0.001]
    else:
        df["Target"] = df["Target"].map(to_num)
        df["Realisasi"] = df["Realisasi"].map(to_num)
        df["Selisih"] = (df["Realisasi"] - df["Target"]).round(2)
        df["% Deviasi"] = df.apply(
            lambda r: round((r["Selisih"] / r["Target"] * 100), 2) if r["Target"] else 0.0, axis=1
        )
        total_target = float(df["Target"].sum())
        total_real = float(df["Realisasi"].sum())
        diff = round(total_real - total_target, 2)
        balanced = abs(diff) < 0.01
        totals = {
            "total_target": total_target,
            "total_realisasi": total_real,
            "selisih": diff,
            "balanced": balanced,
        }
        imbalanced = df[df["Selisih"].abs() > 0.001]
    return df, totals, imbalanced


# ---------- AI Financial Analyst ----------
def ai_analysis(df: pd.DataFrame, totals: dict, imbalanced: pd.DataFrame, mode: str) -> str:
    system = (
        "Anda adalah Auditor & Analis Keuangan profesional. Anda menulis penjelasan audit "
        "terstruktur dan mudah dipahami dalam Bahasa Indonesia."
    )
    table_md = df.head(30).to_markdown(index=False)
    if mode == "jurnal":
        ctx = (
            f"Mode: Jurnal (Debet vs Kredit).\n"
            f"Total Debet: {totals['total_debet']:.2f}\n"
            f"Total Kredit: {totals['total_kredit']:.2f}\n"
            f"Selisih: {totals['selisih']:.2f}\n"
            f"Status: {'SEIMBANG' if totals['balanced'] else 'TIDAK SEIMBANG'}\n"
        )
    else:
        ctx = (
            f"Mode: Target vs Realisasi.\n"
            f"Total Target: {totals['total_target']:.2f}\n"
            f"Total Realisasi: {totals['total_realisasi']:.2f}\n"
        )
    prompt = (
        f"{ctx}\nTabel data sampel:\n{table_md}\n\n"
        "Buat 'Penjelasan Audit' singkat:\n"
        "### 1. Akun/Item Bermasalah\n"
        "### 2. Analisis Penyebab\n"
        "### 3. Rekomendasi Jurnal Koreksi\n"
    )
    try:
        return llm_call(system, prompt)
    except Exception as e:
        return f"Catatan Audit: Evaluasi data transaksi dapat diperiksa langsung pada tabel selisih."


# ---------- Ekspor PDF & Excel ----------
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Analisis")
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def build_pdf(df, totals, imbalanced, explanation, mode) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=12*mm, rightMargin=12*mm)
    ss = getSampleStyleSheet()
    navy = colors.HexColor("#1E3A5F")
    
    title_style = ParagraphStyle("TitleStyle", parent=ss["Title"], textColor=navy, fontSize=15, leading=18, alignment=0)
    h2 = ParagraphStyle("Heading2Style", parent=ss["Heading2"], textColor=navy, fontSize=11, leading=15, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("SmallStyle", parent=ss["Normal"], fontSize=8, leading=10, textColor=colors.grey)
    body = ParagraphStyle("BodyStyle", parent=ss["Normal"], fontSize=8.5, leading=12, textColor=colors.HexColor("#1E293B"))
    
    th_style = ParagraphStyle("THStyle", parent=ss["Normal"], fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")
    td_style = ParagraphStyle("TDStyle", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#1E293B"))

    elements = []
    elements.append(Paragraph(f"<b>{APP_TITLE}</b>", title_style))
    elements.append(Paragraph(f"Hak Cipta © {CURRENT_YEAR} {OWNER}. Seluruh Hak Cipta Dilindungi.", small))
    elements.append(Paragraph(f"<i>Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M WIB')}</i>", small))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("<b>Ringkasan Eksekutif</b>", h2))
    if mode == "jurnal":
        summary_data = [
            [Paragraph("<b>Indikator</b>", th_style), Paragraph("<b>Nilai</b>", th_style)],
            [Paragraph("Total Debet", td_style), Paragraph(rupiah(totals["total_debet"]), td_style)],
            [Paragraph("Total Kredit", td_style), Paragraph(rupiah(totals["total_kredit"]), td_style)],
            [Paragraph("Selisih (Debet - Kredit)", td_style), Paragraph(rupiah(totals["selisih"]), td_style)],
            [Paragraph("Status", td_style), Paragraph("<b>SEIMBANG</b>" if totals["balanced"] else "<font color='red'><b>TIDAK SEIMBANG</b></font>", td_style)],
        ]
    else:
        summary_data = [
            [Paragraph("<b>Indikator</b>", th_style), Paragraph("<b>Nilai</b>", th_style)],
            [Paragraph("Total Target", td_style), Paragraph(rupiah(totals["total_target"]), td_style)],
            [Paragraph("Total Realisasi", td_style), Paragraph(rupiah(totals["total_realisasi"]), td_style)],
            [Paragraph("Selisih", td_style), Paragraph(rupiah(totals["selisih"]), td_style)],
        ]

    t_summary = Table(summary_data, colWidths=[110 * mm, 70 * mm])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 10))

    doc.build(elements)
    return buf.getvalue()


def inject_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
        .app-hero {
            background: linear-gradient(120deg, #1E3A5F 0%, #274b78 100%);
            color: #fff; padding: 24px; border-radius: 12px; margin-bottom: 12px;
        }
        .app-hero h1 { color:#fff !important; margin:0; font-size: 1.8rem; }
        .app-hero p { color:#d7e3f4; margin:4px 0 0; }
        .app-footer { text-align:center; color:#64748b; font-size:.8rem; padding:20px 0; }
        </style>
    """, unsafe_allow_html=True)


# ---------- MAIN ----------
def main():
    inject_css()

    if "df" not in st.session_state:
        st.session_state.df = None
    if "analysis" not in st.session_state:
        st.session_state.analysis = None

    with st.sidebar:
        st.markdown(f"### 📊 {APP_TITLE}")
        st.caption(f"Oleh {OWNER}")
        st.divider()
        mode_label = st.radio("Mode Analisis", ["Jurnal (Debet & Kredit)", "Target vs Realisasi"])
        mode = "jurnal" if mode_label.startswith("Jurnal") else "realisasi"

        st.divider()
        st.markdown("**🗂️ Riwayat Analisis**")
        hist = load_history()
        if hist and st.button("🧹 Bersihkan Riwayat"):
            clear_history()
            st.rerun()

    st.markdown(f"""
        <div class="app-hero">
            <h1>{APP_TITLE}</h1>
            <p>Ekstraksi Data Presisi • Pengecekan Keseimbangan Jurnal • Audit Selisih Otomatis</p>
        </div>
    """, unsafe_allow_html=True)

    st.subheader("① Input Dokumen")
    up = st.file_uploader("Unggah PDF, Excel, atau CSV Jurnal Transaksi", type=["xlsx", "xls", "csv", "pdf", "jpg", "png"], accept_multiple_files=True)
    
    files = []
    if up:
        for f in up:
            kind = "excel" if f.name.endswith((".xlsx", ".xls")) else ("csv" if f.name.endswith(".csv") else ("pdf" if f.name.endswith(".pdf") else "image"))
            files.append({"name": f.name, "kind": kind, "data": f.getvalue()})

    if st.button("🚀 Ekstrak Data", type="primary", disabled=not files):
        with st.spinner("Memproses file..."):
            combined, messages = process_files(files, mode)
            for level, text in messages:
                if level == "ok": st.success(text)
                else: st.warning(text)
            if combined is not None and not combined.empty:
                st.session_state.df = combined
                st.session_state.analysis = None
                st.success(f"Berhasil mengekstrak {len(combined)} baris transaksi.")

    if st.session_state.df is not None and not st.session_state.df.empty:
        st.subheader("② Koreksi & Kunci Data")
        edited = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)

        if st.button("🔒 Kunci Data & Jalankan Analisis", type="primary"):
            full_df, totals, imbalanced = compute(normalize_df(edited, mode), mode)
            explanation = ai_analysis(full_df, totals, imbalanced, mode) if EMERGENT_LLM_KEY else "AI tidak aktif."
            st.session_state.analysis = {"df": full_df, "totals": totals, "imbalanced": imbalanced, "explanation": explanation, "mode": mode}
            
            save_history({
                "id": str(uuid.uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": mode, "rows": normalize_df(edited, mode).to_dict("records"),
                "full_rows": full_df.astype(object).to_dict("records"), "totals": totals, "explanation": explanation
            })
            st.rerun()

    res = st.session_state.analysis
    if res:
        st.subheader("③ Hasil Analisis & Selisih")
        df = res["df"]
        totals = res["totals"]

        if res["mode"] == "jurnal":
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Debet", rupiah(totals["total_debet"]))
            c2.metric("Total Kredit", rupiah(totals["total_kredit"]))
            c3.metric("Selisih", rupiah(totals["selisih"]))
            c4.metric("Status", "SEIMBANG ✅" if totals["balanced"] else "TIDAK SEIMBANG ⚠️")
            
            if not totals["balanced"]:
                st.error(f"⚠️ Jurnal TIDAK SEIMBANG! Terdapat selisih {rupiah(totals['selisih'])}.")
            else:
                st.success("✅ Jurnal SEIMBANG — Total Debet = Total Kredit.")

        st.dataframe(df, use_container_width=True)

        st.subheader("④ Ekspor Laporan")
        e1, e2 = st.columns(2)
        e1.download_button("⬇️ Download Excel (.xlsx)", data=to_excel_bytes(df), file_name="Analisis_Jurnal.xlsx", use_container_width=True)
        e2.download_button("⬇️ Download CSV", data=to_csv_bytes(df), file_name="Analisis_Jurnal.csv", use_container_width=True)


if __name__ == "__main__":
    main()
