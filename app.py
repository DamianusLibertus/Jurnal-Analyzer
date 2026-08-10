# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Selisih Laporan
# =========================================================

import os
import re
import io
import json
import uuid
import base64
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

CURRENT_YEAR = datetime.now().year
APP_TITLE = "Aplikasi Analisis Jurnal & Selisih Laporan"
OWNER = "Damianus Libertus"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Utility Helpers ----------
def to_num(x) -> float:
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s in ("", "-", "--", "nil", "null", "nan", "none", "."):
        return 0.0
    neg = "(" in s and ")" in s
    s = re.sub(r"[^\d,.\-]", "", s)
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

def is_noise_row(val: str) -> bool:
    """Deteksi baris rekap/footer seperti TOTAL dan lokasi cetak."""
    low = str(val).lower().replace(" ", "")
    noise_keywords = ["total", "jumlah", "sanggau", "saldoawal", "saldoakhir", "halaman", "periode"]
    return any(k in low for k in noise_keywords)

# ---------- Ekstraksi Lokal (PDFPlumber) ----------
def extract_pdf_local(raw_bytes: bytes) -> pd.DataFrame:
    try:
        import pdfplumber
        lines = []
        with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                lines.extend(txt.splitlines())
        
        rows = []
        date_re = re.compile(r"\b\d{1,2}[/\.-]\d{1,2}[/\.-]\d{2,4}\b")
        ref_re = re.compile(r"\b(?:TAB|JU|OB|COA|BKK|BKM|KK|KM|ACC)[.-]?\d[\w.-]*\b", re.I)
        num_re = re.compile(r"\(?-?\d{1,3}(?:\.\d{3})*(?:,\d+)?\)?")

        for line in lines:
            low = line.lower()
            if any(k in low for k in ["halaman", "jurnal transaksi", "periode", "dicetak"]):
                continue
            
            line_clean = date_re.sub(" ", line)
            line_clean = ref_re.sub(" ", line_clean)
            
            num_tokens = num_re.findall(line_clean)
            amts = [to_num(m) for m in num_tokens if not (m.isdigit() and 2020 <= int(m) <= 2030)]
            
            desc = line_clean
            for m in num_tokens:
                desc = desc.replace(m, " ")
            desc = re.sub(r"\s+", " ", desc).strip(" .-,:|")

            # Mengabaikan baris TOTAL & Footer sejak ekstraksi awal
            if is_noise_row(desc):
                continue

            if len(amts) >= 2 and len(desc) > 2:
                rows.append({
                    "Akun": desc[:150],
                    "Debet": amts[-2] if len(amts) >= 2 else amts[0],
                    "Kredit": amts[-1] if len(amts) >= 2 else 0.0
                })

        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

# ---------- Hitung Selisih & Koreksi ----------
def compute_jurnal(df: pd.DataFrame):
    df = df.copy()
    if "Debet" in df.columns:
        df["Debet"] = df["Debet"].apply(to_num)
    else:
        df["Debet"] = 0.0

    if "Kredit" in df.columns:
        df["Kredit"] = df["Kredit"].apply(to_num)
    else:
        df["Kredit"] = 0.0

    df["Selisih"] = (df["Debet"] - df["Kredit"]).round(2)
    
    total_debet = float(df["Debet"].sum())
    total_kredit = float(df["Kredit"].sum())
    diff = round(total_debet - total_kredit, 2)
    
    totals = {
        "total_debet": total_debet,
        "total_kredit": total_kredit,
        "selisih": diff,
        "balanced": abs(diff) < 0.01
    }
    return df, totals

# ---------- Main Application ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    st.caption(f"Dikembangkan oleh {OWNER}")
    st.divider()

    up_files = st.file_uploader("Unggah PDF Jurnal Transaksi Asli", type=["pdf", "png", "jpg"], accept_multiple_files=True)

    if st.button("🚀 Mula-mula Baca & Analisis Dokumen", type="primary", disabled=not up_files):
        all_frames = []
        with st.spinner("Membaca isi tabel dan menyesuaikan dengan laporan asli..."):
            for f in up_files:
                df_loc = extract_pdf_local(f.getvalue())
                if not df_loc.empty:
                    all_frames.append(df_loc)
            
            if all_frames:
                st.session_state.df_raw = pd.concat(all_frames, ignore_index=True)
                st.success("Berhasil membaca tabel jurnal secara otomatis!")
            else:
                st.error("Gagal membaca dokumen. Pastikan file PDF berformat tabel jurnal yang jelas.")

    if "df_raw" in st.session_state and st.session_state.df_raw is not None:
        st.subheader("① Pratinjau & Koreksi Data Tabel")

        # ---------- PANEL ALAT TAMBAH / HAPUS KOLOM & BARIS ----------
        with st.expander("🛠️ Alat Pengaturan Kolom & Pembersihan Baris", expanded=True):
            c_clean, c_add, c_del = st.columns(3)
            
            with c_clean:
                st.markdown("**1. Bersihkan Baris Sampah**")
                if st.button("🧹 Hapus Baris TOTAL / Footer", use_container_width=True):
                    col_akun = st.session_state.df_raw.columns[0]
                    st.session_state.df_raw = st.session_state.df_raw[
                        ~st.session_state.df_raw[col_akun].apply(is_noise_row)
                    ].reset_index(drop=True)
                    st.success("Baris T O T A L & Lokasi Cetak berhasil dibersihkan!")
                    st.rerun()

            with c_add:
                st.markdown("**2. Tambah Kolom Baru**")
                new_col_name = st.text_input("Nama Kolom Baru:", key="input_new_col")
                if st.button("➕ Tambah Kolom", use_container_width=True):
                    if new_col_name and new_col_name not in st.session_state.df_raw.columns:
                        st.session_state.df_raw[new_col_name] = ""
                        st.success(f"Kolom '{new_col_name}' berhasil ditambahkan!")
                        st.rerun()

            with c_del:
                st.markdown("**3. Hapus Kolom**")
                col_to_del = st.selectbox("Pilih Kolom yang Dihapus:", st.session_state.df_raw.columns, key="select_col_del")
                if st.button("🗑️ Hapus Kolom", use_container_width=True):
                    if len(st.session_state.df_raw.columns) > 1:
                        st.session_state.df_raw = st.session_state.df_raw.drop(columns=[col_to_del])
                        st.success(f"Kolom '{col_to_del}' berhasil dihapus!")
                        st.rerun()

        st.caption(
            "💡 **Cara Manipulasi Baris Langsung pada Tabel:**\n"
            "- **Tambah Baris Baru:** Gulir ke paling bawah tabel lalu klik baris kosong berciri tanda `+`.\n"
            "- **Hapus Baris:** Centang kotak di paling kiri baris yang ingin dihapus, lalu tekan tombol **Delete** pada keyboard Anda atau klik ikon tong sampah di pojok kanan atas tabel."
        )

        edited_df = st.data_editor(
            st.session_state.df_raw,
            num_rows="dynamic",
            use_container_width=True,
            key="editor_table"
        )

        if st.button("🔒 Kunci Data & Cari Selisih Otomatis", type="primary"):
            st.session_state.df_raw = edited_df
            computed_df, totals = compute_jurnal(edited_df)
            st.session_state.computed_df = computed_df
            st.session_state.totals = totals
            st.rerun()

    if "computed_df" in st.session_state:
        df = st.session_state.computed_df
        totals = st.session_state.totals

        st.divider()
        st.subheader("② Ringkasan Hasil Analisis Selisih")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Debet", rupiah(totals["total_debet"]))
        c2.metric("Total Kredit", rupiah(totals["total_kredit"]))
        c3.metric("Selisih Total", rupiah(totals["selisih"]))
        c4.metric("Status Jurnal", "SEIMBANG ✅" if totals["balanced"] else "TIDAK SEIMBANG ⚠️")

        st.subheader("③ Tabel Transaksi (Akun Selisih Ditandai Merah)")
        
        def highlight_selisih_row(row):
            if "Selisih" in row and abs(row["Selisih"]) > 0.001:
                return ['background-color: #FEE2E2; color: #991B1B; font-weight: bold;'] * len(row)
            return [''] * len(row)

        fmt_dict = {}
        if "Debet" in df.columns: fmt_dict["Debet"] = "{:,.2f}"
        if "Kredit" in df.columns: fmt_dict["Kredit"] = "{:,.2f}"
        if "Selisih" in df.columns: fmt_dict["Selisih"] = "{:,.2f}"

        styled_df = df.style.apply(highlight_selisih_row, axis=1).format(fmt_dict)
        
        st.dataframe(styled_df, use_container_width=True)

if __name__ == "__main__":
    main()
