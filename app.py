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
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def jalankan_audit_universal(file_1_obj, file_2_obj):
    # ---------------------------------------------------------
    # 1. PARSING & PEMBERSIHAN DATASET (UNIVERSAL)
    # ---------------------------------------------------------
    # Pembacaan File Pembanding 1 (Buku Besar / GL)
    df_raw_1 = pd.read_excel(file_1_obj, header=None)
    df_1 = df_raw_1.iloc[8:].copy().iloc[:, :7]
    df_1.columns = ['Tgl_Trans', 'Kode', 'No_Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo']
    df_1['Debet'] = pd.to_numeric(df_1['Debet'], errors='coerce').fillna(0)
    df_1['Kredit'] = pd.to_numeric(df_1['Kredit'], errors='coerce').fillna(0)
    df_1['Tgl_Clean'] = df_1['Tgl_Trans'].astype(str).str.strip()
    df_1['Bukti_Clean'] = df_1['No_Bukti'].astype(str).str.strip().str.upper()

    # Pembacaan File Pembanding 2 (Subledger / Rincian)
    df_raw_2 = pd.read_excel(file_2_obj, header=None)
    df_2 = df_raw_2.iloc[6:].copy().iloc[:, :8]
    df_2.columns = ['No', 'No_Rekening', 'Nama_Nasabah', 'Tgl_Trans', 'No_Bukti', 'Kode_Trans', 'Kredit_2', 'Debet_2']
    df_2['Kredit_2'] = pd.to_numeric(df_2['Kredit_2'], errors='coerce').fillna(0)
    df_2['Debet_2'] = pd.to_numeric(df_2['Debet_2'], errors='coerce').fillna(0)
    df_2['Tgl_Clean'] = df_2['Tgl_Trans'].astype(str).str.strip()
    df_2['Bukti_Clean'] = df_2['No_Bukti'].astype(str).str.strip().str.upper()

    # Filter khusus transaksi dengan nomor bukti valid (mengabaikan NaN/Header)
    f1_valid = df_1[df_1['No_Bukti'].notna() & (df_1['Bukti_Clean'] != 'NAN')].copy()
    f2_valid = df_2[
        df_2['No_Bukti'].notna() & 
        (df_2['Bukti_Clean'] != 'NAN') & 
        (df_2['No_Rekening'].astype(str) != 'No Rekening')
    ].copy()

    # ---------------------------------------------------------
    # 2. ALGORITMA AUDIT & PENCARIAN SELISIH PINTAR
    # ---------------------------------------------------------
    set_f1 = set(f1_valid['Bukti_Clean'])
    set_f2 = set(f2_valid['Bukti_Clean'])

    # A. Transaksi Gantung (Unmatched Vouchers)
    gantung_di_f1 = f1_valid[~f1_valid['Bukti_Clean'].isin(set_f2)]
    gantung_di_f2 = f2_valid[~f2_valid['Bukti_Clean'].isin(set_f1)]

    # B. Matching per Nomor Bukti
    merged = pd.merge(
        f1_valid, f2_valid,
        on='Bukti_Clean',
        suffixes=('_F1', '_F2')
    )

    # C. Beda Tanggal Catat
    beda_tanggal = merged[merged['Tgl_Clean_F1'] != merged['Tgl_Clean_F2']]

    # D. Beda Nominal Rupiah
    beda_nominal = merged[
        (merged['Kredit'] != merged['Kredit_2']) | 
        (merged['Debet'] != merged['Debet_2'])
    ]

    # E. Jurnal Pincang di File Pembanding 1
    f1_by_bukti = f1_valid.groupby('Bukti_Clean').agg(
        total_debet=('Debet', 'sum'),
        total_kredit=('Kredit', 'sum')
    )
    f1_by_bukti['selisih'] = (f1_by_bukti['total_debet'] - f1_by_bukti['total_kredit']).abs()
    pincang_f1 = f1_by_bukti[f1_by_bukti['selisih'] > 0.01]

    # Total Mutasi
    f1_tot_debet = df_1['Debet'].sum()
    f1_tot_kredit = df_1['Kredit'].sum()
    f2_tot_kredit = df_2['Kredit_2'].sum()
    f2_tot_debet = df_2['Debet_2'].sum()

    selisih_kredit = f1_tot_kredit - f2_tot_kredit
    selisih_debet = f1_tot_debet - f2_tot_debet

    # ---------------------------------------------------------
    # 3. GENERATE LAPORAN AUDIT PDF PROFESIONAL
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

    # Header PDF
    elements.append(Paragraph("LAPORAN HASIL AUDIT REKONSILIASI & ANALISIS JURNAL", style_title))
    elements.append(Paragraph("Hak Cipta © 2026 Damianus Libertus. Seluruh Hak Cipta Dilindungi.", style_sub))
    elements.append(Paragraph(f"Tanggal Audit: {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')} WIB", style_sub))
    elements.append(Spacer(1, 10))

    # Ringkasan Eksekutif
    elements.append(Paragraph("1. Ringkasan Eksekutif & Indikator Temuan Audit", style_h2))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=8))

    summary_table_data = [
        [Paragraph("Parameter Uji Audit", style_bold), Paragraph("Jumlah Temuan", style_bold), Paragraph("Status Risiko", style_bold)],
        ["Transaksi Gantung di File 1 (Tidak ada di File 2)", f"{len(gantung_di_f1)} Transaksi", "Perlu Verifikasi" if len(gantung_di_f1)>0 else "Clean"],
        ["Transaksi Gantung di File 2 (Tidak ada di File 1)", f"{len(gantung_di_f2)} Transaksi", "Perlu Verifikasi" if len(gantung_di_f2)>0 else "Clean"],
        ["Transaksi Beda Tanggal Catat (File 1 vs File 2)", f"{len(beda_tanggal)} Transaksi", "Peringatan" if len(beda_tanggal)>0 else "Clean"],
        ["Transaksi Beda Nominal Angka", f"{len(beda_nominal)} Transaksi", "Tinggi" if len(beda_nominal)>0 else "Clean"],
        ["Jurnal Pincang di File 1 (Debet != Kredit)", f"{len(pincang_f1)} Voucher", "Tinggi" if len(pincang_f1)>0 else "Clean"]
    ]
    t_sum = Table(summary_table_data, colWidths=[240, 130, 130])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EDF2F7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(t_sum)
    elements.append(Spacer(1, 12))

    # Rekonsiliasi Nominal Mutasi
    elements.append(Paragraph("2. Rekonsiliasi Total Nominal Mutasi (File 1 vs File 2)", style_h2))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=8))

    rekon_data = [
        [Paragraph("Sisi Mutasi", style_bold), Paragraph("File Pembanding 1 (Rp)", style_bold), Paragraph("File Pembanding 2 (Rp)", style_bold), Paragraph("Selisih (Rp)", style_bold)],
        ["Mutasi Kredit / Masuk", f"{f1_tot_kredit:,.2f}", f"{f2_tot_kredit:,.2f}", f"{selisih_kredit:,.2f}"],
        ["Mutasi Debet / Keluar", f"{f1_tot_debet:,.2f}", f"{f2_tot_debet:,.2f}", f"{selisih_debet:,.2f}"]
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

    # Detail Transaksi Gantung
    if len(gantung_di_f2) > 0:
        elements.append(Paragraph("3. Rincian Transaksi Gantung (Ada di File Pembanding 2 Tapi Belum Masuk File 1)", style_h2))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=8))

        detail_gantung = [[Paragraph("Tgl", style_bold), Paragraph("No. Bukti", style_bold), Paragraph("No Rek/ID", style_bold), Paragraph("Nama / Ket", style_bold), Paragraph("Kredit (Rp)", style_bold), Paragraph("Debet (Rp)", style_bold)]]
        for _, row in gantung_di_f2.iterrows():
            detail_gantung.append([
                Paragraph(str(row['Tgl_Trans']), style_cell),
                Paragraph(str(row['No_Bukti']), style_cell),
                Paragraph(str(row['No_Rekening']), style_cell),
                Paragraph(str(row['Nama_Nasabah'])[:20], style_cell),
                f"{row['Kredit_2']:,.0f}",
                f"{row['Debet_2']:,.0f}"
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
        "gantung_f1_cnt": len(gantung_di_f1),
        "gantung_f2_cnt": len(gantung_di_f2),
        "beda_tgl_cnt": len(beda_tanggal),
        "beda_nom_cnt": len(beda_nominal),
        "pincang_cnt": len(pincang_f1)
    }, gantung_di_f2


# =========================================================
# INTERFACE STREAMLIT UTAMA
# =========================================================
st.set_page_config(page_title="Audit Rekonsiliasi & Analisis Jurnal", layout="wide")

st.title("Aplikasi Analisis Jurnal & Rekonsiliasi Audit")
st.caption("Hak Cipta © 2026 Damianus Libertus. Seluruh Hak Cipta Dilindungi.")

col1, col2 = st.columns(2)
with col1:
    file_1 = st.file_uploader("Upload File Utama / Pembanding 1 (Excel)", type=["xlsx", "xls"])
with col2:
    file_2 = st.file_uploader("Upload File Pendukung / Pembanding 2 (Excel)", type=["xlsx", "xls"])

if file_1 and file_2:
    if st.button("Jalankan Audit & Rekonsiliasi", type="primary"):
        with st.spinner("Menganalisis transaksi gantung, beda tanggal, dan selisih..."):
            pdf_bytes, summary, gantung_df = jalankan_audit_universal(file_1, file_2)
            
            st.success("Audit Selesai Dilaksanakan!")
            
            # Dashboard Metric Interaktif
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Gantung (File 2)", f"{summary['gantung_f2_cnt']} Tx")
            m2.metric("Gantung (File 1)", f"{summary['gantung_f1_cnt']} Tx")
            m3.metric("Beda Tanggal", f"{summary['beda_tgl_cnt']} Tx")
            m4.metric("Beda Nominal", f"{summary['beda_nom_cnt']} Tx")
            m5.metric("Jurnal Pincang", f"{summary['pincang_cnt']} Voucher")

            if summary['gantung_f2_cnt'] > 0:
                st.subheader("Detail Transaksi Gantung di File Pembanding 2")
                st.dataframe(gantung_df[['Tgl_Trans', 'No_Bukti', 'No_Rekening', 'Nama_Nasabah', 'Kredit_2', 'Debet_2']])

            st.download_button(
                label="Download Laporan Audit Resmi (PDF)",
                data=pdf_bytes,
                file_name="Laporan_Audit_Rekonsiliasi.pdf",
                mime="application/pdf"
            )
else:
    st.info("Silakan unggah File Pembanding 1 dan File Pembanding 2 (Excel) untuk memulai analisis.")
