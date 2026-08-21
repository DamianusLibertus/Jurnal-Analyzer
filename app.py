# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi (Dual-Mode)
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

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- UTILITY HELPERS ----------
def to_num(x) -> float:
    if x is None or pd.isna(x):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s in ("", "-", "--", "nil", "null", "nan", "none", ".", "0.00", "0"):
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

def rupiah(v: float) -> str:
    try:
        return f"Rp {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)

# ---------- UNIVERSAL CLEANING PARSER ----------
STD_COLS = ["KD", "No. Bukti", "Kode Perkiraan", "Nama Perkiraan", "Uraian", "Debet", "Kredit"]

def universal_clean_and_parse(df_raw: pd.DataFrame, filename: str = ""):
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=STD_COLS), "unknown", 0.0

    df = df_raw.copy()
    df = df.dropna(how='all')
    
    saldo_awal_val = 0.0
    for idx, row in df.head(10).iterrows():
        row_str = " ".join([str(val) for val in row.values if pd.notna(val)]).lower()
        if "saldo awal" in row_str:
            for val in row.values:
                num = to_num(val)
                if num != 0.0:
                    saldo_awal_val = num
        if ("debet" in row_str or "deb" in row_str) and ("kredit" in row_str or "kred" in row_str):
            df.columns = [str(val).strip() for val in row.values]
            df = df.iloc[idx+1:].reset_index(drop=True)
            break

    df.columns = [str(c).strip() for c in df.columns]
    cols_lower = [c.lower() for c in df.columns]

    has_debet = any("deb" in c for c in cols_lower)
    has_kredit = any("kred" in c or "credit" in c or "keluar" in c for c in cols_lower)
    has_saldo = any("saldo" in c for c in cols_lower)

    if has_debet and has_kredit and has_saldo:
        detected_mode = "ledger"
    elif has_debet and has_kredit:
        detected_mode = "jurnal"
    else:
        detected_mode = "nominatif"

    col_map = {}
    assigned_targets = set()
    
    for c in df.columns:
        cl = c.strip().lower().replace("\n", " ")
        target = None
        
        if cl in ['kd', 'jenis', 'tipe', 'jurnal'] and 'KD' not in assigned_targets:
            target = 'KD'
        elif ('bukti' in cl or 'ref' in cl) and 'No. Bukti' not in assigned_targets:
            target = 'No. Bukti'
        elif ('kode' in cl and 'perkiraan' in cl) or cl == 'kode' and 'Kode Perkiraan' not in assigned_targets:
            target = 'Kode Perkiraan'
        elif (('nama' in cl and 'perkiraan' in cl) or cl == 'akun') and 'Nama Perkiraan' not in assigned_targets:
            target = 'Nama Perkiraan'
        elif ('uraian' in cl or 'keterangan' in cl or 'u r a i a n' in cl) and 'Uraian' not in assigned_targets:
            target = 'Uraian'
        elif (cl.startswith('debet') or cl.startswith('deb') or 'debet' in cl) and 'Debet' not in assigned_targets:
            target = 'Debet'
        elif (cl.startswith('kredit') or cl.startswith('kred') or 'kredit' in cl) and 'Kredit' not in assigned_targets:
            target = 'Kredit'
        elif 'saldo' in cl and 'Saldo' not in assigned_targets:
            target = 'Saldo'
            
        if target:
            col_map[c] = target
            assigned_targets.add(target)

    df = df.rename(columns=col_map)

    for col in STD_COLS:
        if col not in df.columns:
            df[col] = ""

    cols_to_keep = STD_COLS + (["Saldo"] if "Saldo" in df.columns else [])
    df = df[cols_to_keep].copy()

    clean_rows = []
    for _, r in df.iterrows():
        kd_val = str(r.get("KD", "")).lower().replace(" ", "")
        bukti_val = str(r.get("No. Bukti", "")).lower().replace(" ", "")
        uraian_val = str(r.get("Uraian", "")).lower().replace(" ", "")
        
        is_summary_row = False
        if any(w in kd_val or w in bukti_val for w in ["jumlah", "tot"]):
            is_summary_row = True
        elif uraian_val in ["jumlah", "total", "subtotal"]:
            is_summary_row = True
        
        if is_summary_row:
            continue
            
        full_row_text = f"{kd_val} {bukti_val} {uraian_val}"
        d_val = to_num(r.get("Debet", 0))
        k_val = to_num(r.get("Kredit", 0))
        
        if d_val == 0.0 and k_val == 0.0 and len(full_row_text.strip()) < 3:
            continue
            
        clean_rows.append(r)

    df_filtered = pd.DataFrame(clean_rows).reset_index(drop=True) if clean_rows else pd.DataFrame(columns=cols_to_keep)

    df_filtered["KD"] = df_filtered["KD"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("JU")
    df_filtered["No. Bukti"] = df_filtered["No. Bukti"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("ACC-AUTO")
    df_filtered["Uraian"] = df_filtered["Uraian"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("")

    df_filtered["Debet"] = df_filtered["Debet"].apply(to_num)
    df_filtered["Kredit"] = df_filtered["Kredit"].apply(to_num)
    if "Saldo" in df_filtered.columns:
        df_filtered["Saldo"] = df_filtered["Saldo"].apply(to_num)

    df_filtered["Source_File"] = filename
    df_filtered.attrs["saldo_awal"] = saldo_awal_val
    return df_filtered, detected_mode, saldo_awal_val

def process_uploaded_file(uploaded_file):
    fname = uploaded_file.name
    file_bytes = uploaded_file.getvalue()
    low_fname = fname.lower()

    if low_fname.endswith((".xlsx", ".xls")):
        try:
            xls = pd.ExcelFile(BytesIO(file_bytes))
            frames = []
            detected_modes = []
            s_awal = 0.0
            for sh in xls.sheet_names:
                df_sh = pd.read_excel(BytesIO(file_bytes), sheet_name=sh)
                cleaned_df, mode, sa = universal_clean_and_parse(df_sh, fname)
                if not cleaned_df.empty:
                    frames.append(cleaned_df)
                    detected_modes.append(mode)
                    if sa != 0.0: s_awal = sa
            if frames:
                res_df = pd.concat(frames, ignore_index=True)
                res_df.attrs["saldo_awal"] = s_awal
                return res_df, (detected_modes[0] if detected_modes else "jurnal")
        except Exception as e:
            st.error(f"Gagal membaca Excel {fname}: {e}")
    return pd.DataFrame(columns=STD_COLS), "unknown"

# ---------- ENGINE REKONSILIASI & AUDIT ----------
def perform_dual_mode_analysis(df_all, analysis_mode):
    files = df_all["Source_File"].unique()
    if len(files) < 2:
        return None

    df_a = df_all[df_all["Source_File"] == files[0]].copy().reset_index(drop=True)
    df_b = df_all[df_all["Source_File"] == files[1]].copy().reset_index(drop=True)

    matched_results = []
    unmatched_a = []
    unmatched_b = []

    used_b = set()

    # MODE 1: REKONSILIASI RAK (Sistem Berbeda - Logika Cerminan)
    if analysis_mode == "Rekonsiliasi RAK (Sistem Berbeda)":
        for idx_a, row_a in df_a.iterrows():
            val_a_kred = row_a["Kredit"]
            val_a_deb = row_a["Debet"]
            found = False

            for idx_b, row_b in df_b.iterrows():
                if idx_b in used_b:
                    continue
                # Cermin: Kredit A == Debet B atau Debet A == Kredit B
                if (val_a_kred > 0 and abs(val_a_kred - row_b["Debet"]) < 1.0) or \
                   (val_a_deb > 0 and abs(val_a_deb - row_b["Kredit"]) < 1.0):
                    matched_results.append({
                        "Uraian Transaksi": row_a["Uraian"],
                        "Nominal": rupiah(val_a_kred if val_a_kred > 0 else val_a_deb),
                        "Status": "COCOK (Cermin) ✅"
                    })
                    used_b.add(idx_b)
                    found = True
                    break
            if not found:
                unmatched_a.append(row_a)

        for idx_b, row_b in df_b.iterrows():
            if idx_b not in used_b:
                unmatched_b.append(row_b)

    # MODE 2: AUDIT INTEGRITAS (Sistem Sama - Logika Direct Match)
    else:
        for idx_a, row_a in df_a.iterrows():
            val_a_deb = row_a["Debet"]
            val_a_kred = row_a["Kredit"]
            found = False

            for idx_b, row_b in df_b.iterrows():
                if idx_b in used_b:
                    continue
                # Direct Match: Debet A == Debet B dan Kredit A == Kredit B
                if abs(val_a_deb - row_b["Debet"]) < 1.0 and abs(val_a_kred - row_b["Kredit"]) < 1.0:
                    matched_results.append({
                        "Uraian Transaksi": row_a["Uraian"],
                        "Nominal": rupiah(val_a_deb if val_a_deb > 0 else val_a_kred),
                        "Status": "COCOK (Identik) ✅"
                    })
                    used_b.add(idx_b)
                    found = True
                    break
            if not found:
                unmatched_a.append(row_a)

        for idx_b, row_b in df_b.iterrows():
            if idx_b not in used_b:
                unmatched_b.append(row_b)

    return {
        "file_a": files[0],
        "file_b": files[1],
        "matched": pd.DataFrame(matched_results),
        "unmatched_a": pd.DataFrame(unmatched_a),
        "unmatched_b": pd.DataFrame(unmatched_b)
    }

# ---------- ANTARMUKA UTAMA ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    st.caption(f"Dikembangkan oleh {OWNER}")
    st.divider()

    # Sidebar Pilihan Mode
    st.sidebar.header("⚙️ Pengaturan Analisis")
    selected_mode = st.sidebar.radio(
        "Pilih Metode Analisis:",
        ["Rekonsiliasi RAK (Sistem Berbeda)", "Audit Integritas (Sistem Sama)"]
    )

    st.subheader("① Unggah Dua File Laporan")
    up_files = st.file_uploader(
        "Pilih 2 file laporan Excel untuk dianalisis bersamaan",
        type=["xlsx", "xls"],
        accept_multiple_files=True
    )

    if st.button("🚀 Jalankan Analisis Dual-Mode", type="primary", disabled=not up_files or len(up_files) < 2):
        all_frames = []
        with st.spinner("Mengekstrak dan mencocokkan data..."):
            for f in up_files:
                parsed_df, _, _ = process_uploaded_file(f)
                if not parsed_df.empty:
                    all_frames.append(parsed_df)

            if len(all_frames) >= 2:
                combined_df = pd.concat(all_frames, ignore_index=True)
                st.session_state.df_raw = combined_df
                st.session_state.analysis_res = perform_dual_mode_analysis(combined_df, selected_mode)
                st.session_state.selected_mode = selected_mode
                st.success("Analisis berhasil dijalankan!")
            else:
                st.error("Harap unggah minimal 2 file laporan yang valid.")

    if "analysis_res" in st.session_state and st.session_state.analysis_res is not None:
        res = st.session_state.analysis_res
        st.divider()
        st.subheader(f"🔍 Hasil Analisis: {st.session_state.selected_mode}")

        tab1, tab2, tab3 = st.tabs(["✅ Transaksi Cocok (Matched)", f"📌 Belum Tercatat di {res['file_b']}", f"📌 Belum Tercatat di {res['file_a']}"])

        with tab1:
            if not res["matched"].empty:
                st.dataframe(res["matched"], use_container_width=True)
            else:
                st.info("Tidak ada transaksi yang cocok.")

        with tab2:
            if not res["unmatched_a"].empty:
                st.dataframe(res["unmatched_a"], use_container_width=True)
            else:
                st.success("Semua transaksi di file pertama sudah tercatat.")

        with tab3:
            if not res["unmatched_b"].empty:
                st.dataframe(res["unmatched_b"], use_container_width=True)
            else:
                st.success("Semua transaksi di file kedua sudah tercatat.")

if __name__ == "__main__":
    main()
