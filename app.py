# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi (Dynamic Rows)
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

APP_TITLE = "Aplikasi Analisis Jurnal & Rekonsiliasi"
OWNER = "Damianus Libertus"
CURRENT_YEAR = datetime.now().year

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[-1]) == 3 and len(parts[0]) <= 3): s = s.replace(".", "")
    try:
        v = float(s)
        return -abs(v) if neg else v
    except Exception: return 0.0

def rupiah(v: float) -> str:
    try: return f"Rp {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception: return str(v)

# ---------- UNIVERSAL CLEANING PARSER ----------
STD_COLS = ["KD", "No. Bukti", "Kode Perkiraan", "Nama Perkiraan", "Uraian", "Debet", "Kredit"]

def universal_clean_and_parse(df_raw: pd.DataFrame, filename: str = ""):
    if df_raw is None or df_raw.empty: return pd.DataFrame(columns=STD_COLS), "unknown", 0.0
    df = df_raw.copy().dropna(how='all')
    saldo_awal_val = 0.0
    for idx, row in df.head(15).iterrows():
        row_str = " ".join([str(val) for val in row.values if pd.notna(val)]).lower()
        if "saldo awal" in row_str:
            for val in row.values:
                num = to_num(val)
                if num != 0.0: saldo_awal_val = num
        if ("debet" in row_str or "deb" in row_str) and ("kredit" in row_str or "kred" in row_str):
            df.columns = [str(val).strip() for val in row.values]
            df = df.iloc[idx+1:].reset_index(drop=True)
            break
     
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {}
    assigned_targets = set()
    for c in df.columns:
        cl = c.strip().lower().replace("\n", " ")
        target = None
        if cl in ['kd', 'jenis', 'tipe', 'jurnal'] and 'KD' not in assigned_targets: target = 'KD'
        elif ('bukti' in cl or 'ref' in cl) and 'No. Bukti' not in assigned_targets: target = 'No. Bukti'
        elif ('kode' in cl and 'perkiraan' in cl) or cl == 'kode' and 'Kode Perkiraan' not in assigned_targets: target = 'Kode Perkiraan'
        elif (('nama' in cl and 'perkiraan' in cl) or cl == 'akun') and 'Nama Perkiraan' not in assigned_targets: target = 'Nama Perkiraan'
        elif ('uraian' in cl or 'keterangan' in cl or 'u r a i a n' in cl) and 'Uraian' not in assigned_targets: target = 'Uraian'
        elif (cl.startswith('debet') or 'debet' in cl) and 'Debet' not in assigned_targets: target = 'Debet'
        elif (cl.startswith('kredit') or 'kredit' in cl) and 'Kredit' not in assigned_targets: target = 'Kredit'
        elif 'saldo' in cl and 'Saldo' not in assigned_targets: target = 'Saldo'
        if target: col_map[c] = target; assigned_targets.add(target)
     
    df = df.rename(columns=col_map)
    for col in STD_COLS:
        if col not in df.columns: df[col] = ""
    cols_to_keep = STD_COLS + (["Saldo"] if "Saldo" in df.columns else [])
    df = df[cols_to_keep].copy()

    clean_rows = []
    for _, r in df.iterrows():
        kd_val = str(r.get("KD", "")).lower().replace(" ", "")
        bukti_val = str(r.get("No. Bukti", "")).lower().replace(" ", "")
        uraian_val = str(r.get("Uraian", "")).lower().replace(" ", "")
        if any(w in kd_val or w in bukti_val for w in ["jumlah", "tot"]) or uraian_val in ["jumlah", "total", "subtotal"]: continue
        if to_num(r.get("Debet", 0)) == 0.0 and to_num(r.get("Kredit", 0)) == 0.0 and len(uraian_val) < 3: continue
        clean_rows.append(r)
         
    df_filtered = pd.DataFrame(clean_rows).reset_index(drop=True) if clean_rows else pd.DataFrame(columns=cols_to_keep)
    df_filtered["KD"] = df_filtered["KD"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("JU")
    df_filtered["No. Bukti"] = df_filtered["No. Bukti"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("ACC-AUTO")
    df_filtered["Uraian"] = df_filtered["Uraian"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("")
    df_filtered["Debet"] = df_filtered["Debet"].apply(to_num)
    df_filtered["Kredit"] = df_filtered["Kredit"].apply(to_num)
    if "Saldo" in df_filtered.columns: df_filtered["Saldo"] = df_filtered["Saldo"].apply(to_num)
    df_filtered["Source_File"] = filename
    return df_filtered, "jurnal", saldo_awal_val

def process_uploaded_file(uploaded_file):
    fname = uploaded_file.name
    file_bytes = uploaded_file.getvalue()
    try:
        xls = pd.ExcelFile(BytesIO(file_bytes))
        frames = []
        for sh in xls.sheet_names:
            df_sh = pd.read_excel(BytesIO(file_bytes), sheet_name=sh)
            cleaned_df, _, _ = universal_clean_and_parse(df_sh, fname)
            if not cleaned_df.empty: frames.append(cleaned_df)
        if frames: return pd.concat(frames, ignore_index=True)
    except: pass
    return pd.DataFrame(columns=STD_COLS)

# ---------- ENGINE RAK & PDF ----------
def perform_rak_reconciliation(df_all):
    if "Source_File" not in df_all.columns: return None
    files = df_all["Source_File"].unique()
    if len(files) < 2: return None
    df_a = df_all[df_all["Source_File"] == files[0]].copy().reset_index(drop=True)
    df_b = df_all[df_all["Source_File"] == files[1]].copy().reset_index(drop=True)
    if "pusat" in str(files[1]).lower(): df_c, df_p = df_a, df_b
    else: df_c, df_p = df_b, df_a
     
    sal_c = df_c["Debet"].sum() - df_c["Kredit"].sum()
    sal_p = df_p["Debet"].sum() - df_p["Kredit"].sum()
     
    matched, un_c, un_p = [], [], []
    p_used = set()
    for _, row_c in df_c.iterrows():
        found = False
        for idx_p, row_p in df_p.iterrows():
            if idx_p in p_used: continue
            if abs(row_c['Kredit'] - row_p['Debet']) < 1.0 or abs(row_c['Debet'] - row_p['Kredit']) < 1.0:
                matched.append({"Uraian": row_c["Uraian"], "Nominal": rupiah(row_c["Debet"] or row_c["Kredit"]), "Status": "COCOK"})
                p_used.add(idx_p); found = True; break
        if not found: un_c.append({"Uraian": row_c["Uraian"], "Nominal": rupiah(row_c["Debet"] or row_c["Kredit"]), "Status": "BELUM DI PUSAT"})
    for idx_p, row_p in df_p.iterrows():
        if idx_p not in p_used: un_p.append({"Uraian": row_p["Uraian"], "Nominal": rupiah(row_p["Debet"] or row_p["Kredit"]), "Status": "HANYA DI PUSAT"})
    return {"sal_c": sal_c, "sal_p": sal_p, "selisih": sal_p - sal_c, "matched": pd.DataFrame(matched), "un_c": pd.DataFrame(un_c), "un_p": pd.DataFrame(un_p)}

def build_pdf_report(df, rak):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, 
        pagesize=landscape(A4), 
        topMargin=15*mm, 
        bottomMargin=15*mm, 
        leftMargin=15*mm, 
        rightMargin=15*mm
    )
    elements = []
    styles = getSampleStyleSheet()
    navy = colors.HexColor('#1E3A5F')
    
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=navy,
        alignment=0,
        spaceAfter=12
    )
    
    cell_style = ParagraphStyle(
        'Cell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#374151')
    )
    
    header_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.white
    )

    elements.append(Paragraph(f"<b>{APP_TITLE}</b>", title_style))
    elements.append(Paragraph(f"Hak Cipta © {CURRENT_YEAR} {OWNER}. Seluruh Hak Cipta Dilindungi.", ParagraphStyle('Sub', parent=styles['Normal'], fontSize=8, textColor=colors.grey)))
    elements.append(Paragraph(f"<i>Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M WIB')}</i>", ParagraphStyle('Sub2', parent=styles['Normal'], fontSize=8, textColor=colors.grey)))
    elements.append(Spacer(1, 10))

    if rak:
        summary_data = [
            [Paragraph("<b>Keterangan</b>", header_style), Paragraph("<b>Nilai</b>", header_style)],
            [Paragraph("Saldo Cabang", cell_style), Paragraph(rupiah(rak["sal_c"]), cell_style)],
            [Paragraph("Saldo Pusat", cell_style), Paragraph(rupiah(rak["sal_p"]), cell_style)],
            [Paragraph("Selisih", cell_style), Paragraph(rupiah(rak["selisih"]), cell_style)]
        ]
        t_sum = Table(summary_data, colWidths=[140*mm, 126*mm])
        t_sum.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), navy),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(t_sum)
        elements.append(Spacer(1, 12))

    if not df.empty:
        headers = [Paragraph(f"<b>{c}</b>", header_style) for c in df.columns]
        table_data = [headers]
        for _, row in df.iterrows():
            r_cells = [Paragraph(str(row[c]) if pd.notna(row[c]) else "", cell_style) for c in df.columns]
            table_data.append(r_cells)
        
        col_count = len(df.columns)
        col_width = 267.0 / col_count if col_count > 0 else 50
        col_widths = [col_width * mm] * col_count

        t_main = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_main.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), navy),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_main)

    doc.build(elements)
    return buf.getvalue()

# ---------- ANTARMUKA UTAMA ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    up_files = st.file_uploader("Upload file Excel", accept_multiple_files=True, type=["xlsx", "xls", "csv"])
    if st.button("🚀 Ekstrak & Analisis", type="primary"):
        if up_files and len(up_files) >= 1:
            all_frames = [process_uploaded_file(f) for f in up_files]
            combined = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=STD_COLS)
            if not combined.empty:
                st.session_state.df = combined
                st.session_state.rak = perform_rak_reconciliation(combined)
                st.success(f"Berhasil mengekstrak {len(combined)} baris data!")
                st.rerun()

    if "df" in st.session_state and st.session_state.df is not None and not st.session_state.df.empty:
        # Menampilkan Metrik RAK & Tab Rekonsiliasi jika data RAK tersedia
        if st.session_state.get("rak"):
            rak = st.session_state.rak
            c1, c2, c3 = st.columns(3)
            c1.metric("Saldo Cabang", rupiah(rak["sal_c"]))
            c2.metric("Saldo Pusat", rupiah(rak["sal_p"]))
            c3.metric("Selisih", rupiah(rak["selisih"]))
            t1, t2 = st.tabs(["🔴 Selisih & Unmatched", "✅ Matched"])
            with t1: st.dataframe(pd.concat([rak["un_c"], rak["un_p"]]), use_container_width=True)
            with t2: st.dataframe(rak["matched"], use_container_width=True)

        st.subheader("② Pratinjau & Edit Data Jurnal")
        
        # Panel Fleksibel: Tambah/Hapus Kolom & Sisipkan Baris di Posisi Mana Saja
        with st.expander("🛠️ Panel Pengaturan Tabel (Kolom & Posisi Baris)", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                col_add = st.text_input("Nama Kolom Baru:")
                if st.button("➕ Tambah Kolom"):
                    if col_add and col_add not in st.session_state.df.columns:
                        st.session_state.df[col_add] = ""
                        st.rerun()
            with c2:
                col_del = st.selectbox("Pilih Kolom Dihapus:", st.session_state.df.columns)
                if st.button("🗑️ Hapus Kolom"):
                    st.session_state.df = st.session_state.df.drop(columns=[col_del])
                    st.rerun()
            with c3:
                insert_idx = st.number_input("Sisipkan baris setelah indeks ke-:", min_value=0, max_value=max(0, len(st.session_state.df)-1), step=1)
                if st.button("📍 Sisipkan Baris Baru"):
                    new_row = {c: ("" if c not in ["Debet", "Kredit", "Saldo"] else 0.0) for c in st.session_state.df.columns}
                    idx_int = int(insert_idx)
                    df_top = st.session_state.df.iloc[:idx_int+1]
                    df_bottom = st.session_state.df.iloc[idx_int+1:]
                    df_new_row = pd.DataFrame([new_row])
                    st.session_state.df = pd.concat([df_top, df_new_row, df_bottom], ignore_index=True)
                    st.success(f"Baris berhasil disisipkan setelah indeks {idx_int}!")
                    st.rerun()

        st.session_state.df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True)
         
        st.divider()
        e1, e2 = st.columns(2)
        
        df_to_export = st.session_state.df.copy()
        if "Debet" in df_to_export.columns: df_to_export["Debet"] = df_to_export["Debet"].apply(to_num)
        if "Kredit" in df_to_export.columns: df_to_export["Kredit"] = df_to_export["Kredit"].apply(to_num)

        e1.download_button(
            "🖨️ Cetak PDF", 
            build_pdf_report(df_to_export, st.session_state.get("rak")), 
            f"Laporan_Analisis_RAK_{datetime.now():%Y%m%d_%H%M}.pdf", 
            "application/pdf", 
            use_container_width=True
        )
        
        buf = BytesIO()
        with pd.ExcelWriter(buf) as w: df_to_export.to_excel(w, index=False)
        e2.download_button(
            "📊 Download Excel", 
            buf.getvalue(), 
            f"Hasil_Analisis_RAK_{datetime.now():%Y%m%d_%H%M}.xlsx", 
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            use_container_width=True
        )

if __name__ == "__main__":
    main()
