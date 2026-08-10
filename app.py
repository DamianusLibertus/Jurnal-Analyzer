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

# ---------- Ekstraksi Lokal (PDFPlumber / PyMuPDF) ----------
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
            if any(k in low for k in ["halaman", "jurnal transaksi", "periode", "total", "jumlah", "dicetak"]):
                continue
            
            line_clean = date_re.sub(" ", line)
            line_clean = ref_re.sub(" ", line_clean)
            
            num_tokens = num_re.findall(line_clean)
            amts = [to_num(m) for m in num_tokens if not (m.isdigit() and 2020 <= int(m) <= 2030)]
            
            desc = line_clean
            for m in num_tokens:
                desc = desc.replace(m, " ")
            desc = re.sub(r"\s+", " ", desc).strip(" .-,:|")

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
    df["Debet"] = df["Debet"].apply(to_num)
    df["Kredit"] = df["Kredit"].apply(to_num)
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
        edited_df = st.data_editor(st.session_state.df_raw, num_rows="dynamic", use_container_width=True)

        if st.button("🔒 Kunci Data & Cari Selisih Otomatis", type="primary"):
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
            if abs(row["Selisih"]) > 0.001:
                return ['background-color: #FEE2E2; color: #991B1B; font-weight: bold;'] * len(row)
            return [''] * len(row)

        styled_df = df.style.apply(highlight_selisih_row, axis=1).format({
            "Debet": "{:,.2f}",
            "Kredit": "{:,.2f}",
            "Selisih": "{:,.2f}"
        })
        
        st.dataframe(styled_df, use_container_width=True)

if __name__ == "__main__":
    main()
