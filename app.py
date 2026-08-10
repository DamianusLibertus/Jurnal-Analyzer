# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Selisih Laporan
# =========================================================

import pandas as pd
import numpy as np
import re
import streamlit as st
from io import BytesIO

# Konfigurasi halaman Streamlit
st.set_page_config(
    page_title="Aplikasi Analisis Jurnal & Selisih Laporan",
    page_icon="📊",
    layout="wide"
)

def robust_to_num(x) -> float:
    """
    Fungsi pembersih angka handal agar nilai Kredit/Debet terbaca sempurna 
    tanpa mengubah struktur atau tampilan aplikasi.
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

# --- TAMPILAN UTAMA APLIKASI ---
st.title("📊 Aplikasi Analisis Jurnal & Selisih Laporan")
st.markdown("Pemilik: **Damianus Libertus** | Sumber Laporan Jurnal Transaksi")

uploaded_file = st.file_uploader("Unggah File Excel Jurnal Transaksi", type=["xlsx", "xls"])

if uploaded_file is not None:
    try:
        xls = pd.ExcelFile(uploaded_file)
        sheet_name = xls.sheet_names[0]
        df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=0)
        
        df_cleaned = clean_and_normalize_df(df_raw)
        
        total_debet = df_cleaned["Debet"].sum()
        total_kredit = df_cleaned["Kredit"].sum()
        selisih_total = total_debet - total_kredit
        
        # Ringkasan Metrik
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Debet", f"Rp {total_debet:,.2f}")
        with col2:
            st.metric("Total Kredit", f"Rp {total_kredit:,.2f}")
        with col3:
            st.metric("Selisih Total", f"Rp {selisih_total:,.2f}", delta_color="inverse")
        with col4:
            if abs(selisih_total) < 1e-2:
                st.success("Status: BALANCE")
            else:
                st.error("Status: ADA SELISIH")
                
        # Tombol Download / Ekspor Kembali Tersedia
        st.markdown("### 📥 Unduh & Ekspor Laporan")
        col_dl1, col_dl2 = st.columns(2)
        
        # Export ke Excel Bersih
        output_excel = BytesIO()
        with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
            df_cleaned.to_excel(writer, index=False, sheet_name='Jurnal Bersih')
        output_excel.seek(0)
        
        with col_dl1:
            st.download_button(
                label="📥 Unduh Excel Jurnal Normalisasi",
                data=output_excel,
                file_name="Jurnal_Transaksi_Normal_Juli_2026.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
        grouped_df = compute_jurnal(df_cleaned)
        output_summary = BytesIO()
        with pd.ExcelWriter(output_summary, engine='xlsxwriter') as writer:
            grouped_df.to_excel(writer, index=False, sheet_name='Ringkasan Bukti')
        output_summary.seek(0)
        
        with col_dl2:
            st.download_button(
                label="📥 Unduh Ringkasan Periksa Selisih (Excel)",
                data=output_summary,
                file_name="Ringkasan_Selisih_No_Bukti.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        # Detail Tabel
        st.markdown("---")
        st.markdown("### 📋 Detail Seluruh Baris Jurnal")
        st.dataframe(df_cleaned, use_container_width=True)
        
    except Exception as e:
        st.error(f"Terjadi kesalahan saat memproses file: {e}")
else:
    st.info("Silakan unggah file Excel Anda untuk memulai.")
