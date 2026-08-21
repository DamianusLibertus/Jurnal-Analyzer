# =========================================================
# APLIKASI ANALISIS JURNAL & REKONSILIASI (VERSI STABIL)
# =========================================================

import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime
import re

# Set layout
st.set_page_config(layout="wide")

# Helper untuk angka
def to_num(x):
    try: return float(re.sub(r'[^\d\-]', '', str(x))) if x else 0.0
    except: return 0.0

def rupiah(v): return f"Rp {v:,.2f}"

# Parser untuk memproses data
def process_data(uploaded_files):
    all_dfs = []
    for f in uploaded_files:
        df = pd.read_excel(f)
        df['Source_File'] = f.name
        all_dfs.append(df)
    return pd.concat(all_dfs, ignore_index=True)

# Main App
def main():
    st.title("📊 Aplikasi Analisis Jurnal & RAK")
    
    files = st.file_uploader("Upload File Excel", accept_multiple_files=True)
    if files:
        if "df" not in st.session_state:
            st.session_state.df = process_data(files)
        
        # Panel Edit Kolom
        with st.expander("🛠️ Panel Pengaturan Kolom"):
            c1, c2, c3 = st.columns(3)
            with c1:
                new_col = st.text_input("Tambah Kolom:")
                if st.button("➕ Tambah"): 
                    st.session_state.df[new_col] = ""
                    st.rerun()
            with c2:
                del_col = st.selectbox("Pilih Kolom Hapus:", st.session_state.df.columns)
                if st.button("🗑️ Hapus"):
                    st.session_state.df.drop(columns=[del_col], inplace=True)
                    st.rerun()

        # Data Editor
        st.session_state.df = st.data_editor(st.session_state.df, use_container_width=True)

        if st.button("🚀 Kunci Data & Analisis"):
            df = st.session_state.df
            # Logika RAK
            files_list = df['Source_File'].unique()
            df_a = df[df['Source_File'] == files_list[0]]
            df_b = df[df['Source_File'] == files_list[1]]
            
            st.subheader("🔍 Hasil Analisis RAK")
            # Logika pencocokan (Cermin)
            matched = []
            for _, r1 in df_a.iterrows():
                for _, r2 in df_b.iterrows():
                    if abs(r1['Kredit'] - r2['Debet']) < 1.0:
                        matched.append(r1['Uraian'])
            
            st.success(f"Ditemukan {len(matched)} transaksi cocok.")
            st.write("Daftar Cocok:", matched)

if __name__ == "__main__":
    main()
