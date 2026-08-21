# =========================================================
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi (All-in-One Stable)
# =========================================================
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
import numpy as np

# ... [Fungsi to_num, rupiah, universal_clean_and_parse, build_pdf_report tetap sama seperti sebelumnya] ...
# (Saya asumsikan Anda sudah memiliki fungsi-fungsi ini di file app.py Anda)

def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    st.divider()

    # 1. UPLOAD
    up_files = st.file_uploader("Upload 2 File Laporan Excel:", type=["xlsx", "xls"], accept_multiple_files=True)
    
    if st.button("🚀 Jalankan Analisis"):
        all_frames = []
        for f in up_files:
            parsed_df, _, _ = process_uploaded_file(f)
            if not parsed_df.empty: all_frames.append(parsed_df)
        
        if len(all_frames) >= 2:
            combined_df = pd.concat(all_frames, ignore_index=True)
            st.session_state.df_raw = combined_df
            st.session_state.rak_res = perform_rak_reconciliation(combined_df)
            st.success("Analisis Selesai!")
            st.rerun()

    # 2. TAMPILKAN HASIL JIKA ADA
    if "rak_res" in st.session_state:
        rak = st.session_state.rak_res
        
        # --- METRIK SALDO (DIPENGGIL KEMBALI) ---
        c1, c2, c3 = st.columns(3)
        c1.metric("Saldo Akhir Cabang", rupiah(rak["sal_cabang"]))
        c2.metric("Saldo Akhir Pusat", rupiah(rak["sal_pusat"]))
        c3.metric("Selisih RAK", rupiah(rak["selisih_akhir"]))
        st.divider()

        # --- TABS (YANG BISA DIKLIK) ---
        tab1, tab2, tab3 = st.tabs(["✅ Transaksi Cocok", f"📌 Belum di {rak['name_pusat']}", f"📌 Belum di {rak['name_cabang']}"])
        
        with tab1: st.dataframe(rak["matched"], use_container_width=True)
        with tab2: st.dataframe(rak["unmatched_cabang"], use_container_width=True)
        with tab3: st.dataframe(rak["unmatched_pusat"], use_container_width=True)
        
        # --- DOWNLOAD PDF/EXCEL ---
        st.divider()
        st.subheader("⑤ Cetak & Download")
        # [Tambahkan kembali tombol download PDF/Excel di sini]

if __name__ == "__main__":
    main()
