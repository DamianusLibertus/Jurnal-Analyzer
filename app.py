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
    """Terjemahkan exception teknis menjadi pesan ramah untuk pengguna akhir."""
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
    # Fallback: pastikan nama library internal tidak bocor ke pengguna
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
    neg = "(" in s and ")" in s
    s = re.sub(r"[^\d,.\-]", "", s)
    if s in ("", "-", ".", ","):
        return 0.0
    if "," in s and "." in s:
        # titik = pemisah ribuan, koma = desimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # koma kemungkinan desimal
        s = s.replace(",", ".")
    elif "." in s:
        # hanya titik: konvensi Indonesia → titik = ribuan, KECUALI tampak desimal
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[-1]) == 3):
            # mis. "1.234.567" atau "5.000" → pemisah ribuan
            s = s.replace(".", "")
        # selain itu (mis. "12.5", "3.75") biarkan sebagai desimal
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
    import fitz  # PyMuPDF
    out = []
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    for page in doc[:max_pages]:
        pix = page.get_pixmap(dpi=150)
        out.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return out


# ---------- Ekstraksi teks langsung (TANPA AI / kuota) ----------
def parse_text_rows(text: str, mode: str) -> pd.DataFrame:
    """Parse teks mentah (hasil pdfplumber/OCR) menjadi baris akun + angka secara heuristik."""
    rows = []
    skip_kw = ("total", "jumlah", "saldo akhir", "akun", "keterangan", "debet",
               "kredit", "debit", "credit", "target", "realisasi", "item", "no.")
    heading_kw = ("halaman", "jurnal", "laporan", "periode", "page", "tanggal",
                  "dibuat", "perusahaan", "neraca", "buku besar", "hal.", "per ")
    num_re = re.compile(r"\(?-?[\d][\d.,]*\)?")
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        nums = num_re.findall(line)
        # buang token yang hanya berupa nomor urut tunggal 1-2 digit di awal
        label = num_re.sub(" ", line).strip(" .:-\t|")
        if not label or len(label) < 2:
            continue
        # buang baris judul/heading (mis. "JURNAL UMUM - Halaman 1")
        if any(k in low for k in heading_kw):
            continue
        if any(k in low for k in ("total", "jumlah")) and label.lower() in ("total", "jumlah"):
            continue
        # header row (mengandung kata kunci kolom & tanpa angka nyata)
        if not nums and any(k in low for k in skip_kw):
            continue
        values = [to_num(n) for n in nums if to_num(n) != 0 or n.strip("() ") == "0"]
        if mode == "jurnal":
            debet = kredit = 0.0
            if len(values) >= 2:
                debet, kredit = values[-2], values[-1]
            elif len(values) == 1:
                debet = values[0]
            if debet == 0 and kredit == 0:
                continue
            rows.append({"Akun": label, "Debet": debet, "Kredit": kredit})
        else:
            target = real = 0.0
            if len(values) >= 2:
                target, real = values[-2], values[-1]
            elif len(values) == 1:
                target = values[0]
            if target == 0 and real == 0:
                continue
            rows.append({"Item": label, "Target": target, "Realisasi": real})
    return pd.DataFrame(rows)


def pdf_extract_direct(raw_bytes: bytes, mode: str, max_pages: int = 20) -> pd.DataFrame:
    """Ekstrak tabel/teks PDF digital langsung via pdfplumber (tanpa AI). Kosong bila PDF hasil scan."""
    import pdfplumber
    frames = []
    text_accum = []
    with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
        for page in pdf.pages[:max_pages]:
            for tbl in (page.extract_tables() or []):
                if not tbl or len(tbl) < 2:
                    continue
                header = [str(c).strip() if c else "" for c in tbl[0]]
                body = [r for r in tbl[1:] if any(c not in (None, "") for c in r)]
                if body:
                    frames.append(pd.DataFrame(body, columns=header))
            txt = page.extract_text() or ""
            if txt:
                text_accum.append(txt)
    parts = []
    for f in frames:
        nf = normalize_df(f, mode)
        if nf is not None and not nf.empty:
            parts.append(nf)
    if parts:
        combined = pd.concat(parts, ignore_index=True)
        combined = combined[~(combined.iloc[:, 1:].apply(pd.to_numeric, errors="coerce").fillna(0).eq(0).all(axis=1))]
        if not combined.empty:
            return combined.reset_index(drop=True)
    # fallback: parse teks bila tabel tidak terdeteksi rapi
    text_df = parse_text_rows("\n".join(text_accum), mode)
    return text_df


def has_tesseract() -> bool:
    import shutil
    return shutil.which("tesseract") is not None


def ocr_image_direct(raw_bytes: bytes, mode: str) -> pd.DataFrame:
    """OCR gambar via Tesseract (gratis, lokal) lalu parse ke baris. Butuh tesseract terpasang."""
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
        "nilai Debet dan Kredit / Target dan Realisasi secara tepat, termasuk tulisan tangan."
    )
    prompt = (
        f"Baca dokumen akuntansi pada gambar. Ekstrak SETIAP baris tabel ke kolom: {cols}.\n"
        "Aturan:\n"
        "- Kembalikan angka murni (tanpa 'Rp', tanpa pemisah ribuan). Gunakan titik untuk desimal.\n"
        "- Jika sel kosong, isi 0.\n"
        "- Jangan sertakan baris Total/Jumlah dalam rows.\n"
        "- Pertahankan urutan baris sesuai dokumen.\n"
        f"Balas HANYA dengan JSON valid dengan format persis:\n{schema}"
    )
    raw = llm_call(system, prompt, images_b64=images_b64, timeout=timeout)
    data = extract_json(raw)
    rows = (data or {}).get("rows", []) if isinstance(data, dict) else []
    return normalize_df(pd.DataFrame(rows), mode)


def process_files(files, mode: str, progress_cb=None, timeout: int = 600):
    """Proses setiap file satu per satu (looping) dengan try-except.

    files: list dict {name, kind, data}. Mengembalikan (df_gabungan, messages).
    Kegagalan pada satu file (atau satu halaman PDF) tidak menghentikan pemrosesan lainnya.
    """
    frames = []
    messages = []  # (level, text) — level: ok | warn | error
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
                messages.append(("ok", f"✅ {name}: {len(part)} baris terbaca (langsung, tanpa AI)."))

            elif kind == "pdf":
                # 1) Coba ekstraksi TEKS/TABEL langsung (pdfplumber) — TANPA AI/kuota
                part = None
                try:
                    part = pdf_extract_direct(data, mode)
                except Exception:
                    part = None
                if part is not None and not part.empty:
                    frames.append(part)
                    messages.append(("ok", f"✅ {name}: {len(part)} baris diekstrak langsung dari teks PDF (tanpa AI)."))
                    continue
                # 2) PDF hasil scan (tanpa teks) → fallback AI Vision per halaman (butuh kuota)
                if not EMERGENT_LLM_KEY:
                    messages.append(("warn", f"⚠️ {name}: PDF tampak hasil scan/tanpa teks dan AI tidak tersedia — dilewati."))
                    continue
                pages = pdf_to_b64_images(data)
                if not pages:
                    messages.append(("warn", f"⚠️ {name}: tidak ada halaman yang dapat diproses."))
                    continue
                page_frames, page_errors = [], 0
                for pno, page_img in enumerate(pages, start=1):
                    if progress_cb:
                        progress_cb(idx, total, f"{name} — OCR AI halaman {pno}/{len(pages)}")
                    try:
                        page_frames.append(vision_extract([page_img], mode, timeout=timeout))
                    except asyncio.TimeoutError:
                        page_errors += 1
                        messages.append(("warn", f"⏱️ {name} hal. {pno}: melebihi batas waktu, dilewati."))
                    except Exception as e:
                        page_errors += 1
                        messages.append(("warn", f"⚠️ {name} hal. {pno}: gagal — {friendly_error(e)}"))
                if page_frames:
                    part = pd.concat(page_frames, ignore_index=True)
                    frames.append(part)
                    ok_pages = len(pages) - page_errors
                    messages.append(("ok", f"✅ {name}: {len(part)} baris via OCR AI ({ok_pages}/{len(pages)} halaman)."))
                else:
                    messages.append(("error", f"❌ {name}: PDF scan gagal diekstrak — periksa dokumen atau kuota AI."))

            elif kind == "image":
                # 1) OCR lokal gratis (Tesseract) — TANPA AI/kuota
                part = None
                if has_tesseract():
                    try:
                        part = ocr_image_direct(data, mode)
                    except Exception:
                        part = None
                if part is not None and not part.empty:
                    frames.append(part)
                    messages.append(("ok", f"✅ {name}: {len(part)} baris via OCR lokal Tesseract (tanpa AI). Mohon periksa hasilnya."))
                    continue
                # 2) Fallback AI Vision (butuh kuota)
                if not EMERGENT_LLM_KEY:
                    messages.append(("warn", f"⚠️ {name}: OCR lokal tidak menemukan tabel & AI tidak tersedia — dilewati."))
                    continue
                try:
                    part = vision_extract([img_to_b64(data)], mode, timeout=timeout)
                    frames.append(part)
                    messages.append(("ok", f"✅ {name}: {len(part)} baris diekstrak AI Vision."))
                except Exception as e:
                    messages.append(("error", f"❌ {name}: gagal — {friendly_error(e)}"))

            else:
                messages.append(("warn", f"⚠️ {name}: format tidak dikenali, dilewati."))
        except asyncio.TimeoutError:
            messages.append(("error", f"⏱️ {name}: melebihi batas waktu ({timeout}s), dilewati."))
        except Exception as e:
            messages.append(("error", f"❌ {name}: gagal diproses — {friendly_error(e)}"))

    if not frames:
        return None, messages
    combined = pd.concat(frames, ignore_index=True)
    return combined, messages


# ---------- Normalisasi dataframe ----------
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

    cols = list(df.columns)
    if mode == "jurnal":
        c_akun = _find_col(cols, ["akun", "account", "keterangan", "uraian", "nama", "perkiraan"])
        c_deb = _find_col(cols, ["debet", "debit"])
        c_kre = _find_col(cols, ["kredit", "credit"])
        text_cols = [c for c in cols if df[c].dtype == object]
        if c_akun is None:
            c_akun = text_cols[0] if text_cols else cols[0]
        out = pd.DataFrame()
        out["Akun"] = df[c_akun].astype(str) if c_akun in df else ""
        out["Debet"] = df[c_deb].map(to_num) if c_deb in df else 0.0
        out["Kredit"] = df[c_kre].map(to_num) if c_kre in df else 0.0
        return out.reset_index(drop=True)
    else:
        c_item = _find_col(cols, ["item", "pos", "akun", "keterangan", "uraian", "nama"])
        c_tar = _find_col(cols, ["target", "anggaran", "budget", "rencana"])
        c_real = _find_col(cols, ["realisasi", "realization", "aktual", "actual", "realized"])
        text_cols = [c for c in cols if df[c].dtype == object]
        if c_item is None:
            c_item = text_cols[0] if text_cols else cols[0]
        out = pd.DataFrame()
        out["Item"] = df[c_item].astype(str) if c_item in df else ""
        out["Target"] = df[c_tar].map(to_num) if c_tar in df else 0.0
        out["Realisasi"] = df[c_real].map(to_num) if c_real in df else 0.0
        return out.reset_index(drop=True)


# ---------- Perhitungan analisis ----------
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
        "yang rinci, akademis, terstruktur, dan mudah dipahami dalam Bahasa Indonesia."
    )
    table_md = df.to_markdown(index=False)
    if mode == "jurnal":
        ctx = (
            f"Mode: Jurnal (Debet vs Kredit).\n"
            f"Total Debet: {totals['total_debet']:.2f}\n"
            f"Total Kredit: {totals['total_kredit']:.2f}\n"
            f"Selisih (Debet-Kredit): {totals['selisih']:.2f}\n"
            f"Status keseimbangan: {'SEIMBANG' if totals['balanced'] else 'TIDAK SEIMBANG'}\n"
        )
    else:
        ctx = (
            f"Mode: Target vs Realisasi.\n"
            f"Total Target: {totals['total_target']:.2f}\n"
            f"Total Realisasi: {totals['total_realisasi']:.2f}\n"
            f"Selisih (Realisasi-Target): {totals['selisih']:.2f}\n"
        )
    prompt = (
        f"{ctx}\nTabel data:\n{table_md}\n\n"
        "Buat 'Penjelasan & Analisis Audit' yang eksplisit dengan struktur markdown berikut:\n"
        "### 1. Akun/Item yang Mengalami Selisih atau Ketidakseimbangan\n"
        "### 2. Penyebab Deviasi\n"
        "(Jelaskan mis. sisi Debet melebihi Kredit, transaksi tidak simetris, atau selisih nominal realisasi)\n"
        "### 3. Rekomendasi Tindakan Koreksi Pembukuan\n"
        "(Berikan rekomendasi jurnal koreksi / penyesuaian secara profesional)\n"
        "Gunakan angka konkret dari data. Ringkas namun rinci dan profesional."
    )
    try:
        return llm_call(system, prompt)
    except Exception as e:
        msg = str(e)
        if "budget" in msg.lower() or "exceeded" in msg.lower():
            return ("> ⚠️ **Analisis AI sementara tidak tersedia** — kuota Universal Key habis. "
                    "Metrik saldo & tabel selisih di atas tetap valid. Silakan isi ulang saldo key "
                    "(Profile → Manage plan → Universal Key → Add Balance) lalu jalankan ulang analisis.")
        if "timeout" in msg.lower():
            return "> ⏱️ **Analisis AI melebihi batas waktu.** Coba lagi; metrik & tabel selisih tetap ditampilkan."
        return f"> ⚠️ **Analisis AI gagal.** Metrik & tabel selisih tetap ditampilkan. Detail: {msg}"


# ---------- Ekspor ----------
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
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
    )
    ss = getSampleStyleSheet()
    navy = colors.HexColor("#1E3A5F")
    gold = colors.HexColor("#B8860B")
    title_style = ParagraphStyle("t", parent=ss["Title"], textColor=navy, fontSize=17)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=navy, spaceBefore=10)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, textColor=colors.grey)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9.5, leading=14)

    story = []
    story.append(Paragraph(APP_TITLE, title_style))
    story.append(Paragraph(f"© {CURRENT_YEAR} {OWNER}. All Rights Reserved.", small))
    story.append(Paragraph(
        f"Tanggal cetak: {datetime.now().strftime('%d %B %Y, %H:%M')} WIB", small))
    story.append(Spacer(1, 8))

    # Ringkasan saldo
    if mode == "jurnal":
        summary = [
            ["Total Debet", rupiah(totals["total_debet"])],
            ["Total Kredit", rupiah(totals["total_kredit"])],
            ["Selisih (D-K)", rupiah(totals["selisih"])],
            ["Status", "SEIMBANG" if totals["balanced"] else "TIDAK SEIMBANG"],
        ]
    else:
        summary = [
            ["Total Target", rupiah(totals["total_target"])],
            ["Total Realisasi", rupiah(totals["total_realisasi"])],
            ["Selisih (R-T)", rupiah(totals["selisih"])],
        ]
    story.append(Paragraph("Ringkasan Saldo", h2))
    st_tbl = Table(summary, colWidths=[70 * mm, 100 * mm])
    st_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2F7")),
        ("TEXTCOLOR", (0, 0), (0, -1), navy),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(st_tbl)
    story.append(Spacer(1, 10))

    # Tabel data dengan penanda warna
    story.append(Paragraph("Tabel Data & Selisih", h2))
    headers = list(df.columns)
    data = [headers] + df.astype(object).values.tolist()
    # format angka
    numeric_cols = [c for c in headers if c not in ("Akun", "Item")]
    for r in range(1, len(data)):
        for ci, c in enumerate(headers):
            if c in numeric_cols:
                try:
                    data[r][ci] = f"{float(data[r][ci]):,.2f}"
                except Exception:
                    pass
    tbl = Table(data, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]
    if "Selisih" in headers:
        sidx = headers.index("Selisih")
        for r in range(1, len(data)):
            try:
                val = float(str(data[r][sidx]).replace(",", ""))
            except Exception:
                val = 0.0
            if abs(val) > 0.001:
                style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#FDE2E1")))
                style.append(("TEXTCOLOR", (sidx, r), (sidx, r), colors.HexColor("#B91C1C")))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    story.append(Spacer(1, 12))

    # Penjelasan audit
    story.append(Paragraph("Penjelasan & Analisis Audit", h2))
    for line in (explanation or "").split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        clean = re.sub(r"[#*`]", "", line)
        if line.startswith("###") or line.startswith("##"):
            story.append(Paragraph(f"<b>{clean.strip()}</b>", body))
        else:
            story.append(Paragraph(clean, body))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        f"<i>Dokumen ini dihasilkan otomatis. © {CURRENT_YEAR} {OWNER}. All Rights Reserved.</i>",
        small))

    doc.build(story)
    return buf.getvalue()


# ---------- STYLING ----------
def inject_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
        h1, h2, h3, .app-brand { font-family: 'Fraunces', serif !important; }
        #MainMenu, header [data-testid="stToolbar"], footer {visibility: hidden;}
        .app-hero {
            background: linear-gradient(120deg, #1E3A5F 0%, #274b78 60%, #2f5a8f 100%);
            color: #fff; padding: 26px 30px; border-radius: 16px; margin-bottom: 8px;
            box-shadow: 0 10px 30px rgba(30,58,95,.25);
        }
        .app-hero h1 { color:#fff !important; margin:0; font-size: clamp(1.5rem, 4vw, 2.4rem); }
        .app-hero p { color:#d7e3f4; margin:6px 0 0; font-size:.95rem; }
        .gold-pill {
            display:inline-block; background:#B8860B; color:#fff; padding:3px 12px;
            border-radius:999px; font-size:.72rem; letter-spacing:.5px; margin-bottom:10px;
        }
        .app-footer {
            text-align:center; color:#64748b; font-size:.8rem; padding:22px 0 8px;
            border-top:1px solid #e2e8f0; margin-top:34px;
        }
        .stButton>button {
            border-radius:10px; font-weight:600;
        }
        div[data-testid="stMetric"] {
            background:#fff; border:1px solid #e2e8f0; border-radius:14px;
            padding:14px 16px; box-shadow:0 2px 8px rgba(15,23,42,.04);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------- APP ----------
def main():
    inject_css()

    if "df" not in st.session_state:
        st.session_state.df = None
    if "analysis" not in st.session_state:
        st.session_state.analysis = None

    # Sidebar
    with st.sidebar:
        st.markdown(f"<div class='app-brand' style='font-size:1.15rem;color:#1E3A5F;font-weight:600'>📊 {APP_TITLE}</div>", unsafe_allow_html=True)
        st.caption(f"oleh {OWNER}")
        st.divider()
        mode_label = st.radio(
            "Mode Analisis",
            ["Jurnal (Debet & Kredit)", "Target vs Realisasi"],
            key="mode_label",
        )
        mode = "jurnal" if mode_label.startswith("Jurnal") else "realisasi"

        st.markdown("**Metode Ekstraksi**")
        st.caption("📄 PDF/Excel/CSV → teks langsung (tanpa kuota AI). "
                   "🖼️ Gambar → OCR lokal Tesseract" + (" (tersedia)" if has_tesseract() else " (tidak terpasang)") + ". "
                   "AI Vision hanya dipakai sebagai cadangan untuk dokumen hasil scan.")
        if not EMERGENT_LLM_KEY:
            st.info("AI Vision (cadangan) tidak aktif — EMERGENT_LLM_KEY belum diset.")
        else:
            st.success("AI Vision cadangan aktif (GPT-5.4)")

        st.divider()
        st.markdown("**🗂️ Riwayat Analisis**")
        hist = load_history()
        if hist:
            if st.button("🧹 Bersihkan Semua Riwayat", key="clear_hist",
                         use_container_width=True):
                clear_history()
                st.rerun()
        else:
            st.caption("Belum ada riwayat.")
        for h in hist:
            ts = h.get("timestamp", "")
            try:
                date_s = datetime.fromisoformat(ts).strftime("%d %b %H:%M")
            except Exception:
                date_s = ts[:16].replace("T", " ")
            src = h.get("source_label") or h.get("mode", "")
            short = src if len(src) <= 15 else src[:13] + "…"
            label = f"{short} ({date_s})"
            item_col, del_col = st.columns([4, 1])
            if item_col.button(label, key=f"h_{h.get('id')}", use_container_width=True,
                               help=f"{src} — mode {h.get('mode','')}"):
                st.session_state.df = pd.DataFrame(h.get("rows", []))
                st.session_state.analysis = {
                    "df": pd.DataFrame(h.get("full_rows", h.get("rows", []))),
                    "totals": h.get("totals", {}),
       
