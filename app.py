# ==========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi
# ==========================================================

import os
import datetime
import pandas as pd
import numpy as np

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def buat_laporan_rekonsiliasi(gl_filepath, subledger_filepath, output_pdf_path):
    # ==========================================
    # 1. BACA DAN BERSIHKAN DATA
    # ==========================================
    
    # Reading GL File (Simp. Harian)
    df_raw_gl = pd.read_excel(gl_filepath, header=None)
    df_gl = df_raw_gl.iloc[8:].copy()
    df_gl = df_gl.iloc[:, :7]
    df_gl.columns = ['Tgl_Trans', 'Kode', 'No_Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo']
    
    # Tangani No Bukti yang kosong (misal: Bunga Otomatis)
    df_gl['No_Bukti'] = df_gl['No_Bukti'].fillna('AUTO-SYSTEM')
    df_gl['Debet'] = pd.to_numeric(df_gl['Debet'], errors='coerce').fillna(0)
    df_gl['Kredit'] = pd.to_numeric(df_gl['Kredit'], errors='coerce').fillna(0)
    df_gl['Tgl_Trans'] = df_gl['Tgl_Trans'].astype(str)

    # Reading Subledger File (Lap. Transaksi Tabungan)
    df_raw_sub = pd.read_excel(subledger_filepath, header=None)
    df_sub = df_raw_sub.iloc[6:].copy()
    df_sub = df_sub.iloc[:, :8]
    df_sub.columns = ['No', 'No_Rekening', 'Nama_Nasabah', 'Tgl_Trans', 'No_Bukti', 'Kode_Trans', 'Setoran', 'Penarikan']
    
    df_sub['No_Bukti'] = df_sub['No_Bukti'].fillna('AUTO-SYSTEM')
    df_sub['Setoran'] = pd.to_numeric(df_sub['Setoran'], errors='coerce').fillna(0)
    df_sub['Penarikan'] = pd.to_numeric(df_sub['Penarikan'], errors='coerce').fillna(0)
    df_sub['Tgl_Trans'] = df_sub['Tgl_Trans'].astype(str)

    # ==========================================
    # 2. PERHITUNGAN AKUNTANSI & REKONSILIASI
    # ==========================================
    
    # Ringkasan Buku Besar (GL COA 2040102)
    gl_debet = df_gl['Debet'].sum()      # Pengurangan Kewajiban (Penarikan)
    gl_kredit = df_gl['Kredit'].sum()    # Penambahan Kewajiban (Setoran)
    gl_selisih_internal = gl_debet - gl_kredit

    # Ringkasan Subledger Tabungan Nasabah
    sub_setoran = df_sub['Setoran'].sum()
    sub_penarikan = df_sub['Penarikan'].sum()

    # Uji Kesesuaian GL vs Subledger
    selisih_setoran = gl_kredit - sub_setoran
    selisih_penarikan = gl_debet - sub_penarikan

    # Audit Transaksi Pincang per No Bukti di GL
    gl_by_bukti = df_gl[df_gl['No_Bukti'] != 'AUTO-SYSTEM'].groupby('No_Bukti').agg(
        total_debet=('Debet', 'sum'),
        total_kredit=('Kredit', 'sum')
    )
    gl_by_bukti['selisih'] = (gl_by_bukti['total_debet'] - gl_by_bukti['total_kredit']).abs()
    pincang_df = gl_by_bukti[gl_by_bukti['selisih'] > 0.01]

    # ==========================================
    # 3. GENERATE PDF REPORT
    # ==========================================
    
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30
    )
    
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#1A365D'))
    style_subtitle = ParagraphStyle('SubTitleStyle', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#4A5568'))
    style_h2 = ParagraphStyle('Heading2Style', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#2B6CB0'))
    style_normal = ParagraphStyle('NormStyle', parent=styles['Normal'], fontSize=9, leading=12)
    style_bold = ParagraphStyle('BoldStyle', parent=styles['Normal'], fontSize=9, leading=12, fontName='Helvetica-Bold')

    elements = []

    # Header PDF (Juga Mencetak Copyright di Laporan PDF)
    elements.append(Paragraph("Aplikasi Analisis Jurnal & Rekonsiliasi", style_title))
    elements.append(Paragraph("Hak Cipta © 2026 Damianus Libertus. Seluruh Hak Cipta Dilindungi.", style_subtitle))
    elements.append(Paragraph(f"Tanggal Cetak: {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')} WIB", style_subtitle))
    elements.append(Spacer(1, 15))

    # Ringkasan Buku Besar
    elements.append(Paragraph("1. Ringkasan Buku Besar / GL (COA 2040102 - Simpanan)", style_h2))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=10))

    data_gl = [
        [Paragraph("Parameter Buku Besar", style_bold), Paragraph("Nilai (Rp)", style_bold)],
        ["Total Debet (Pengurangan/Penarikan)", f"{gl_debet:,.2f}"],
        ["Total Kredit (Penambahan/Setoran)", f"{gl_kredit:,.2f}"],
        ["Selisih Mutasi Intern GL (Debet vs Kredit)", f"{gl_selisih_internal:,.2f}"]
    ]
    
    t_gl = Table(data_gl, colWidths=[300, 200])
    t_gl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EDF2F7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(t_gl)
    elements.append(Spacer(1, 15))

    # Uji Kesesuaian Subledger vs GL
    elements.append(Paragraph("2. Hasil Uji Kesesuaian Subledger Simpanan vs Buku Besar", style_h2))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=10))

    data_rekon = [
        [Paragraph("Parameter Uji Kesesuaian", style_bold), Paragraph("Subledger (Rp)", style_bold), Paragraph("Buku Besar / GL (Rp)", style_bold), Paragraph("Selisih (Rp)", style_bold)],
        ["Setoran Tabungan (Kredit GL)", f"{sub_setoran:,.2f}", f"{gl_kredit:,.2f}", f"{selisih_setoran:,.2f}"],
        ["Penarikan Tabungan (Debet GL)", f"{sub_penarikan:,.2f}", f"{gl_debet:,.2f}", f"{selisih_penarikan:,.2f}"]
    ]

    t_rekon = Table(data_rekon, colWidths=[180, 110, 110, 100])
    t_rekon.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EDF2F7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(t_rekon)
    elements.append(Spacer(1, 10))

    # Catatan Evaluasi
    status_setoran = "SEIMBANG" if abs(selisih_setoran) < 0.01 else f"TIDAK SEIMBANG (Selisih: Rp {selisih_setoran:,.2f})"
    status_penarikan = "SEIMBANG" if abs(selisih_penarikan) < 0.01 else f"TIDAK SEIMBANG (Selisih: Rp {selisih_penarikan:,.2f})"
    
    txt_eval = f"<b>Evaluasi Rekonsiliasi:</b><br/>" \
               f"• Transaksi Setoran Subledger vs GL: <b>{status_setoran}</b><br/>" \
               f"• Transaksi Penarikan Subledger vs GL: <b>{status_penarikan}</b><br/>" \
               f"• Jurnal Pincang (Unbalanced Voucher di GL): <b>{len(pincang_df)} Nomor Bukti</b>"
    
    elements.append(Paragraph(txt_eval, style_normal))
    elements.append(Spacer(1, 15))

    # Detail Jurnal Pincang (Jika ada)
    if len(pincang_df) > 0:
        elements.append(Paragraph("3. Rincian Jurnal Pincang di Buku Besar", style_h2))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E0'), spaceAfter=10))

        data_pincang = [[Paragraph("No. Bukti", style_bold), Paragraph("Total Debet (Rp)", style_bold), Paragraph("Total Kredit (Rp)", style_bold), Paragraph("Selisih (Rp)", style_bold)]]
        for idx, row in pincang_df.iterrows():
            data_pincang.append([
                str(idx),
                f"{row['total_debet']:,.2f}",
                f"{row['total_kredit']:,.2f}",
                f"{row['selisih']:,.2f}"
            ])

        t_pincang = Table(data_pincang, colWidths=[150, 120, 120, 110])
        t_pincang.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FEB2B2')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(t_pincang)

    # Build PDF
    doc.build(elements)
    print(f"Laporan berhasil dibuat di: {output_pdf_path}")


# ==========================================
# EKSEKUSI PROGRAM
# ==========================================
if __name__ == '__main__':
    file_gl = 'Simp. Harian 773 Des 2025 ok.xls.xlsx'
    file_sub = 'Lap. Transaksi tabungan 773 des 2025 Ok.xls.xlsx'
    file_output = 'Laporan_Analisis_Jurnal_Revisi.pdf'
    
    buat_laporan_rekonsiliasi(file_gl, file_sub, file_output)
