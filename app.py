# ==========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi Audit
# ==========================================================

import streamlit as st
import datetime
import pandas as pd
import numpy as np
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def jalankan_audit_dan_pdf(file_gl_obj, file_sub_obj):
    # ---------------------------------------------------------
    # 1. PARSING DATASET
    # ---------------------------------------------------------
    df_raw_gl = pd.read_excel(file_gl_obj, header=None)
    df_gl = df_raw_gl.iloc[8:].copy().iloc[:, :7]
    df_gl.columns = ['Tgl_Trans', 'Kode', 'No_Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo']
    df_gl['Debet'] = pd.to_numeric(df_gl['Debet'], errors='coerce').fillna(0)
    df_gl['Kredit'] = pd.to_numeric(df_gl['Kredit'], errors='coerce').fillna(0)
    df_gl['Tgl_Trans'] = df_gl['Tgl_Trans'].astype(str).str.strip()
    df_gl['No_Bukti_Clean'] = df_gl['No_Bukti'].astype(str).str.strip()

    df_raw_sub = pd.read_excel(file_sub_obj, header=None)
    df_sub = df_raw_sub.iloc[6:].copy().iloc[:, :8]
    df_sub.columns = ['No', 'No_Rekening', 'Nama_Nasabah', 'Tgl_Trans', 'No_Bukti', 'Kode_Trans', 'Setoran', 'Penarikan']
    df_sub['Setoran'] = pd.to_numeric(df_sub['Setoran'], errors='coerce').fillna(0)
    df_sub['Penarikan'] = pd.to_numeric(df_sub['Penarikan'], errors='coerce').fillna(0)
    df_sub['Tgl_Trans'] = df_sub['Tgl_Trans'].astype(str).str.strip()
    df_sub['No_Bukti_Clean'] = df_sub['No_Bukti'].astype(str).str.strip()

    # ---------------------------------------------------------
    # 2. LOGIKA AUDIT LENGKAP (TRANSAKSI GANTUNG, SELISIH, TANGGAL)
    # ---------------------------------------------------------
    
    # Filter No Bukti Valid (Abaikan AUTO-SYSTEM / NaN untuk matching voucher)
    gl_valid = df_gl[df_gl['No_Bukti'].notna() & (df_gl['No_Bukti_Clean'] != 'nan')].copy()
    sub_valid = df_sub[df_sub['No_Bukti'].notna() & (df_sub['No_Bukti_Clean'] != 'nan')].copy()

    set_bukti_gl = set(gl_valid['No_Bukti_Clean'])
    set_bukti_sub = set(sub_valid['No_Bukti_Clean'])

    # A. Transaksi Gantung (Unmatched)
    gantung_di_gl = gl_valid[~gl_valid['No_Bukti_Clean'].isin(set_bukti_sub)]
    gantung_di_sub = sub_valid[~sub_valid['No_Bukti_Clean'].isin(set_bukti_gl)]

    # B. Matching per No Bukti
    merged = pd.merge(
        gl_valid, sub_valid,
        on='No_Bukti_Clean',
        suffixes=('_GL', '_SUB')
    )

    # C. Beda Tanggal Catat
    beda_tanggal = merged[merged['Tgl_Trans_GL'] != merged['Tgl_Trans_SUB']]

    # D. Beda Nominal (Kredit GL vs Setoran Sub / Debet GL vs Penarikan Sub)
    beda_nominal = merged[
        (merged['Kredit'] != merged['Setoran']) | 
        (merged['Debet'] != merged['Penarikan'])
    ]

    # E. Jurnal Pincang di GL
    gl_by_bukti = gl_valid.groupby('No_Bukti_Clean').agg(
        total_debet=('Debet', 'sum'),
        total_kredit=('Kredit', 'sum')
    )
    gl_by_bukti['selisih'] = (gl_by_bukti['total_debet'] - gl_by_bukti['total_kredit']).abs()
    pincang_gl = gl_by_bukti[gl_by_bukti['selisih'] > 0.01]

    # Ringkasan Total
    gl_total_debet = df_gl['Debet'].sum()
    gl_total_kredit = df_gl['Kredit'].sum()
    sub_total_setoran = df_sub['Setoran'].sum()
    sub_total_penarikan = df_sub['Penarikan'].sum()

    selisih_kredit = gl_total_kredit - sub_total_setoran
    selisih_debet = gl_total_debet - sub_total_penarikan

    # ---------------------------------------------------------
    # 3. GENERATE LAPORAN PDF PROFESIONAL
    # ---------------------------------------------------------
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=25, leftMargin=25, topMargin=25, bottomMargin=25
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=15, leading=18, textColor=colors.HexColor('#1A365D'))
    style_sub = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#4A5568'))
    style_h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=11, leading=14, textColor=colors.HexColor('#2B6CB0'))
    style_bold = ParagraphStyle('B', parent=styles['Normal'], fontSize=8, fontName='Helvetica-Bold')
    style_cell = ParagraphStyle('C', parent=styles['Normal'], fontSize=8)

    elements = []

    # Header Document
    elements.append(Paragraph("LAPORAN HASIL AUDIT REKONSILIASI & ANALISIS JURNAL", style_title))
    elements.append(Paragraph("Hak Cipta © 2026 Damianus Libertus. Seluruh Hak Cipta Dilindungi.", style_sub))
    elements.append(Paragraph(f"Tanggal Audit: {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')} WIB", style_sub))
    elements.append(Spacer(1, 10))

    # SECTION 1: EXECUTIVE SUMMARY AUDIT
    elements.append(Paragraph("1. Ringkasan Eksekutif & Indikator Temuan Audit", style_h2))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=8))

    summary_table_data = [
        [Paragraph("Parameter Uji Audit", style_bold), Paragraph("Jumlah Temuan", style_bold), Paragraph("Status Risiko", style_bold)],
        ["Transaksi Gantung di GL (Tidak ada di Subledger)", f"{len(gantung_di_gl)} Transaksi", "Perlu Verifikasi" if len(gantung_di_gl)>0 else "Clean"],
        ["Transaksi Gantung di Subledger (Belum di-Jurnal)", f"{len(gantung_di_sub)} Transaksi", "Perlu Verifikasi" if len(gantung_di_sub)>0 else "Clean"],
        ["Transaksi Beda Tanggal Catat (GL vs Subledger)", f"{len(beda_tanggal)} Transaksi", "Peringatan" if len(beda_tanggal)>0 else "Clean"],
        ["Transaksi Beda Nominal Angka", f"{len(beda_nominal)} Transaksi", "Tinggi" if len(beda_nominal)>0 else "Clean"],
        ["Jurnal Pincang di GL (Debet != Kredit)", f"{len(pincang_gl)} Voucher", "Tinggi" if len(pincang_gl)>0 else "Clean"]
    ]
    t_sum = Table(summary_table_data, colWidths=[240, 130, 130])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EDF2F7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(t_sum)
    elements.append(Spacer(1, 12))

    # SECTION 2: REKONSILIASI GLOBAL
    elements.append(Paragraph("2. Rekonsiliasi Nominal Mutasi (GL vs Subledger)", style_h2))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=8))

    rekon_data = [
        [Paragraph("Sisi Mutasi", style_bold), Paragraph("Buku Besar / GL (Rp)", style_bold), Paragraph("Subledger (Rp)", style_bold), Paragraph("Selisih (Rp)", style_bold)],
        ["Setoran / Mutasi Kredit", f"{gl_total_kredit:,.2f}", f"{sub_total_setoran:,.2f}", f"{selisih_kredit:,.2f}"],
        ["Penarikan / Mutasi Debet", f"{gl_total_debet:,.2f}", f"{sub_total_penarikan:,.2f}", f"{selisih_debet:,.2f}"]
    ]
    t_rek = Table(rekon_data, colWidths=[140, 120, 120, 120])
    t_rek.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EDF2F7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(t_rek)
    elements.append(Spacer(1, 12))

    # SECTION 3: DETAIL TRANSAKSI GANTUNG DI SUBLEDGER
    if len(gantung_di_sub) > 0:
        elements.append(Paragraph("3. Detail Transaksi Gantung (Tercatat di Subledger Tapi Belum Masuk GL)", style_h2))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=8))

        detail_gantung = [[Paragraph("Tgl Sub", style_bold), Paragraph("No. Bukti", style_bold), Paragraph("No Rekening", style_bold), Paragraph("Nama Nasabah", style_bold), Paragraph("Setoran (Rp)", style_bold), Paragraph("Penarikan (Rp)", style_bold)]]
        for _, row in gantung_di_sub.iterrows():
            detail_gantung.append([
                Paragraph(str(row['Tgl_Trans']), style_cell),
                Paragraph(str(row['No_Bukti']), style_cell),
                Paragraph(str(row['No_Rekening']), style_cell),
                Paragraph(str(row['Nama_Nasabah'])[:20], style_cell),
                f"{row['Setoran']:,.0f}",
                f"{row['Penarikan']:,.0f}"
            ])
        t_gantung = Table(detail_gantung, colWidths=[65, 80, 95, 110, 75, 75])
        t_gantung.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FEEBC8')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('ALIGN', (4,1), (-1,-1), 'RIGHT'),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_gantung)

    doc.build(elements)
    buffer.seek(0)
    return buffer, {
        "gl_debet": gl_total_debet,
        "gl_kredit": gl_total_kredit,
        "sub_setoran": sub_total_setoran,
        "sub_penarikan": sub_total_penarikan,
        "gantung_gl_cnt": len(gantung_di_gl),
        "gantung_sub_cnt": len(gantung_di_sub),
        "beda_tgl_cnt": len(beda_tanggal),
        "beda_nom_cnt": len(beda_nominal),
        "pincang_cnt": len(pincang_gl)
    }

# =========================================================
# INTERFACE STREAMLIT UTAMA
# =========================================================
st.set_page_config(page_title="Audit Rekonsiliasi & Analisis Jurnal", layout="wide")

st.title("Aplikasi Analisis Jurnal & Rekonsiliasi Audit")
st.caption("Hak Cipta © 2026 Damianus Libertus. Seluruh Hak Cipta Dilindungi.")

col1, col2 = st.columns(2)
with col1:
    file_gl = st.file_uploader("Upload File Buku Besar / Jurnal Utama (GL)", type=["xlsx", "xls"])
with col2:
    file_sub = st.file_uploader("Upload File Subledger / Rincian Transaksi", type=["xlsx", "xls"])

if file_gl and file_sub:
    if st.button("Jalankan Audit & Rekonsiliasi", type="primary"):
        with st.spinner("Menganalisis transaksi gantung, beda tanggal, dan selisih..."):
            pdf_bytes, summary = jalankan_audit_dan_pdf(file_gl, file_sub)
            
            st.success("Audit Selesai Dilaksanakan!")
            
            # Dashboard Ringkasan Hasil Uji Audit
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Transaksi Gantung (Sub)", f"{summary['gantung_sub_cnt']} Tx")
            m2.metric("Transaksi Gantung (GL)", f"{summary['gantung_gl_cnt']} Tx")
            m3.metric("Selisih Tanggal", f"{summary['beda_tgl_cnt']} Tx")
            m4.metric("Selisih Nominal", f"{summary['beda_nom_cnt']} Tx")
            m5.metric("Jurnal Pincang", f"{summary['pincang_cnt']} Voucher")

            st.download_button(
                label="Download Laporan Audit Resmi (PDF)",
                data=pdf_bytes,
                file_name="Laporan_Audit_Rekonsiliasi.pdf",
                mime="application/pdf"
            )
else:
    st.info("Silakan unggah File Buku Besar (GL) dan File Subledger untuk memulai proses audit.")
