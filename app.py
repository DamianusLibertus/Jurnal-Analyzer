# ==========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi
# ==========================================================

import io
import os
import re
from datetime import datetime
from io import BytesIO

import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

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
        return (
            f"Rp {v:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
    except Exception:
        return str(v)

# ---------- UNIVERSAL CLEANING PARSER ----------
STD_COLS = [
    "Tanggal",
    "KD",
    "No. Bukti",
    "Kode Perkiraan",
    "Nama Perkiraan",
    "Uraian",
    "Debet",
    "Kredit",
]

def process_uploaded_file(uploaded_file):
    fname = uploaded_file.name
    file_bytes = uploaded_file.getvalue()
    try:
        df_raw = pd.read_excel(BytesIO(file_bytes))
        if "simpanan" in fname.lower() or "simp" in fname.lower() or "harian" in fname.lower():
            sub = df_raw.iloc[8:].copy()
            sub.columns = ['Tanggal', 'KD', 'No. Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo', 'N1', 'N2', 'N3'][:len(sub.columns)]
            sub = sub.dropna(subset=['Tanggal'])
            sub['Debet'] = sub['Debet'].apply(to_num)
            sub['Kredit'] = sub['Kredit'].apply(to_num)
            sub['Source_File'] = fname
            return sub[['Tanggal', 'KD', 'No. Bukti', 'Uraian', 'Debet', 'Kredit', 'Source_File']]
        else:
            gl = df_raw.iloc[6:].copy()
            if len(gl.columns) >= 8:
                gl.columns = ['No', 'No Rekening', 'Nama Nasabah', 'Tanggal', 'No. Bukti', 'KD', 'Setoran', 'Penarikan'][:len(gl.columns)]
                gl = gl.dropna(subset=['Tanggal'])
                gl['Debet'] = gl['Setoran'].apply(to_num) if 'Setoran' in gl.columns else 0.0
                gl['Kredit'] = gl['Penarikan'].apply(to_num) if 'Penarikan' in gl.columns else 0.0
                gl['Source_File'] = fname
                gl['Uraian'] = gl['Nama Nasabah'].astype(str) + " (" + gl['No Rekening'].astype(str) + ")"
                return gl[['Tanggal', 'KD', 'No. Bukti', 'Uraian', 'Debet', 'Kredit', 'Source_File']]
        return df_raw
    except Exception as e:
        st.error(f"Gagal membaca file {fname}: {e}")
        return pd.DataFrame(columns=STD_COLS)

# ---------- ENGINE VALIDASI PER NOMOR BUKTI (KANTOR TUNGGAL) ----------
def perform_per_bukti_validation(df):
    if df.empty or "No. Bukti" not in df.columns:
        return pd.DataFrame()
    
    df_val = df.copy()
    df_val["Debet_num"] = df_val["Debet"].apply(to_num) if "Debet" in df_val.columns else 0.0
    df_val["Kredit_num"] = df_val["Kredit"].apply(to_num) if "Kredit" in df_val.columns else 0.0
    df_val["No. Bukti Clean"] = df_val["No. Bukti"].astype(str).str.strip()
    
    # Kelompokkan berdasarkan No. Bukti
    grouped = df_val[df_val["No. Bukti Clean"] != ""].groupby("No. Bukti Clean").agg({
        "Debet_num": "sum",
        "Kredit_num": "sum",
        "Uraian": lambda x: " | ".join(x.astype(str).unique()[:2])
    }).reset_index()
    
    grouped["Selisih"] = grouped["Debet_num"] - grouped["Kredit_num"]
    # Filter yang tidak seimbang (selisih > 1 rupiah)
    unbalanced = grouped[abs(grouped["Selisih"]) >= 1.0].copy()
    return unbalanced

# ---------- ENGINE RAK & PDF (REVISED) ----------
def perform_rak_reconciliation(df_all):
    if "Source_File" not in df_all.columns:
        return None
    files = df_all["Source_File"].unique()
    if len(files) < 2:
        return None
    
    files_str = " ".join([str(f).lower() for f in files])
    if not ("770" in files_str or "pusat" in files_str):
        return None

    df_a = df_all[df_all["Source_File"] == files[0]].copy().reset_index(drop=True)
    df_b = df_all[df_all["Source_File"] == files[1]].copy().reset_index(drop=True)

    f0_lower = str(files[0]).lower()
    if "770" in f0_lower or "pusat" in f0_lower:
        df_p, df_c = df_a, df_b
    else:
        df_c, df_p = df_a, df_b

    sal_c = df_c["Saldo"].iloc[-1] if "Saldo" in df_c.columns and (df_c["Saldo"] != 0).any() else (df_c["Debet"].sum() - df_c["Kredit"].sum())
    sal_p = df_p["Saldo"].iloc[-1] if "Saldo" in df_p.columns and (df_p["Saldo"] != 0).any() else (df_p["Debet"].sum() - df_p["Kredit"].sum())

    debet_c, kredit_c = df_c["Debet"].sum(), df_c["Kredit"].sum()
    debet_p, kredit_p = df_p["Debet"].sum(), df_p["Kredit"].sum()

    matched, un_c, un_p = [], [], []
    p_used = set()
    for _, row_c in df_c.iterrows():
        found = False
        for idx_p, row_p in df_p.iterrows():
            if idx_p in p_used:
                continue
            if abs(row_c["Kredit"] - row_p["Debet"]) < 1.0 or abs(row_c["Debet"] - row_p["Kredit"]) < 1.0:
                matched.append({
                    "Uraian": row_c["Uraian"],
                    "Nominal": rupiah(row_c["Debet"] or row_c["Kredit"]),
                    "Status": "COCOK",
                })
                p_used.add(idx_p)
                found = True
                break
        if not found:
            un_c.append({
                "Uraian": row_c["Uraian"],
                "Nominal": rupiah(row_c["Debet"] or row_c["Kredit"]),
                "Status": "BELUM DI PUSAT",
            })
    for idx_p, row_p in df_p.iterrows():
        if idx_p not in p_used:
            un_p.append({
                "Uraian": row_p["Uraian"],
                "Nominal": rupiah(row_p["Debet"] or row_p["Kredit"]),
                "Status": "HANYA DI PUSAT",
            })

    return {
        "sal_c": sal_c,
        "sal_p": sal_p,
        "selisih": abs(sal_p - sal_c),
        "debet_c": debet_c,
        "kredit_c": kredit_c,
        "debet_p": debet_p,
        "kredit_p": kredit_p,
        "matched": pd.DataFrame(matched),
        "un_c": pd.DataFrame(un_c),
        "un_p": pd.DataFrame(un_p),
    }

def _extract_subledger_from_df(raw, file_bytes, is_csv=False, sheet_name=None):
    header_row = -1
    is_subledger_file = False
    for i, row in raw.iterrows():
        row_str = " ".join([str(v).lower() for v in row.values if pd.notna(v)])
        if "laporan transaksi" in row_str or "tabungan" in row_str or "simpanan" in row_str:
            is_subledger_file = True
        if "no." in row_str and "rekening" in row_str and ("setoran" in row_str or "penarikan" in row_str):
            header_row = i
            is_subledger_file = True
            break

    if not is_subledger_file or header_row == -1:
        return pd.DataFrame()

    if is_csv:
        df = pd.read_csv(BytesIO(file_bytes), skiprows=header_row, sep=None, engine='python')
    else:
        df = pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name, skiprows=header_row)

    df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if "rekening" in cl:
            col_map[c] = "No_Rekening"
        elif "nasabah" in cl or "nama" in cl:
            col_map[c] = "Nama_Nasabah"
        elif "tgl" in cl or "tanggal" in cl:
            col_map[c] = "Tgl_Trans"
        elif "bukti" in cl:
            col_map[c] = "No_Bukti"
        elif "setoran" in cl:
            col_map[c] = "Setoran"
        elif "penarikan" in cl:
            col_map[c] = "Penarikan"

    df = df.rename(columns=col_map)
    if "Setoran" in df.columns:
        df["Setoran"] = df["Setoran"].apply(to_num)
    if "Penarikan" in df.columns:
        df["Penarikan"] = df["Penarikan"].apply(to_num)
    return df

def parse_subledger_simpanan(file_bytes, filename):
    frames = []
    try:
        if filename.lower().endswith('.csv'):
            raw = pd.read_csv(BytesIO(file_bytes), header=None, sep=None, engine='python')
            df = _extract_subledger_from_df(raw, file_bytes, is_csv=True)
            if not df.empty:
                df["Source_File"] = filename
                frames.append(df)
        else:
            xls = pd.ExcelFile(BytesIO(file_bytes))
            for sh in xls.sheet_names:
                raw = pd.read_excel(BytesIO(file_bytes), sheet_name=sh, header=None)
                df = _extract_subledger_from_df(raw, file_bytes, is_csv=False, sheet_name=sh)
                if not df.empty:
                    df["Source_File"] = filename
                    frames.append(df)
        if frames:
            return pd.concat(frames, ignore_index=True)
    except Exception:
        pass
    return pd.DataFrame()

def perform_subledger_vs_gl_analysis(df_subledger, df_gl):
    if df_subledger.empty:
        return None
    tot_setoran = df_subledger["Setoran"].sum() if "Setoran" in df_subledger.columns else 0.0
    tot_penarikan = df_subledger["Penarikan"].sum() if "Penarikan" in df_subledger.columns else 0.0

    tot_kredit_gl = df_gl["Kredit"].sum() if "Kredit" in df_gl.columns else 0.0
    tot_debet_gl = df_gl["Debet"].sum() if "Debet" in df_gl.columns else 0.0

    selisih_setoran = tot_setoran - tot_kredit_gl
    selisih_penarikan = tot_penarikan - tot_debet_gl

    unmatched_subledger = []
    if "No_Bukti" in df_subledger.columns and "No. Bukti" in df_gl.columns:
        gl_bukti_set = set(df_gl["No. Bukti"].dropna().astype(str).str.strip().str.lower().unique())
        for idx, row in df_subledger.iterrows():
            b_val = str(row.get("No_Bukti", "")).strip()
            b_val_lower = b_val.lower()
            num_val = row.get("Setoran", 0.0) or row.get("Penarikan", 0.0)

            if num_val > 0 and b_val_lower not in ("", "nan") and b_val_lower not in gl_bukti_set:
                unmatched_subledger.append({
                    "Letak Baris": idx + 1,
                    "Tgl Trans": row.get("Tgl_Trans", "-"),
                    "No Rekening": row.get("No_Rekening", "-"),
                    "Nama Nasabah": row.get("Nama_Nasabah", "-"),
                    "No Bukti": b_val,
                    "Nominal Transaksi": rupiah(num_val),
                    "Keterangan Auditor": "Nomor Bukti Subledger Belum Ter-record di Buku Besar",
                })

    return {
        "tot_setoran": tot_setoran,
        "tot_kredit_gl": tot_kredit_gl,
        "selisih_setoran": selisih_setoran,
        "tot_penarikan": tot_penarikan,
        "tot_debet_gl": tot_debet_gl,
        "selisih_penarikan": selisih_penarikan,
        "df_unmatched_subledger": pd.DataFrame(unmatched_subledger),
    }

def build_pdf_report(df, rak, sub_res=None, unbalanced_bukti=None):
    if not REPORTLAB_AVAILABLE:
        return b"Error: Modul reportlab tidak terinstall."
        
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )
    elements = []
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#1E3A5F")

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=navy,
        alignment=0,
        spaceAfter=12,
    )

    h2 = ParagraphStyle(
        "Heading2Style",
        parent=styles["Heading2"],
        textColor=navy,
        fontSize=11,
        leading=15,
        spaceBefore=10,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    )

    cell_style = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#374151"),
    )

    cell_red_style = ParagraphStyle(
        "CellRed",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#DC2626"),
    )

    header_style = ParagraphStyle(
        "HeaderCell",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=colors.white,
    )

    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1E293B"),
        fontName="Helvetica",
    )

    elements.append(Paragraph(f"<b>{APP_TITLE}</b>", title_style))
    elements.append(Paragraph(f"Hak Cipta © {CURRENT_YEAR} {OWNER}. Seluruh Hak Cipta Dilindungi.", ParagraphStyle("Sub", parent=styles["Normal"], fontSize=8, textColor=colors.grey)))
    elements.append(Paragraph(f"<i>Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M WIB')}</i>", ParagraphStyle("Sub2", parent=styles["Normal"], fontSize=8, textColor=colors.grey)))
    elements.append(Spacer(1, 10))

    # Jika mode RAK aktif
    if rak:
        summary_data = [
            [Paragraph("<b>Keterangan</b>", header_style), Paragraph("<b>Nilai</b>", header_style)],
            [Paragraph("Saldo Akhir Cabang", cell_style), Paragraph(rupiah(rak["sal_c"]), cell_style)],
            [Paragraph("Saldo Akhir Pusat", cell_style), Paragraph(rupiah(rak["sal_p"]), cell_style)],
            [Paragraph("Selisih Pembukuan", cell_style), Paragraph(rupiah(rak["selisih"]), cell_style)],
        ]
        t_sum = Table(summary_data, colWidths=[140 * mm, 126 * mm])
        t_sum.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(t_sum)
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("<b>Analisis & Penjelasan Penyebab Selisih RAK</b>", h2))
        un_c_df = rak.get("un_c", pd.DataFrame())
        un_p_df = rak.get("un_p", pd.DataFrame())
        selisih_val = rak["selisih"]

        exp_text = f"• <b>Saldo Akhir Buku Besar:</b> Saldo Akhir Kantor Cabang tercatat sebesar <b>{rupiah(rak['sal_c'])}</b>, sedangkan Saldo Akhir Kantor Pusat tercatat sebesar <b>{rupiah(rak['sal_p'])}</b>.<br/>"
        exp_text += f"• <b>Selisih Pembukuan:</b> Selisih sebesar <b>{rupiah(selisih_val)}</b> merupakan selisih saldo akhir riil antara pembukuan Pusat dan Cabang.<br/>"
        exp_text += "• <b>Definisi Transaksi Gantung (Outstanding):</b> Transaksi yang sudah dicatat oleh salah satu pihak (misal Cabang) namun belum dicatat/di-posting oleh pihak seberangnya (Pusat) pada periode yang sama.<br/>"
        if not un_c_df.empty:
            exp_text += f"• <b>Transaksi Gantung di Cabang Belum Dicatat di Pusat ({len(un_c_df)} transaksi):</b> Contoh uraian: <i>{un_c_df.iloc[0].get('Uraian', 'N/A')}</i> senilai <b>{un_c_df.iloc[0].get('Nominal', 'N/A')}</b>.<br/>"
        if not un_p_df.empty:
            exp_text += f"• <b>Transaksi Gantung di Pusat Belum Dicatat di Cabang ({len(un_p_df)} transaksi):</b> Contoh uraian: <i>{un_p_df.iloc[0].get('Uraian', 'N/A')}</i> senilai <b>{un_p_df.iloc[0].get('Nominal', 'N/A')}</b>.<br/>"
        exp_text += "• <b>Rekomendasi Auditor:</b> Lakukan konfirmasi timbal balik antar kantor dan buat jurnal penyesuaian (adjustment entries) untuk memulihkan kesesuaian laporan."

        elements.append(Paragraph(exp_text, body_style))
        elements.append(Spacer(1, 12))
    
    # Jika mode Kantor Tunggal (Single Office)
    else:
        tot_db = df["Debet"].sum() if "Debet" in df.columns else 0.0
        tot_kr = df["Kredit"].sum() if "Kredit" in df.columns else 0.0
        diff_bal = abs(tot_db - tot_kr)

        summary_data = [
            [Paragraph("<b>Parameter Neraca Saldo Internal</b>", header_style), Paragraph("<b>Nilai</b>", header_style)],
            [Paragraph("Total Debet", cell_style), Paragraph(rupiah(tot_db), cell_style)],
            [Paragraph("Total Kredit", cell_style), Paragraph(rupiah(tot_kr), cell_style)],
            [Paragraph("Selisih Debet vs Kredit", cell_style), Paragraph(rupiah(diff_bal), cell_style)],
        ]
        t_sum = Table(summary_data, colWidths=[140 * mm, 126 * mm])
        t_sum.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(t_sum)
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("<b>Analisis Pembukuan Kantor Tunggal</b>", h2))
        if diff_bal < 1.0:
            single_exp = "• <b>Status Trial Balance:</b> SEIMBANG (BALANCED). Total seluruh Debet sama persis dengan total Kredit.<br/>"
        else:
            single_exp = f"• <b>Status Trial Balance:</b> TIDAK SEIMBANG. Ditemukan selisih global sebesar <b>{rupiah(diff_bal)}</b>.<br/>"
        
        if unbalanced_bukti is not None and not unbalanced_bukti.empty:
            single_exp += f"• <b>Temuan Jurnal Pincang:</b> Terdapat <b>{len(unbalanced_bukti)}</b> nomor bukti transaksi yang total debet dan kredit per buktinya tidak seimbang.<br/>"
        else:
            single_exp += "• <b>Validasi Per No. Bukti:</b> Seluruh transaksi per nomor bukti terverifikasi seimbang.<br/>"
        
        elements.append(Paragraph(single_exp, body_style))
        elements.append(Spacer(1, 12))

    if sub_res:
        selisih_set = sub_res["selisih_setoran"]
        elements.append(Paragraph("<b>Hasil Uji Kesesuaian Subledger Simpanan vs Buku Besar</b>", h2))
        sub_summary = [
            [Paragraph("<b>Parameter Uji Kesesuaian</b>", header_style), Paragraph("<b>Nilai / Selisih</b>", header_style)],
            [Paragraph("Total Setoran (Subledger Nasabah)", cell_style), Paragraph(rupiah(sub_res["tot_setoran"]), cell_style)],
            [Paragraph("Total Kredit di Buku Besar (GL)", cell_style), Paragraph(rupiah(sub_res["tot_kredit_gl"]), cell_style)],
            [Paragraph("Selisih Setoran", cell_style), Paragraph(rupiah(sub_res["selisih_setoran"]), cell_style)],
            [Paragraph("Selisih Penarikan", cell_style), Paragraph(rupiah(sub_res["selisih_penarikan"]), cell_style)],
        ]
        t_sub = Table(sub_summary, colWidths=[140 * mm, 126 * mm])
        t_sub.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t_sub)
        elements.append(Spacer(1, 8))

        if abs(selisih_set) < 1.0:
            sub_exp = "• <b>Analisis Kesesuaian Setoran & Penarikan:</b> Seluruh transaksi setoran dan penarikan pada subledger nasabah telah terverifikasi sinkron terhadap Buku Besar (General Ledger).<br/>"
        else:
            sub_exp = f"• <b>Analisis Kesesuaian Setoran & Penarikan:</b> Ditemukan selisih setoran sebesar <b>{rupiah(selisih_set)}</b> antara Subledger Nasabah dan Buku Besar (GL).<br/>"

        elements.append(Paragraph(sub_exp, body_style))
        elements.append(Spacer(1, 12))

    if not df.empty:
        elements.append(Paragraph("<b>Rincian Jurnal Transaksi (Baris Ditandai Merah = Indikasi Selisih/Unmatched)</b>", h2))
        headers = [Paragraph(f"<b>{c}</b>", header_style) for c in df.columns]
        table_data = [headers]

        unmatched_refs = set()
        if rak:
            for _, r in pd.concat([rak.get("un_c", pd.DataFrame()), rak.get("un_p", pd.DataFrame())]).iterrows():
                if "Uraian" in r:
                    unmatched_refs.add(str(r["Uraian"]).strip().lower())
        
        if sub_res and "df_unmatched_subledger" in sub_res:
            df_un_sub = sub_res["df_unmatched_subledger"]
            if not df_un_sub.empty and "No Bukti" in df_un_sub.columns:
                for b_val in df_un_sub["No Bukti"].dropna():
                    unmatched_refs.add(str(b_val).strip().lower())

        bad_rows = []
        for idx, row in df.iterrows():
            uraian_row = str(row.get("Uraian", "")).strip().lower()
            bukti_row = str(row.get("No. Bukti", "")).strip().lower()
            
            is_unmatched = (
                any(u in uraian_row for u in unmatched_refs if len(u) > 3) or 
                (bukti_row in unmatched_refs and bukti_row != "")
            )
            if is_unmatched:
                bad_rows.append(idx + 1)

            r_cells = []
            for col in df.columns:
                val = row[col]
                txt = rupiah(val) if isinstance(val, (int, float)) and col not in ["KD", "No. Bukti", "Kode Perkiraan"] else str(val)
                style_to_use = cell_red_style if is_unmatched else cell_style
                r_cells.append(Paragraph(txt, style_to_use))
            table_data.append(r_cells)

        col_count = len(df.columns)
        col_width = 267.0 / col_count if col_count > 0 else 50
        col_widths = [col_width * mm] * col_count

        t_main = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]

        for r_idx in bad_rows:
            t_style_cmds.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#FEE2E2")))

        t_main.setStyle(TableStyle(t_style_cmds))
        elements.append(t_main)

    doc.build(elements)
    return buf.getvalue()

# ---------- ANTARMUKA UTAMA ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    
    if "audit_logs" not in st.session_state:
        st.session_state.audit_logs = []

    up_files = st.file_uploader(
        "Upload file Excel atau CSV", accept_multiple_files=True, type=["xlsx", "xls", "csv"]
    )

    c_btn1, c_btn2 = st.columns([1, 4])
    with c_btn1:
        if st.button("🔄 Reset Sesi"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.success("Sesi berhasil dibersihkan!")
            st.rerun()

    if st.button("🚀 Ekstrak & Analisis", type="primary"):
        if up_files and len(up_files) >= 1:
            for key in list(st.session_state.keys()):
                if key != "audit_logs":
                    del st.session_state[key]

            all_frames = [process_uploaded_file(f) for f in up_files]
            combined = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=STD_COLS)

            subledger_frames = []
            for f in up_files:
                df_sub = parse_subledger_simpanan(f.getvalue(), f.name)
                if not df_sub.empty:
                    subledger_frames.append(df_sub)

            if not combined.empty:
                st.session_state.df = combined
                st.session_state.rak = perform_rak_reconciliation(combined)
                st.session_state.unbalanced_bukti = perform_per_bukti_validation(combined)
                st.session_state.audit_logs.append({
                    "Waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Aksi": "Ekstrak File",
                    "Keterangan": f"Berhasil memuat {len(combined)} baris dari {len(up_files)} file."
                })

            if subledger_frames and not combined.empty:
                combined_sub = pd.concat(subledger_frames, ignore_index=True)
                st.session_state.subledger_analysis = perform_subledger_vs_gl_analysis(
                    combined_sub, combined
                )
            else:
                st.session_state.subledger_analysis = None

            st.success(f"Berhasil mengekstrak {len(combined)} baris data!")
            st.rerun()

    if "df" in st.session_state and st.session_state.df is not None and not st.session_state.df.empty:
        df_current = st.session_state.df

        if "Debet" in df_current.columns and "Kredit" in df_current.columns:
            tot_db = df_current["Debet"].apply(to_num).sum()
            tot_kr = df_current["Kredit"].apply(to_num).sum()
            diff_bal = abs(tot_db - tot_kr)
            
            st.markdown("### ⚖️ Neraca Saldo (Trial Balance Check)")
            b1, b2, b3 = st.columns(3)
            b1.metric("Total Debet", rupiah(tot_db))
            b2.metric("Total Kredit", rupiah(tot_kr))
            b3.metric("Selisih Debet vs Kredit", rupiah(diff_bal), delta_color="inverse")
            
            if diff_bal < 1.0:
                st.success("✨ **STATUS JURNAL: SEIMBANG (BALANCED)** — Total Debet sama dengan Total Kredit.")
            else:
                st.error(f"⚠️ **STATUS JURNAL: TIDAK SEIMBANG** — Terdapat selisih sebesar {rupiah(diff_bal)} antara Debet dan Kredit.")

        # Tampilkan Validasi Per Nomor Bukti (Khusus Mode Kantor Tunggal)
        if not st.session_state.get("rak") and "unbalanced_bukti" in st.session_state:
            unb_df = st.session_state.unbalanced_bukti
            st.markdown("### 🔍 Validasi Keseimbangan per Nomor Bukti")
            if not unb_df.empty:
                st.warning(f"Ditemukan **{len(unb_df)} nomor bukti** dengan total Debet dan Kredit yang tidak seimbang:")
                st.dataframe(unb_df, use_container_width=True)
            else:
                st.success("✨ **Semua No. Bukti Seimbang** — Setiap transaksi per nomor bukti memiliki Debet dan Kredit yang cocok.")

        # Tampilkan RAK Jika Terdeteksi Antar Kantor
        if st.session_state.get("rak"):
            rak = st.session_state.rak
            st.subheader("① Hasil Rekonsiliasi Antar Kantor (RAK)")
            c1, c2, c3 = st.columns(3)
            c1.metric("Saldo Akhir Cabang", rupiah(rak["sal_c"]))
            c2.metric("Saldo Akhir Pusat", rupiah(rak["sal_p"]))
            c3.metric("Selisih Pembukuan", rupiah(rak["selisih"]))
            
            t1, t2, t3 = st.tabs(["🔴 Selisih & Unmatched", "✅ Matched", "📈 Grafik RAK"])
            with t1:
                st.dataframe(pd.concat([rak["un_c"], rak["un_p"]]), use_container_width=True)
            with t2:
                st.dataframe(rak["matched"], use_container_width=True)
            with t3:
                chart_data = pd.DataFrame({
                    "Kategori": ["Cabang", "Pusat"],
                    "Saldo Akhir": [rak["sal_c"], rak["sal_p"]]
                })
                st.bar_chart(chart_data.set_index("Kategori"))

        if st.session_state.get("subledger_analysis"):
            st.markdown("---")
            st.subheader("🔍 Hasil Uji Kesesuaian Subledger Simpanan vs Buku Besar")
            sub_res = st.session_state.subledger_analysis
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Setoran", rupiah(sub_res["tot_setoran"]))
            m2.metric("Total Kredit (GL)", rupiah(sub_res["tot_kredit_gl"]))
            m3.metric("Selisih Setoran", rupiah(sub_res["selisih_setoran"]), delta_color="inverse")
            m4.metric("Selisih Penarikan", rupiah(sub_res["selisih_penarikan"]), delta_color="inverse")

            st.warning("📍 **Audit Trail / Letak Ketidaksesuaian Transaksi:**")
            df_un = sub_res["df_unmatched_subledger"]
            if not df_un.empty:
                st.dataframe(df_un, use_container_width=True)
            else:
                st.success("Semua transaksi di Subledger cocok dan ter-posting sempurna ke Buku Besar.")

        st.subheader("② Pratinjau & Edit Data Jurnal")

        with st.expander("🛠️ Panel Pengaturan Tabel (Kolom & Posisi Baris)", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                col_add = st.text_input("Nama Kolom Baru:")
                if st.button("➕ Tambah Kolom"):
                    if col_add and col_add not in st.session_state.df.columns:
                        st.session_state.df[col_add] = ""
                        st.session_state.audit_logs.append({
                            "Waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Aksi": "Tambah Kolom",
                            "Keterangan": f"Menambahkan kolom baru: {col_add}"
                        })
                        st.rerun()
            with c2:
                col_del = st.selectbox("Pilih Kolom Dihapus:", st.session_state.df.columns)
                if st.button("🗑️ Hapus Kolom"):
                    st.session_state.df = st.session_state.df.drop(columns=[col_del])
                    st.session_state.audit_logs.append({
                        "Waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Aksi": "Hapus Kolom",
                        "Keterangan": f"Menghapus kolom: {col_del}"
                    })
                    st.rerun()
            with c3:
                insert_idx = st.number_input(
                    "Sisipkan baris setelah indeks ke-:",
                    min_value=0,
                    max_value=max(0, len(st.session_state.df) - 1),
                    step=1,
                )
                if st.button("📍 Sisipkan Baris Baru"):
                    new_row = {
                        c: ("" if c not in ["Debet", "Kredit", "Saldo"] else 0.0)
                        for c in st.session_state.df.columns
                    }
                    idx_int = int(insert_idx)
                    df_top = st.session_state.df.iloc[:idx_int + 1]
                    df_bottom = st.session_state.df.iloc[idx_int + 1:]
                    df_new_row = pd.DataFrame([new_row])
                    st.session_state.df = pd.concat([df_top, df_new_row, df_bottom], ignore_index=True)
                    st.session_state.audit_logs.append({
                        "Waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Aksi": "Sisip Baris",
                        "Keterangan": f"Menyisipkan baris baru setelah indeks {idx_int}"
                    })
                    st.success(f"Baris berhasil disisipkan setelah indeks {idx_int}!")
                    st.rerun()

        edited_df = st.data_editor(
            st.session_state.df, num_rows="dynamic", use_container_width=True
        )
        if not edited_df.equals(st.session_state.df):
            st.session_state.df = edited_df
            st.session_state.unbalanced_bukti = perform_per_bukti_validation(edited_df)
            st.session_state.audit_logs.append({
                "Waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Aksi": "Edit Data Tabel",
                "Keterangan": "Pengguna melakukan perubahan langsung pada sel tabel jurnal."
            })

        with st.expander("📜 Lihat Audit Trail & Riwayat Perubahan Sesi", expanded=False):
            if st.session_state.audit_logs:
                df_logs = pd.DataFrame(st.session_state.audit_logs)
                st.dataframe(df_logs, use_container_width=True)
            else:
                st.info("Belum ada catatan aktivitas perubahan pada sesi ini.")

        st.divider()
        e1, e2 = st.columns(2)

        df_to_export = st.session_state.df.copy()
        if "Debet" in df_to_export.columns:
            df_to_export["Debet"] = df_to_export["Debet"].apply(to_num)
        if "Kredit" in df_to_export.columns:
            df_to_export["Kredit"] = df_to_export["Kredit"].apply(to_num)

        if REPORTLAB_AVAILABLE:
            pdf_data = build_pdf_report(
                df_to_export,
                st.session_state.get("rak"),
                st.session_state.get("subledger_analysis"),
                st.session_state.get("unbalanced_bukti"),
            )
            e1.download_button(
                "🖨️ Cetak PDF",
                pdf_data,
                f"Laporan_Analisis_Jurnal_{datetime.now():%Y%m%d_%H%M}.pdf",
                "application/pdf",
                use_container_width=True,
            )
        else:
            e1.error("Modul reportlab tidak terpasang. PDF tidak tersedia.")

        buf = BytesIO()
        with pd.ExcelWriter(buf) as w:
            df_to_export.to_excel(w, index=False)
        e2.download_button(
            "📊 Download Excel",
            buf.getvalue(),
            f"Hasil_Analisis_Jurnal_{datetime.now():%Y%m%d_%H%M}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

if __name__ == "__main__":
    main()
