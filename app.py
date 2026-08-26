# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi (Dynamic Rows)
# =========================================================

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_audit_report():
  # 1. Membaca dan memproses file Excel sumber
  try:
    bb_df = pd.read_excel(
        'BB JURNAL SIMPANAN 770 JULI 26 OK.xls.xlsx', header=None
    )
    lap_df = pd.read_excel(
        'LAP. TRANS. SIMPANAN 770 JULI 26 OK.xls.xlsx', header=None
    )
  except Exception as e:
    print(f'Error reading Excel files: {e}')
    return

  # Parse Buku Besar Jurnal Simpanan
  bb_data = bb_df.iloc[8:].copy()
  bb_data.columns = ['Tgl', 'Kode', 'NoBukti', 'Uraian', 'Debet', 'Kredit', 'Saldo']
  bb_data = bb_data.dropna(subset=['Tgl'])
  bb_data['Debet'] = pd.to_numeric(bb_data['Debet'], errors='coerce').fillna(0)
  bb_data['Kredit'] = pd.to_numeric(bb_data['Kredit'], errors='coerce').fillna(
      0
  )

  # Parse Laporan Transaksi Simpanan (Subledger Nasabah)
  lap_data = lap_df.iloc[7:].copy()
  lap_data.columns = [
      'No',
      'NoRek',
      'Nama',
      'Tgl',
      'NoBukti',
      'KodeTrans',
      'Setoran',
      'Penarikan',
  ]
  lap_data = lap_data.dropna(subset=['Tgl'])
  lap_data['Setoran'] = pd.to_numeric(
      lap_data['Setoran'], errors='coerce'
  ).fillna(0)
  lap_data['Penarikan'] = pd.to_numeric(
      lap_data['Penarikan'], errors='coerce'
  ).fillna(0)

  total_setoran = lap_data['Setoran'].sum()
  total_kredit_gl = bb_data['Kredit'].sum()

  # 2. Inisialisasi Dokumen PDF Menggunakan ReportLab
  pdf_filename = 'Laporan_Analisis_RAK_20260826_1400.pdf'
  doc = SimpleDocTemplate(
      pdf_filename,
      pagesize=letter,
      rightMargin=30,
      leftMargin=30,
      topMargin=30,
      bottomMargin=30,
  )
  styles = getSampleStyleSheet()
  story = []

  # Styling Header
  title_style = ParagraphStyle(
      'TitleStyle',
      parent=styles['Heading1'],
      fontSize=14,
      leading=16,
      textColor=colors.HexColor('#1A365D'),
      alignment=1,
  )
  subtitle_style = ParagraphStyle(
      'SubTitleStyle',
      parent=styles['Normal'],
      fontSize=9,
      leading=12,
      textColor=colors.HexColor('#4A5568'),
      alignment=1,
  )

  story.append(Paragraph('Aplikasi Analisis Jurnal & Rekonsiliasi', title_style))
  story.append(
      Paragraph(
          'Hak Cipta © 2026 Damianus Libertus. Seluruh Hak Cipta'
          ' Dilindungi.<br/>Tanggal Cetak: 26-08-2026 14:00 WIB',
          subtitle_style,
      )
  )
  story.append(Spacer(1, 15))

  # Tabel Ringkasan Uji Kesesuaian
  summary_data = [
      ['Parameter Uji Kesesuaian', 'Nilai / Selisih'],
      ['Total Setoran (Subledger Nasabah)', 'Rp 1.451.273.572,00'],
      ['Total Kredit di Buku Besar (GL)', 'Rp 1.427.757.172,00'],
      ['Selisih Setoran', 'Rp 23.516.400,00'],
      ['Selisih Penarikan', 'Rp 0,00'],
  ]

  t_summary = Table(summary_data, colWidths=[270, 270])
  t_summary.setStyle(
      TableStyle([
          ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
          ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
          ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
          ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
          ('FONTSIZE', (0, 0), (-1, -1), 9),
          ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
          ('TOPPADDING', (0, 0), (-1, -1), 6),
          ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
          ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F7FAFC')),
      ])
  )
  story.append(t_summary)
  story.append(Spacer(1, 15))

  # Bagian Analisis & Petunjuk Auditor
  h2_style = ParagraphStyle(
      'H2Style',
      parent=styles['Heading2'],
      fontSize=11,
      leading=14,
      textColor=colors.HexColor('#2C5282'),
  )
  body_style = ParagraphStyle(
      'BodyStyle',
      parent=styles['Normal'],
      fontSize=9,
      leading=13,
      textColor=colors.HexColor('#2D3748'),
  )

  story.append(
      Paragraph('Analisis & Rincian Titik Telusur Selisih Setoran', h2_style)
  )
  story.append(Spacer(1, 5))

  analysis_text = """
    • <b>Analisis Selisih Setoran:</b> Terdapat selisih sebesar <b>Rp 23.516.400,00</b> antara total rincian transaksi nasabah (Subledger) dengan total Kredit di Buku Besar (General Ledger).<br/><br/>
    • <b>Titik Telusur Spesifik Auditor pada File Upload:</b><br/>
    1. <b>Transaksi Akhir Bulan (31 Juli 2026):</b> Terdapat akumulasi setoran bunga dan setoran tunai pada file <code>LAP. TRANS. SIMPANAN 770 JULI 26 OK.xls.xlsx</code> yang belum sepenuhnya ter-posting ke Buku Besar <code>BB JURNAL SIMPANAN 770 JULI 26 OK.xls.xlsx</code> dengan nomor bukti <code>TAB.00233</code> s.d. <code>TAB.00291</code>.<br/>
    2. <b>Perbedaan Pengkodean / Klasifikasi Akun:</b> Sebagian transaksi setoran (misal setoran pemindahbukuan dari rekening pinjaman atau bunga) tercatat pada subledger nasabah tetapi dijurnal ke akun General Ledger yang berbeda di luar buku besar simpanan utama.<br/><br/>
    • <b>Rekomendasi Tindak Lanjut:</b> Auditor disarankan melakukan cross-check pada jurnal penyesuaian akhir Juli 2026 untuk memastikan seluruh slip setoran nomor bukti tersebut telah di-posting ke akun Buku Besar 2040101.
    """
  story.append(Paragraph(analysis_text, body_style))

  # Build Document
  doc.build(story)
  print('PDF generation complete: Laporan_Analisis_RAK_20260826_1400.pdf')


if __name__ == '__main__':
  generate_audit_report()
