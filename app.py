# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Selisih Laporan
# =========================================================

import pandas as pd
import numpy as np
import re
import streamlit as st

# Konfigurasi halaman Streamlit
st.set_page_config(
    page_title="Aplikasi Analisis Jurnal & Selisih Laporan",
    page_icon="📊",
    layout="wide"
)

def robust_to_num(x) -> float:
    """
    Fungsi pembersih angka yang handal untuk format akuntansi Indonesia 
    (pemisah ribuan titik '.', desimal koma ',', dan negatif dalam kurung '(...)').
    """
    if x is None or pd.isna(x):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    
    s = str(x).strip()
    if s in ("", "-", "--", "nil", "null", "nan", "none", "."):
        return 0.0
        
    neg = "(" in s and ")" in s
    s = re.sub(r"[^\d,.\-]", "", s)
    
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[-1]) == 3 and len(parts[0]) <= 3):
            s = s.replace(".", "")
            
    try:
        v = float(s)
        return -abs(v) if neg else v
    except Exception:
        return 0.0

def clean_and_normalize_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()
    col_map = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ["kd", "jenis", "tipe", "jurnal"]: col_map[c] = "KD"
        elif "bukti" in cl or "ref" in cl or "no bukti" in cl: col_map[c] = "No. Bukti"
        elif "kode" in cl or "acc" in cl or "rekening" in cl or "no rek" in cl or "no." == cl: col_map[c] = "Kode Perkiraan"
        elif "nama" in cl or "perkiraan" in cl or "akun" in cl or "nasabah" in cl: col_map[c] = "Nama Perkiraan"
        elif "uraian" in cl or "keterangan" in cl or "memo" in cl or "alamat" in cl or "kecamatan" in cl: col_map[c] = "Uraian"
        elif cl in ["debet", "debit", "deb", "d"]: col_map[c] = "Debet"
        elif cl in ["kredit", "kred", "k"]: col_map[c] = "Kredit"

    df = df.rename(columns=col_map)
    
    STD_COLS = ["KD", "No. Bukti", "Kode Perkiraan", "Nama Perkiraan", "Uraian", "Debet", "Kredit"]
    for col in STD_COLS:
        if col not in df.columns:
            df[col] = ""
            
    df = df[STD_COLS].copy()
    df = df[~df['KD'].astype(str).str.contains('TANGGAL', na=False)]
    df = df.dropna(subset=['Kode Perkiraan'], how='all')
    df = df.replace({'nan': '', 'NaN': '', np.nan: ''})
    
    df["KD"] = df["KD"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("JU")
    df["No. Bukti"] = df["No. Bukti"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("UNASSIGNED")
    df["Uraian"] = df["Uraian"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("")

    df["Debet"] = df["Debet"].apply(robust_to_num)
    df["Kredit"] = df["Kredit"].apply(robust_to_num)
    
    return df

def compute_jurnal(df_cleaned: pd.DataFrame):
    grouped = df_cleaned.groupby("No. Bukti").agg(
        Debet=("Debet", "sum"),
        Kredit=("Kredit", "sum"),
        Uraian=("Uraian", "first"),
        KD=("KD", "first")
    ).reset_index()

    grouped["Selisih"] = grouped["Debet"] - grouped["Kredit"]
    grouped["Status_Balance"] = abs(grouped["Selisih"]) < 1e-2
    return grouped

st.title("📊 Aplikasi Analisis Jurnal & Selisih Laporan")
st.markdown("Unggah file Excel jurnal transaksi Anda untuk melakukan verifikasi keseimbangan Debet dan Kredit secara otomatis.")

uploaded_file = st.file_uploader("Pilih File Excel Jurnal Transaksi", type=["xlsx", "xls"])

if uploaded_file is not None:
    try:
        xls = pd.ExcelFile(uploaded_file)
        sheet_name = xls.sheet_names[0]
        df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=0)
        
        df_cleaned = clean_and_normalize_df(df_raw)
        
        total_debet = df_cleaned["Debet"].sum()
        total_kredit = df_cleaned["Kredit"].sum()
        selisih_total = total_debet - total_kredit
        
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Debet", f"Rp {total_debet:,.2f}")
        with col2:
            st.metric("Total Kredit", f"Rp {total_kredit:,.2f}")
        with col3:
            st.metric("Selisih Total", f"Rp {selisih_total:,.2f}", delta_color="inverse")
            
        if abs(selisih_total) < 1e-2:
            st.success("✅ STATUS JURNAL: 100% SEIMBANG (BALANCE)")
        else:
            st.error("⚠️ STATUS JURNAL: PERHATIAN (ADA SELISIH)")
            
        st.markdown("### 🔍 Ringkasan Periksa Saldo Berbasis No. Bukti")
        grouped_df = compute_jurnal(df_cleaned)
        unbalanced = grouped_df[~grouped_df["Status_Balance"]]
        
        if len(unbalanced) == 0:
            st.info("Semua nomor bukti tercatat balance dengan sempurna.")
        else:
            st.warning(f"Ditemukan {len(unbalanced)} nomor bukti yang memiliki selisih.")
            st.dataframe(unbalanced)
            
        st.markdown("### 📋 Detail Seluruh Baris Jurnal")
        st.dataframe(df_cleaned, use_container_width=True)
        
    except Exception as e:
        st.error(f"Terjadi kesalahan saat memproses file: {e}")
else:
    st.info("Silakan unggah file Excel (.xlsx) untuk memulai analisis.")
