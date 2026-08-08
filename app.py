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
    import fitz  # PyMuPDF
    out = []
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    for page in doc[:max_pages]:
        pix = page.get_pixmap(dpi=150)
        out.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return out


# ---------- Ekstraksi teks langsung (TANPA AI / kuota) ----------
# Kata kunci untuk mendeteksi baris HEADER tabel (kolom)
HEADER_COL_KW = ("akun", "uraian", "keterangan", "perkiraan", "nama akun", "debet",
                 "debit", "kredit", "credit", "target", "realisasi", "item", "pos",
                 "anggaran", "nominal")
# Kata kunci baris pengesahan / tanda tangan / penutup (footer) → hentikan pembacaan
SIGN_KW = ("mengetahui", "menyetujui", "disetujui", "mengesahkan", "dibuat oleh",
           "diperiksa", "disusun", "penyusun", "ketua", "wakil", "manajer", "manager",
           "direktur", "direktris", "bendahara", "sekretaris", "kepala", "pimpinan",
           "atasan", "nip", "nik", "tanda tangan", "ttd", "hormat kami", "stempel",
           "materai", "pejabat", "auditor", "akuntan publik", "an.", "a.n.", "u.b.",
           "mengesyahkan")
# Kata kunci catatan kaki / penutup laporan
CLOSING_KW = ("catatan:", "keterangan:", "demikian", "laporan ini", "dibuat dengan",
              "*)", "**)", "disclaimer")
# Kata kunci baris judul / kop dokumen
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
    """Gabungkan huruf ter-spasi ('T O T A L' → 'TOTAL', 'J U M L A H' → 'JUMLAH')."""
    return re.sub(r"(?:\b[A-Za-z]\b\s*){2,}",
                  lambda m: m.group(0).replace(" ", ""), str(s))


def is_noise_label(label) -> bool:
    """True bila label baris merupakan Total/rekap/pengesahan/kosong (bukan data akun)."""
    low = _despace(str(label)).strip().lower()
    if low in ("", "nan", "none"):
        return True
    return any(k in low for k in ROW_NOISE_KW)


def clean_header(name) -> str:
    """Rapikan nama kolom, termasuk gabungkan huruf ter-spasi ('U r a i a n' → 'Uraian')."""
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
    """Buang tanggal, kode transaksi/bukti, dan angka dari sebuah baris → sisakan uraian."""
    s = DATE_RE.sub(" ", str(line))
    s = CODE_RE.sub(" ", s)
    s = re.sub(r"\(?-?\d[\d.,]*\)?", " ", s)  # buang angka
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
    """Parse teks mentah (pdfplumber/OCR) → hanya baris DATA tabel (adaptif).

    - Deteksi header tabel; baris kop/judul di atasnya diabaikan.
    - Baris deskripsi (tanpa nominal) digabung sebagai keterangan baris nominal berikutnya.
    - Nominal dikenali cerdas (bukan tanggal/kode); kolom Saldo (nominal terakhir) diabaikan.
    - Baris pengesahan/tanda tangan/total/kop otomatis dibuang.
    """
    lines = [ln.strip() for ln in (text or "").splitlines()]
    num_re = re.compile(r"\(?-?[\d][\d.,]*\)?")

    start = 0
    for i, ln in enumerate(lines):
        if sum(1 for k in HEADER_COL_KW if k in ln.lower()) >= 2:
            start = i + 1
            break

    rows = []
    pending = []  # fragmen deskripsi yang menunggu baris nominal
    for raw_line in lines[start:]:
        line = raw_line
        if not line:
            continue
        low = line.lower()
        nums = num_re.findall(line)
        amts = [to_num(t) for t in nums if is_amount_token(t)]

        if not amts:
            # baris tanpa nominal → deskripsi atau noise
            if _is_noise_line(low):
                pending = []
            else:
                desc = _clean_label(line)
                if desc:
                    pending.append(desc)
            continue

        # baris rekap (Total/Jumlah/Saldo) yang kebetulan punya nominal → buang
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
                debet, kredit = amts[-3], amts[-2]   # abaikan Saldo (terakhir)
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
    """True bila token angka tampak sebagai NOMINAL uang (bukan tahun/kode/no. bukti).

    Menerima format Indonesia desimal-koma ('3.910.000,00', '0,00'), ribuan-titik
    ('5.000.000'), atau nol polos ('0'). Menolak angka polos seperti '2025' / '0000051'.
    """
    t = str(tok).strip().strip("()")
    if t in ("0", "-0"):
        return True
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d+", t):      # 3.910.000,00 / 0,00
        return True
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):          # 5.000.000
        return True
    if re.fullmatch(r"-?\d+,\d+", t):                    # 12345,67
        return True
    return False


def pdf_extract_direct(raw_bytes: bytes, mode: str, max_pages: int = 30) -> pd.DataFrame:
    """Ekstrak isi tabel PDF digital tanpa AI. Utamakan parsing TEKS (lebih tahan
    terhadap tabel yang terfragmentasi & kolom Saldo); tabel dipakai bila teks kosong."""
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

    # 1) Utamakan parsing TEKS per-baris (adaptif; tahan tabel terfragmentasi & kolom Saldo)
    text_df = parse_text_rows("\n".join(text_accum), mode)
    if text_df is not None and not text_df.empty:
        return text_df.reset_index(drop=True)

    # 2) Fallback: ekstraksi TABEL lalu normalisasi
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
    messages = []  # (level, text) — level: ok | warn | error
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


def _pick_label_col(df, cols, keyword_col, num_cols):
    """Pilih kolom deskripsi/akun: prioritas keyword, jika tidak ada pakai kolom teks terpanjang."""
    if keyword_col is not None:
        return keyword_col
    exclude = set(num_cols)
    excl_kw = ("saldo", "balance", "tgl", "tanggal", "date", "kode", "no ", "no.",
               "bukti", "ref", "no bukti", "nomor")
    candidates = []
    for c in cols:
        if c in exclude:
            continue
        cl = str(c).lower()
        if any(k in cl for k in excl_kw):
            continue
        candidates.append(c)
    if not candidates:
        candidates = [c for c in cols if c not in exclude] or list(cols)
    try:
        return max(candidates, key=lambda c: df[c].astype(str).map(len).mean())
    except Exception:
        return candidates[0]


def normalize_df(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    if df is None or df.empty:
        if mode == "jurnal":
            return pd.DataFrame([{"Akun": "", "Debet": 0.0, "Kredit": 0.0}])
        return pd.DataFrame([{"Item": "", "Target": 0.0, "Realisasi": 0.0}])

    # Rapikan nama kolom (mis. 'U r a i a n' → 'Uraian', hilangkan newline)
    df = df.rename(columns={c: clean_header(c) for c in df.columns})
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    cols = list(df.columns)

    if mode == "jurnal":
        c_deb = _find_col(cols, ["debet", "debit"])
        c_kre = _find_col(cols, ["kredit", "credit"])
        kw_label = _find_col(cols, ["uraian", "keterangan", "akun", "account",
                                    "deskripsi", "description", "perkiraan", "nama"])
        c_akun = _pick_label_col(df, cols, kw_label, [c_deb, c_kre])
        out = pd.DataFrame()
        out["Akun"] = df[c_akun].astype(str).str.replace("\n", " ", regex=False).str.strip() if c_akun in df else ""
        out["Debet"] = df[c_deb].map(to_num) if c_deb in df else 0.0
        out["Kredit"] = df[c_kre].map(to_num) if c_kre in df else 0.0
        out = out[~out["Akun"].map(is_noise_label)]
        # buang baris tanpa nominal (mis. SALDO AWAL / baris kosong)
        out = out[(out["Debet"].abs() > 0) | (out["Kredit"].abs() > 0)].reset_index(drop=True)
        return out if not out.empty else pd.DataFrame([{"Akun": "", "Debet": 0.0, "Kredit": 0.0}])
    else:
        c_tar = _find_col(cols, ["target", "anggaran", "budget", "rencana", "pagu"])
        c_real = _find_col(cols, ["realisasi", "realization", "aktual", "actual", "realized"])
        kw_label = _find_col(cols, ["item", "uraian", "keterangan", "pos", "akun",
                                    "kegiatan", "program", "nama"])
        c_item = _pick_label_col(df, cols, kw_label, [c_tar, c_real])
        out = pd.DataFrame()
        out["Item"] = df[c_item].astype(str).str.replace("\n", " ", regex=False).str.strip() if c_item in df else ""
        out["Target"] = df[c_tar].map(to_num) if c_tar in df else 0.0
        out["Realisasi"] = df[c_real].map(to_num) if c_real in df else 0.0
        out = out[~out["Item"].map(is_noise_label)]
        out = out[(out["Target"].abs() > 0) | (out["Realisasi"].abs() > 0)].reset_index(drop=True)
        return out if not out.empty else pd.DataFrame([{"Item": "", "Target": 0.0, "Realisasi": 0.0}])


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
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
    )
    ss = getSampleStyleSheet()
    navy = colors.HexColor("#1E3A5F")
    
    title_style = ParagraphStyle("TitleStyle", parent=ss["Title"], textColor=navy, fontSize=15, leading=18, alignment=0)
    h2 = ParagraphStyle("Heading2Style", parent=ss["Heading2"], textColor=navy, fontSize=11, leading=15, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("SmallStyle", parent=ss["Normal"], fontSize=8, leading=10, textColor=colors.grey)
    body = ParagraphStyle("BodyStyle", parent=ss["Normal"], fontSize=8.5, leading=12, textColor=colors.HexColor("#1E293B"))
    
    th_style = ParagraphStyle("THStyle", parent=ss["Normal"], fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")
    td_style = ParagraphStyle("TDStyle", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#1E293B"))
    td_red_style = ParagraphStyle("TDRedStyle", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#DC2626"), fontName="Helvetica-Bold")

    elements = []

    # Kop Laporan
    elements.append(Paragraph(f"<b>{APP_TITLE}</b>", title_style))
    elements.append(Paragraph(f"Hak Cipta © {CURRENT_YEAR} {OWNER}. Seluruh Hak Cipta Dilindungi.", small))
    elements.append(Paragraph(f"<i>Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M WIB')}</i>", small))
    elements.append(Spacer(1, 8))

    # Ringkasan Eksekutif
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
            [Paragraph("Selisih (Realisasi - Target)", td_style), Paragraph(rupiah(totals["selisih"]), td_style)],
            [Paragraph("Status", td_style), Paragraph("<b>SESUAI</b>" if totals["balanced"] else "<font color='red'><b>DEVIASI</b></font>", td_style)],
        ]

    t_summary = Table(summary_data, colWidths=[110 * mm, 70 * mm])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 10))

    # Deteksi Pasangan Jurnal Berpasangan (Per Dua Baris) Yang Selisih
    bad_rows_indices = set()
    n_rows = len(df)
    
    for i in range(0, n_rows, 2):
        if i + 1 < n_rows:
            d_val1 = float(df.iloc[i].get("Debet", 0) or 0)
            k_val1 = float(df.iloc[i].get("Kredit", 0) or 0)
            d_val2 = float(df.iloc[i+1].get("Debet", 0) or 0)
            k_val2 = float(df.iloc[i+1].get("Kredit", 0) or 0)
            
            if abs((d_val1 + d_val2) - (k_val1 + k_val2)) > 0.01:
                bad_rows_indices.add(i + 1)
                bad_rows_indices.add(i + 2)
        else:
            bad_rows_indices.add(i + 1)

    # Tabel Rincian Data Analisis
    elements.append(Paragraph("<b>Rincian Data Analisis</b>", h2))
    headers = list(df.columns)
    
    header_row = [Paragraph(f"<b>{h}</b>", th_style) for h in headers]
    table_rows = [header_row]
    
    for idx, row in df.iterrows():
        r_list = []
        is_bad = (idx + 1) in bad_rows_indices

        for col in headers:
            val = row[col]
            if isinstance(val, (int, float)) and col != "% Deviasi":
                txt = rupiah(val)
            else:
                txt = str(val)

            if is_bad:
                r_list.append(Paragraph(txt, td_red_style))
            else:
                r_list.append(Paragraph(txt, td_style))
        
        table_rows.append(r_list)

    if len(headers) == 4:
        col_widths = [84 * mm, 34 * mm, 34 * mm, 34 * mm]
    elif len(headers) == 3:
        col_widths = [96 * mm, 45 * mm, 45 * mm]
    else:
        col_widths = [(186 * mm) / len(headers)] * len(headers)

    t_detail = Table(table_rows, colWidths=col_widths, repeatRows=1)
    
    t_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]

    for r_idx in bad_rows_indices:
        t_styles.append(('BACKGROUND', (0, r_idx), (-1, r_idx), colors.HexColor("#FEE2E2")))

    t_detail.setStyle(TableStyle(t_styles))
    elements.append(t_detail)
    elements.append(Spacer(1, 10))

    # Penjelasan & Catatan Analisis Audit
    if explanation:
        if "EMERGENT_LLM_KEY" in explanation or "Analisis AI tidak tersedia" in explanation:
            clean_exp = "Catatan Audit: Laporan diekspor secara otomatis berdasarkan data transaksi yang diinput. Harap lakukan penyesuaian/jurnal koreksi pada akun yang ditandai merah."
        else:
            clean_exp = explanation.replace("#", "").replace("*", "")

        elements.append(Paragraph("<b>Penjelasan & Catatan Analisis Audit</b>", h2))
        for line in clean_exp.split("\n"):
            if line.strip():
                elements.append(Paragraph(line.strip(), body))
                elements.append(Spacer(1, 2))

    doc.build(elements)
    return buf.getvalue()


# ---------- STYLING ----------
def inject_css():
    st.markdown(
        """
        <style>
        [data-testid="stMetricLabel"] { color: #1E293B !important; font-weight: 700 !important; }
        [data-testid="stMetricValue"] { color: #0F172A !important; font-weight: 800 !important; }
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
                    "explanation": h.get("explanation", ""),
                    "mode": h.get("mode", mode),
                }
                st.rerun()
            if del_col.button("🗑️", key=f"del_{h.get('id')}", use_container_width=True,
                              help="Hapus item ini"):
                delete_history(h.get("id"))
                st.rerun()

    # Hero
    st.markdown(
        f"""
        <div class="app-hero">
            <span class="gold-pill">PROFESSIONAL EDITION</span>
            <h1>{APP_TITLE}</h1>
            <p>Ekstraksi AI Vision presisi tinggi • Pengecekan keseimbangan jurnal • Analisis selisih & audit otomatis</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ===== Langkah 1: Input =====
    st.subheader("① Input Dokumen")
    input_mode = st.radio(
        "Metode Input",
        ["📁 Upload File (Desktop/HP)", "📷 Kamera (HP)"],
        horizontal=True,
        key="input_mode",
    )
    files = []  # list of {name, kind, data}

    if input_mode.startswith("📷"):
        st.caption("Kamera aktif hanya di mode ini. Pindah ke 'Upload File' untuk mematikan kamera.")
        cam = st.camera_input("Ambil foto laporan / jurnal", key="cam")
        if cam is not None:
            files.append({"name": "foto-kamera.jpg", "kind": "image", "data": cam.getvalue()})
    else:
        up = st.file_uploader(
            "Unggah Excel (.xlsx), CSV, PDF, atau Foto (JPG/PNG) — bisa banyak file sekaligus",
            type=["xlsx", "xls", "csv", "pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="uploader",
        )
        if up:
            for f in up:
                name = f.name
                low = name.lower()
                if low.endswith((".xlsx", ".xls")):
                    kind = "excel"
                elif low.endswith(".csv"):
                    kind = "csv"
                elif low.endswith(".pdf"):
                    kind = "pdf"
                else:
                    kind = "image"
                files.append({"name": name, "kind": kind, "data": f.getvalue()})

    if files:
        st.caption(f"📎 {len(files)} file siap diproses: " + ", ".join(x["name"] for x in files))

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("🚀 Ekstrak Data", type="primary", use_container_width=True,
                     disabled=not files):
            prog = st.progress(0.0, text="Mempersiapkan...")

            def _cb(i, total, name):
                prog.progress(i / max(total, 1), text=f"Memproses ({i}/{total}): {name}")

            combined, messages = process_files(files, mode, progress_cb=_cb, timeout=600)
            prog.empty()
            for level, text in messages:
                if level == "ok":
                    st.success(text)
                elif level == "warn":
                    st.warning(text)
                else:
                    st.error(text)
            if combined is not None and not combined.empty:
                st.session_state.df = combined
                st.session_state.analysis = None
                st.session_state.source_files = [x["name"] for x in files]
                st.success(f"Total {len(combined)} baris siap dikoreksi dari {len(files)} file.")
            else:
                st.error("Tidak ada data yang berhasil diekstrak dari file yang diunggah.")
    with c2:
        st.caption("Excel/CSV/PDF digital diekstrak langsung (tanpa kuota AI). Foto/gambar memakai "
                   "OCR lokal Tesseract; AI Vision hanya cadangan untuk dokumen scan. "
                   "File diproses satu per satu — jika satu gagal, lainnya tetap diproses. "
                   "Selalu periksa & koreksi hasil di tabel sebelum mengunci analisis.")

    # ===== Langkah 2: Edit interaktif =====
    if st.session_state.df is not None and not st.session_state.df.empty:
        st.subheader("② Koreksi Data (Human-in-the-Loop)")
        st.caption("Perbaiki angka/nama akun yang salah baca sebelum mengunci analisis. "
                   "Anda dapat menambah atau menghapus baris.")
        edited = st.data_editor(
            st.session_state.df,
            num_rows="dynamic",
            use_container_width=True,
            key="editor",
        )

        if st.button("🔒 Kunci Data & Jalankan Analisis", type="primary"):
            with st.spinner("Menghitung selisih & menyusun analisis audit..."):
                full_df, totals, imbalanced = compute(normalize_df(edited, mode), mode)
                explanation = ai_analysis(full_df, totals, imbalanced, mode) if EMERGENT_LLM_KEY else \
                    "_Analisis AI tidak tersedia (EMERGENT_LLM_KEY belum diset)._"
                st.session_state.analysis = {
                    "df": full_df, "totals": totals, "imbalanced": imbalanced,
                    "explanation": explanation, "mode": mode,
                }
                src_files = st.session_state.get("source_files", [])
                src_label = ", ".join(src_files) if src_files else "Input manual"
                record = {
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "mode": mode,
                    "source_files": src_files,
                    "source_label": src_label,
                    "rows": normalize_df(edited, mode).to_dict("records"),
                    "full_rows": full_df.astype(object).to_dict("records"),
                    "totals": totals,
                    "explanation": explanation,
                }
                save_history(record)
            st.rerun()

    # ===== Langkah 3: Hasil =====
    res = st.session_state.analysis
    if res:
        rmode = res["mode"]
        df = res["df"]
        totals = res["totals"]
        st.subheader("③ Hasil Analisis & Selisih")

        if rmode == "jurnal":
            r1c1, r1c2 = st.columns(2)
            r1c1.metric("Total Debet", rupiah(totals.get("total_debet", 0)))
            r1c2.metric("Total Kredit", rupiah(totals.get("total_kredit", 0)))
            r2c1, r2c2 = st.columns(2)
            r2c1.metric("Selisih (D-K)", rupiah(totals.get("selisih", 0)))
            r2c2.metric("Status", "SEIMBANG ✅" if totals.get("balanced") else "TIDAK SEIMBANG ⚠️")
            if not totals.get("balanced"):
                st.error(f"⚠️ Jurnal TIDAK SEIMBANG. Selisih Debet-Kredit sebesar {rupiah(totals.get('selisih',0))}.")
            else:
                st.success("✅ Jurnal SEIMBANG — Total Debet = Total Kredit.")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Target", rupiah(totals.get("total_target", 0)))
            m2.metric("Total Realisasi", rupiah(totals.get("total_realisasi", 0)))
            m3.metric("Selisih (R-T)", rupiah(totals.get("selisih", 0)))

        # Tabel berwarna
        def color_selisih(val):
            try:
                v = float(val)
            except Exception:
                return ""
            if abs(v) > 0.001:
                return "background-color:#fde2e1;color:#b91c1c;font-weight:600"
            return "background-color:#e6f4ea;color:#166534"

        styled = df.style
        if "Selisih" in df.columns:
            styled = styled.map(color_selisih, subset=["Selisih"])
        num_cols = [c for c in df.columns if c not in ("Akun", "Item")
                    and pd.api.types.is_numeric_dtype(df[c])]
        if num_cols:
            styled = styled.format({c: "{:,.2f}" for c in num_cols})
        st.dataframe(styled, use_container_width=True)

        st.subheader("④ Catatan & Ringkasan Audit")
        st.info("💡 Laporan dianalisis secara otomatis berdasarkan data transaksi. Harap periksa akun yang ditandai merah pada tabel di atas untuk melakukan penyesuaian jurnal.")

        # ===== Ekspor =====
        st.subheader("⑤ Ekspor & Cetak Laporan")
        e1, e2, e3 = st.columns(3)
        with e1:
            st.download_button(
                "⬇️ Download Excel (.xlsx)", data=to_excel_bytes(df),
                file_name=f"analisis_{rmode}_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with e2:
            st.download_button(
                "⬇️ Download CSV", data=to_csv_bytes(df),
                file_name=f"analisis_{rmode}_{datetime.now():%Y%m%d_%H%M}.csv",
                mime="text/csv", use_container_width=True,
            )
        with e3:
            try:
                pdf_bytes = build_pdf(df, totals, res.get("imbalanced", df.head(0)),
                                      res["explanation"], rmode)
                st.download_button(
                    "🖨️ Download / Cetak PDF", data=pdf_bytes,
                    file_name=f"Laporan_Analisis_{datetime.now():%Y%m%d_%H%M}.pdf",
                    mime="application/pdf", use_container_width=True,
                )
            except Exception as e:
                st.error(f"Gagal membuat PDF: {e}")

    # Footer
    st.markdown(
        f"<div class='app-footer'>© {CURRENT_YEAR} {OWNER}. All Rights Reserved.</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
