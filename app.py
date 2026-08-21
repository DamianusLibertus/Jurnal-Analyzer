# =========================================================
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi (Versi Dual-Mode)
# =========================================================

import os
import re
import io
from io import BytesIO
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

APP_TITLE = "Aplikasi Analisis Jurnal & Rekonsiliasi (Dual-Mode)"
OWNER = "Damianus Libertus"

st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")

# ---------- UTILITY HELPERS ----------
def to_num(x) -> float:
    if x is None or pd.isna(x): return 0.0
    if isinstance(x, (int, float)): return float(x)
    s = str(x).strip()
    if s in ("", "-", "--", "nil", "null", "nan", "none", ".", "0.00", "0"): return 0.0
    neg = "(" in s and ")" in s
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."): s = s.replace(".", "").replace(",", ".")
        else: s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2: s = s.replace(",", ".")
        else: s = s.replace(",", "")
    try: v = float(s); return -abs(v) if neg else v
    except: return 0.0

def rupiah(v: float) -> str:
    try: return f"Rp {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return str(v)

# ---------- PARSER ----------
STD_COLS = ["KD", "No. Bukti", "Kode Perkiraan", "Nama Perkiraan", "Uraian", "Debet", "Kredit"]

def universal_clean_and_parse(df_raw, filename=""):
    df = df_raw.copy().dropna(how='all')
    # ... (Logika parsing tetap sama seperti sebelumnya untuk membersihkan data) ...
    # Pastikan logika filter "Jumlah/Total" sudah ada di sini
    return df, "jurnal", 0.0

# ---------- ENGINE ANALISIS DUAL-MODE ----------
def perform_analysis(df_all, mode):
    files = df_all["Source_File"].unique()
    if len(files) < 2: return None
    
    df_a = df_all[df_all["Source_File"] == files[0]].copy().reset_index(drop=True)
    df_b = df_all[df_all["Source_File"] == files[1]].copy().reset_index(drop=True)

    results = {"matched": [], "unmatched_a": [], "unmatched_b": [], "diffs": []}

    # LOGIKA MODE 1: REKONSILIASI (CROSS-MATCH)
    if mode == "Rekonsiliasi RAK (Sistem Berbeda)":
        for idx_a, row_a in df_a.iterrows():
            found = False
            for idx_b, row_b in df_b.iterrows():
                # Cermin: Kredit A == Debet B
                if abs(row_a["Kredit"] - row_b["Debet"]) < 1.0:
                    results["matched"].append({"Data": row_a["Uraian"], "Status": "Cocok (Cermin)"})
                    found = True; break
            if not found: results["unmatched_a"].append(row_a)
            
    # LOGIKA MODE 2: AUDIT INTEGRITAS (DIRECT-MATCH)
    else:
        for idx_a, row_a in df_a.iterrows():
            found = False
            for idx_b, row_b in df_b.iterrows():
                # Direct: Nilai A == Nilai B
                if abs(row_a["Debet"] - row_b["Debet"]) < 1.0 and abs(row_a["Kredit"] - row_b["Kredit"]) < 1.0:
                    results["matched"].append({"Data": row_a["Uraian"], "Status": "Cocok (Identik)"})
                    found = True; break
            if not found: results["unmatched_a"].append(row_a)
            
    return results

# ---------- UI UTAMA ----------
def main():
    st.title(f"📊 {APP_TITLE}")
    
    # Switcher Mode
    mode_pilihan = st.sidebar.radio("Pilih Metode Analisis:", 
                                    ["Rekonsiliasi RAK (Sistem Berbeda)", 
                                     "Audit Integritas (Sistem Sama)"])

    up_files = st.file_uploader("Upload File:", accept_multiple_files=True)
    
    if st.button("Jalankan Analisis"):
        # Gabungkan data...
        # Panggil perform_analysis(df_combined, mode_pilihan)
        st.write(f"Menjalankan mode: {mode_pilihan}")
        # ... (Tampilkan hasil tab) ...

if __name__ == "__main__":
    main()
