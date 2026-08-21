import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime
import re
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

st.set_page_config(layout="wide")

# --- UTILS ---
def to_num(x):
    try: return float(re.sub(r'[^\d\-]', '', str(x))) if x else 0.0
    except: return 0.0
def rupiah(v): return f"Rp {v:,.2f}"

# --- ENGINE RAK STABIL ---
def perform_rak(df):
    files = df['Source_File'].unique()
    df_cabang = df[df['Source_File'] == files[0]]
    df_pusat = df[df['Source_File'] == files[1]]
    
    # Deteksi arah pusat/cabang
    if "pusat" in files[1].lower(): 
        df_a, df_b = df_cabang, df_pusat
    else: 
        df_a, df_b = df_pusat, df_cabang

    matched, unmatched_a = [], []
    for _, r1 in df_a.iterrows():
        found = False
        for _, r2 in df_b.iterrows():
            if abs(r1['Kredit'] - r2['Debet']) < 1.0 or abs(r1['Debet'] - r2['Kredit']) < 1.0:
                matched.append(r1)
                found = True
                break
        if not found: unmatched_a.append(r1)
    
    return pd.DataFrame(matched), pd.DataFrame(unmatched_a), files[0], files[1]

# --- MAIN ---
def main():
    st.title("📊 Aplikasi Analisis Jurnal & Rekonsiliasi (Versi Lengkap)")
    
    files = st.file_uploader("Upload 2 File Excel:", accept_multiple_files=True, type=["xlsx"])
    if files and len(files) >= 2:
        if "df" not in st.session_state:
            all_dfs = [pd.read_excel(f).assign(Source_File=f.name) for f in files]
            st.session_state.df = pd.concat(all_dfs, ignore_index=True)

        # Panel Edit
        with st.expander("🛠️ Panel Pengaturan Kolom"):
            c1, c2 = st.columns(2)
            with c1:
                col_add = st.text_input("Tambah Nama Kolom:")
                if st.button("➕ Tambah"): st.session_state.df[col_add] = ""; st.rerun()
            with c2:
                col_del = st.selectbox("Hapus Kolom:", st.session_state.df.columns)
                if st.button("🗑️ Hapus"): st.session_state.df.drop(columns=[col_del], inplace=True); st.rerun()

        st.session_state.df = st.data_editor(st.session_state.df, use_container_width=True)

        if st.button("🚀 Kunci Data & Analisis"):
            matched, un_a, f1, f2 = perform_rak(st.session_state.df)
            st.session_state.results = {"m": matched, "u": un_a, "f1": f1, "f2": f2}
            st.rerun()

    if "results" in st.session_state:
        res = st.session_state.results
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Transaksi Cocok", len(res['m']))
        c2.metric(f"Unmatched {res['f1']}", len(res['u']))
        
        tab1, tab2 = st.tabs(["✅ Matched", "📌 Unmatched"])
        with tab1: st.dataframe(res['m'], use_container_width=True)
        with tab2: st.dataframe(res['u'], use_container_width=True)

        # Download PDF/Excel
        buf = BytesIO()
        with pd.ExcelWriter(buf) as writer:
            st.session_state.df.to_excel(writer, index=False)
        st.download_button("📊 Download Excel", buf.getvalue(), "Laporan_Final.xlsx", "application/vnd.ms-excel")

if __name__ == "__main__":
    main()
