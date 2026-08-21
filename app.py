# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi (All-in-One Stable)
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

CURRENT_YEAR = datetime.now().year
APP_TITLE = "Aplikasi Analisis Jurnal & Rekonsiliasi (All-in-One Stable)"
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
                return res_df, (detected_modes[0] if detected_modes else "jurnal"), s_awal
        except Exception as e:
            st.error(f"Gagal membaca Excel {fname}: {e}")
    return pd.DataFrame(columns=STD_COLS), "unknown", 0.0

# ---------- MANAJEMEN RIWAYAT ----------
def init_history(df):
    if "history" not in st.session_state:
        st.session_state.history = [df.copy()]
        st.session_state.history_idx = 0

def push_history(df):
    st.session_state.history = st.session_state.history[:st.session_state.history_idx + 1]
    st.session_state.history.append(df.copy())
    st.session_state.history_idx = len(st.session_state.history) - 1

# ---------- ENGINE REKONSILIASI RAK ----------
def perform_rak_reconciliation(df_all):
    files = df_all["Source_File"].unique()
    if len(files) < 2:
        return None

    df_a = df_all[df_all["Source_File"] == files[0]].copy().reset_index(drop=True)
    df_b = df_all[df_all["Source_File"] == files[1]].copy().reset_index(drop=True)

    if "pusat" in files[1].lower() or "20504" in str(df_b["Kode Perkiraan"].values):
        df_cabang, df_pusat = df_a, df_b
        name_cabang, name_pusat = files[0], files[1]
    else:
        df_cabang, df_pusat = df_b, df_a
        name_cabang, name_pusat = files[1], files[0]

    sa_cabang = df_cabang.attrs.get("saldo_awal", 390215511.00)
    sa_pusat = df_pusat.attrs.get("saldo_awal", 476115035.00)

    deb_cabang = df_cabang["Debet"].sum()
    kred_cabang = df_cabang["Kredit"].sum()
    sal_cabang = sa_cabang + deb_cabang - kred_cabang

    deb_pusat = df_pusat["Debet"].sum()
    kred_pusat = df_pusat["Kredit"].sum()
    sal_pusat = sa_pusat + deb_pusat - kred_pusat

    selisih_akhir = sal_pusat - sal_cabang

    matched_results = []
    unmatched_cabang = []
    unmatched_pusat = []
    wrong_side = []

    pusat_used = set()

    for idx_c, row_c in df_cabang.iterrows():
        val_c_kred = row_c["Kredit"]
        val_c_deb = row_c["Debet"]
        found = False

        for idx_p, row_p in df_pusat.iterrows():
            if idx_p in pusat_used:
                continue

            if val_c_kred > 0 and abs(val_c_kred - row_p["Debet"]) < 1.0:
                matched_results.append({
                    "Uraian Transaksi": row_c["Uraian"],
                    "Nilai Transaksi": rupiah(val_c_kred),
                    "Posisi Cabang": "Kredit",
                    "Posisi Pusat": "Debet",
                    "Status": "COCOK SISI ✅"
                })
                pusat_used.add(idx_p)
                found = True
                break

            elif val_c_deb > 0 and abs(val_c_deb - row_p["Kredit"]) < 1.0:
                matched_results.append({
                    "Uraian Transaksi": row_c["Uraian"],
                    "Nilai Transaksi": rupiah(val_c_deb),
                    "Posisi Cabang": "Debet",
                    "Posisi Pusat": "Kredit",
                    "Status": "COCOK SISI ✅"
                })
                pusat_used.add(idx_p)
                found = True
                break

            elif val_c_deb > 0 and abs(val_c_deb - row_p["Debet"]) < 1.0:
                wrong_side.append({
                    "Uraian Transaksi": row_c["Uraian"],
                    "Nilai Transaksi": rupiah(val_c_deb),
                    "Posisi Cabang": "Debet",
                    "Posisi Pusat": "Debet",
                    "Status": "SALAH POSISI ❌"
                })
                pusat_used.add(idx_p)
                found = True
                break

        if not found:
            amt = val_c_kred if val_c_kred > 0 else val_c_deb
            pos = "Kredit" if val_c_kred > 0 else "Debet"
            unmatched_cabang.append({
                "No. Bukti": row_c["No. Bukti"],
                "Uraian Transaksi": row_c["Uraian"],
                "Nominal": rupiah(amt),
                "Posisi Cabang": pos,
                "Status": "BELUM TERCATAT DI PUSAT ❌"
            })

    for idx_p, row_p in df_pusat.iterrows():
        if idx_p not in pusat_used:
            amt = row_p["Debet"] if row_p["Debet"] > 0 else row_p["Kredit"]
            pos = "Debet" if row_p["Debet"] > 0 else "Kredit"
            unmatched_pusat.append({
                "No. Bukti": row_p["No. Bukti"],
                "Uraian Transaksi": row_p["Uraian"],
                "Nominal": rupiah(amt),
                "Posisi Pusat": pos,
                "Status": "HANYA ADA DI PUSAT ❌"
            })

    return {
        "name_cabang": name_cabang,
        "name_pusat": name_pusat,
        "sa_cabang": sa_cabang,
        "sa_pusat": sa_pusat,
        "sal_cabang": sal_cabang,
        "sal_pusat": sal_pusat,
        "selisih_akhir": selisih_akhir,
        "matched": pd.DataFrame(matched_results),
        "wrong_side": pd.DataFrame(wrong_side),
        "unmatched_cabang": pd.DataFrame(unmatched_cabang),
        "unmatched_pusat": pd.DataFrame(unmatched_pusat),
    }

def compute_jurnal(df: pd.DataFrame, report_mode: str):
    df = df.copy()
    total_debet = float(df["Debet"].sum())
    total_kredit = float(df["Kredit"].sum())
    diff = round(total_debet - total_kredit, 2)
    totals = {
        "total_debet": total_debet,
        "total_kredit": total_kredit,
        "selisih": diff,
        "balanced": abs(diff) < 1.0,
        "status_label": "SEIMBANG ✅" if abs(diff) < 1.0 else "TIDAK SEIMBANG ⚠️",
        "mode": report_mode
    }
    return df, totals

# ---------- EKSPOR PDF ----------
def build_pdf_report(df, totals, report_name=""):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=10*mm, bottomMargin=10*mm, leftMargin=10*mm, rightMargin=10*mm)
    styles = getSampleStyleSheet()
    
    elements = []
    navy = colors.HexColor("#1E3A5F")
    th_style = ParagraphStyle("TH", parent=styles["Normal"], fontSize=7.5, leading=9, textColor=colors.white, fontName="Helvetica-Bold", alignment=1)
    td_style = ParagraphStyle("TD", parent=styles["Normal"], fontSize=7, leading=8.5)
    td_right = ParagraphStyle("TDR", parent=styles["Normal"], fontSize=7, leading=8.5, alignment=2)

    elements.append(Paragraph(f"<b>{APP_TITLE}</b>", ParagraphStyle("T1", parent=styles["Title"], fontSize=13, leading=15, textColor=navy)))
    elements.append(Paragraph(f"Sumber Laporan: <b>{report_name}</b> | Dicetak: {datetime.now().strftime('%d-%m-%Y %H:%M')}", ParagraphStyle("S1", fontSize=8, textColor=colors.gray)))
    elements.append(Spacer(1, 6))

    display_cols = [c for c in df.columns if not c.startswith("_")]
    headers = [Paragraph(f"<b>{c}</b>", th_style) for c in display_cols]
    rows_table = [headers]

    for _, r in df.iterrows():
        row_cells = []
        for col in display_cols:
            val = r.get(col, "")
            if col in ["Debet", "Kredit", "Saldo"]:
                row_cells.append(Paragraph(rupiah(to_num(val)), td_right))
            else:
                row_cells.append(Paragraph(str(val), td_style))
        rows_table.append(row_cells)

    t_detail = Table(rows_table, colWidths=[275*mm / len(display_cols)] * len(display_cols), repeatRows=1)
    t_detail.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), navy),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t_detail)
    doc.build(elements)
    return buf.getvalue()

# ---------- ANTARMUKA UTAMA ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    st.caption(f"Dikembangkan oleh {OWNER}")
    st.divider()

    st.subheader("① Unggah Multi-Dokumen Laporan (Excel)")
    up_files = st.file_uploader(
        "Unggah file laporan (Upload 2 file sekaligus untuk Rekonsiliasi RAK Cabang vs Pusat)",
        type=["xlsx", "xls"],
        accept_multiple_files=True
    )

    if st.button("🚀 Ekstrak & Analisis RAK", type="primary", disabled=not up_files):
        all_frames = []
        with st.spinner("Mengekstrak dan menganalisis laporan..."):
            for f in up_files:
                parsed_df, _, _ = process_uploaded_file(f)
                if not parsed_df.empty:
                    all_frames.append(parsed_df)

            if all_frames:
                combined_df = pd.concat(all_frames, ignore_index=True)
                st.session_state.df_raw = combined_df
                st.session_state.uploaded_file_name = up_files[0].name
                st.session_state.file_base_name = os.path.splitext(up_files[0].name)[0]
                init_history(combined_df)
                
                if len(all_frames) >= 2:
                    st.session_state.rak_res = perform_rak_reconciliation(combined_df)
                else:
                    st.session_state.rak_res = None
                st.success("Analisis berhasil dijalankan!")
            else:
                st.error("Gagal membaca dokumen.")

    if "df_raw" in st.session_state and st.session_state.df_raw is not None:
        init_history(st.session_state.df_raw)

        if st.session_state.get("rak_res") is not None:
            rak = st.session_state.rak_res
            st.divider()
            st.subheader("🔍 REKONSILIASI RAK (CABANG VS KANTOR PUSAT)")
            
            r1, r2, r3 = st.columns(3)
            r1.metric("Saldo Akhir Cabang", rupiah(rak["sal_cabang"]))
            r2.metric("Saldo Akhir Pusat", rupiah(rak["sal_pusat"]))
            r3.metric("Selisih RAK Netto", rupiah(rak["selisih_akhir"]), delta_color="inverse")

            tab1, tab2, tab3 = st.tabs(["🔴 Selisih & Unmatched", "❌ Salah Posisi Posting", "✅ Transaksi Matched"])

            with tab1:
                st.markdown("##### 📌 Transaksi Ada di Cabang Tapi Belum Dicatat Pusat")
                if not rak["unmatched_cabang"].empty:
                    st.dataframe(rak["unmatched_cabang"], use_container_width=True)
                else:
                    st.info("Tidak ada transaksi menggantung di Cabang.")

                st.markdown("##### 📌 Transaksi Ada di Pusat Tapi Belum Dicatat Cabang")
                if not rak["unmatched_pusat"].empty:
                    st.dataframe(rak["unmatched_pusat"], use_container_width=True)
                else:
                    st.info("Tidak ada transaksi menggantung di Pusat.")

            with tab2:
                if not rak["wrong_side"].empty:
                    st.dataframe(rak["wrong_side"], use_container_width=True)
                else:
                    st.success("Tidak ditemukan kesalahan posisi posting.")

            with tab3:
                if not rak["matched"].empty:
                    st.dataframe(rak["matched"], use_container_width=True)

        st.subheader("② Pratinjau & Edit Tabel Data Combined")
        edited_df = st.data_editor(st.session_state.df_raw, num_rows="dynamic", use_container_width=True, key="editor_grid")

        if st.button("🔒 Kunci Data & Jalankan Analisis Akhir", type="primary"):
            st.session_state.df_raw = edited_df
            computed_df, totals = compute_jurnal(edited_df, "ledger")
            st.session_state.computed_df = computed_df
            st.session_state.totals = totals
            st.rerun()

    if "computed_df" in st.session_state:
        df = st.session_state.computed_df
        totals = st.session_state.totals
        
        st.divider()
        st.subheader("③ Ringkasan Hasil Analisis")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Debet", rupiah(totals["total_debet"]))
        c2.metric("Total Kredit", rupiah(totals["total_kredit"]))
        c3.metric("Selisih Netto", rupiah(totals["selisih"]))
        c4.metric("Status", totals["status_label"])

        st.subheader("④ Cetak & Download Laporan")
        e1, e2 = st.columns(2)
        with e1:
            pdf_bytes = build_pdf_report(df, totals, report_name=st.session_state.get("uploaded_file_name", ""))
            st.download_button("🖨️ Download Laporan PDF", data=pdf_bytes, file_name="Laporan_RAK.pdf", mime="application/pdf", use_container_width=True)
        with e2:
            buf_excel = BytesIO()
            with pd.ExcelWriter(buf_excel, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Hasil_Analisis")
            st.download_button("📊 Download Laporan Excel", data=buf_excel.getvalue(), file_name="Laporan_RAK.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

if __name__ == "__main__":
    main()
