import re
import io
import fitz  # PyMuPDF
import pandas as pd
import streamlit as st

# ==========================================
# 1. KONSTANTA KATA KUNCI FILTERING (NOISE)
# ==========================================

HEADER_COL_KW = ("debet", "kredit", "target", "realisasi", "akun", "item", "keterangan", "uraian")
SIGN_KW = ("mengetahui", "menyetujui", "disetujui", "mengesahkan", "dibuat oleh", "diperiksa", "disusun", "direktur", "pimpinan", "tanda tangan")
CLOSING_KW = ("catatan:", "keterangan:", "nb:", "pembukuan selesai")

EXCLUDE_KEYWORDS = (
    # Alamat & Lokasi
    "jalan ", "jl. ", "jl ", "rt.", "rw.", "kelurahan", "kecamatan", 
    "kabupaten", "provinsi", "kodepos", "pos ", "komplek", "gedung", "lantai",
    # Identitas Kantor / Cabang / Judul Laporan
    "cabang", "kantor", "posisi", "laporan", "buku besar", "jurnal umum",
    # Filter Tambahan Non-Tabel
    "total", "jumlah", "saldo akhir", "sub total", "subtotal", "grand total",
    "mengetahui", "menyetujui", "disetujui", "mengesahkan", "dibuat oleh",
    "diperiksa", "disusun", "penyusun", "direktur", "bendahara", "sekretaris",
    "pimpinan", "tanda tangan", "hormat kami", "nip", "nik", "saldo awal", "saldoawal",
    "kode perkiraan", "nama perkiraan", "periode", "tanggal"
)

MONTH_REGEX = re.compile(
    r"\b(januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)\b", 
    re.IGNORECASE
)

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================

def to_num(val) -> float:
    """Mengonversi string angka (termasuk format Indonesia/Kurung) menjadi float."""
    if isinstance(val, (int, float)):
        return float(val)
    if not val:
        return 0.0
    
    s = str(val).strip()
    is_negative = False
    
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        is_negative = True
        s = s[1:].strip()
        
    s = s.replace(".", "").replace(",", ".")
    try:
        num = float(re.sub(r"[^\d.]", "", s))
        return -num if is_negative else num
    except ValueError:
        return 0.0


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Mengekstrak seluruh teks dari file PDF."""
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text() + "\n"
    return text


def parse_text_rows(text: str, mode: str) -> pd.DataFrame:
    """Merapikan teks hasil ekstraksi dan memfilter baris non-tabel/alamat/header."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    num_re = re.compile(r"\(?-?[\d][\d.,]*\)?")

    # Cari titik awal tabel berdasarkan kata kunci header
    start = 0
    for i, ln in enumerate(lines):
        low = ln.lower()
        if sum(1 for k in HEADER_COL_KW if k in low) >= 2:
            start = i + 1
            break

    rows = []
    for raw_line in lines[start:]:
        line = raw_line.strip()
        if not line:
            continue
        
        low = line.lower()

        # Hentikan jika masuk area footer/tanda tangan
        if any(k in low for k in SIGN_KW) or any(k in low for k in CLOSING_KW):
            break

        # Filter kata kunci non-tabel (alamat, periode, identitas)
        if any(k in low for k in EXCLUDE_KEYWORDS):
            continue
            
        if low.startswith("//") or MONTH_REGEX.search(low):
            continue

        nums = num_re.findall(line)
        label = num_re.sub(" ", line).strip(" .:-\t|/")

        if not label or len(label) < 2 or not nums:
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


def compute(df: pd.DataFrame, mode: str):
    """Menghitung total, selisih, dan mengidentifikasi baris yang tidak seimbang."""
    df = df.copy()
    if mode == "jurnal":
        df["Debet"] = df["Debet"].map(to_num)
        df["Kredit"] = df["Kredit"].map(to_num)
        df["Selisih"] = (df["Debet"] - df["Kredit"]).round(2)
        
        total_debet = float(df["Debet"].sum())
        total_kredit = float(df["Kredit"].sum())
        diff = round(total_debet - total_kredit, 2)
        
        totals = {
            "total_debet": total_debet,
            "total_kredit": total_kredit,
            "selisih": diff,
            "balanced": abs(diff) < 0.01,
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
        
        totals = {
            "total_target": total_target,
            "total_realisasi": total_real,
            "selisih": diff,
            "balanced": abs(diff) < 0.01,
        }
        imbalanced = df[df["Selisih"].abs() > 0.001]
        
    return df, totals, imbalanced

# ==========================================
# 3. INTERFASE APLIKASI (STREAMLIT UI)
# ==========================================

st.set_page_config(page_title="Audit & Parser Laporan Finance", layout="wide")
st.title("📊 Aplikasi Audit & Parser Laporan Keuangan")

mode = st.sidebar.selectbox("Pilih Jenis Laporan", ["jurnal", "anggaran"], format_func=lambda x: "Jurnal (Debet vs Kredit)" if x == "jurnal" else "Anggaran (Target vs Realisasi)")
uploaded_file = st.file_uploader("Unggah File Laporan (PDF / CSV / XLSX)", type=["pdf", "csv", "xlsx"])

if uploaded_file:
    file_type = uploaded_file.name.split(".")[-1].lower()
    df_raw = pd.DataFrame()

    if file_type == "pdf":
        raw_text = extract_text_from_pdf(uploaded_file.read())
        df_raw = parse_text_rows(raw_text, mode)
    elif file_type == "csv":
        df_raw = pd.read_csv(uploaded_file)
    elif file_type == "xlsx":
        df_raw = pd.read_excel(uploaded_file)

    if not df_raw.empty:
        df_processed, totals, imbalanced = compute(df_raw, mode)

        st.subheader("📌 Ringkasan Audit")
        col1, col2, col3 = st.columns(3)
        
        if mode == "jurnal":
            col1.metric("Total Debet", f"Rp {totals['total_debet']:,.2f}")
            col2.metric("Total Kredit", f"Rp {totals['total_kredit']:,.2f}")
            col3.metric("Status Keseimbangan", "SEIMBANG" if totals['balanced'] else "TIDAK SEIMBANG", delta=f"{totals['selisih']:,.2f}")
        else:
            col1.metric("Total Target", f"Rp {totals['total_target']:,.2f}")
            col2.metric("Total Realisasi", f"Rp {totals['total_realisasi']:,.2f}")
            col3.metric("Total Selisih", f"Rp {totals['selisih']:,.2f}")

        st.subheader("📋 Data Hasil Ekstraksi Tabel")
        st.dataframe(df_processed, use_container_width=True)

        if not imbalanced.empty:
            st.warning(f"⚠️ Ditemukan {len(imbalanced)} baris yang memiliki selisih!")
            st.dataframe(imbalanced, use_container_width=True)
    else:
        st.error("Tabel tidak ditemukan atau seluruh baris terfilter sebagai data non-tabel.")
