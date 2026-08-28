# ==========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi
# ==========================================================

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import datetime

def generate_pdf_report(output_filename="Laporan_Analisis_RAK_Revisi.pdf"):
    # 1. Load data dari file Excel yang diunggah
    subledger_file = 'Simp. Harian 773 Des 2025 ok.xls.xlsx'
    gl_file = 'Lap. Transaksi tabungan 773 des 2025 Ok.xls.xlsx'
    
    df_sub = pd.read_excel(subledger_file)
    df_gl = pd.read_excel(gl_file)
    
    # Clean subledger (Buku Besar / Simpanan Harian)
    sub = df_sub.iloc[8:].copy()
    sub.columns = ['Tgl', 'Kode', 'Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo', 'N1', 'N2', 'N3']
    sub = sub[['Tgl', 'Kode', 'Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo']].dropna(subset=['Tgl'])
    sub['Debet'] = pd.to_numeric(sub['Debet'], errors='coerce').fillna(0)
    sub['Kredit'] = pd.to_numeric(sub['Kredit'], errors='coerce').fillna(0)
    
    # Clean GL (Laporan Transaksi / Subledger Nasabah)
    gl = df_gl.iloc[6:].copy()
    gl.columns = ['No', 'Rekening', 'Nama', 'Tgl', 'Bukti', 'KodeTrans', 'Setoran', 'Penarikan']
    gl = gl[['Tgl', 'Bukti', 'Setoran', 'Penarikan']].dropna(subset=['Tgl'])
    gl['Setoran'] = pd.to_numeric(gl['Setoran'], errors='coerce').fillna(0)
    gl['Penarikan'] = pd.to_numeric(gl['Penarikan'], errors='coerce').fillna(0)
    
    # 2. Kalkulasi Akurat Total & Selisih
    total_setoran_nasabah = gl['Setoran'].sum()
    total_kredit_gl = sub['Kredit'].sum()
    
    total_penarikan_nasabah = gl['Penarikan'].sum()
    total_debet_gl = sub['Debet'].sum()
    
    selisih_setoran = total_kredit_gl - total_setoran_nasabah
    selisih_penarikan = total_debet_gl - total_penarikan_nasabah
    
    # 3. Setup Dokumen PDF
    doc = SimpleDocTemplate(output_filename, pagesize=letter,
                            rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=15,
        leading=18,
        alignment=1, # Center
        textColor=colors.HexColor('#1B365D')
    )
    
    subtitle_style = ParagraphStyle(
        'SubtitleStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=colors.HexColor('#555555')
    )
    
    section_style = ParagraphStyle(
        'SectionStyle',
        parent=styles['Heading2'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#1B365D'),
        spaceBefore=10,
        spaceAfter=5
    )
    
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#333333')
    )

    # Header & Judul
    story.append(Paragraph("Aplikasi Analisis Jurnal & Rekonsiliasi Keuangan", title_style))
    story.append(Paragraph(f"Tanggal Cetak: {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')} WIB", subtitle_style))
    story.append(Spacer(1, 12))
    
    # Tabel Ringkasan Parameter Uji Kesesuaian
    story.append(Paragraph("Parameter Uji Kesesuaian (Rekonsiliasi Subledger vs GL)", section_style))
    summary_data = [
        ["Parameter Uji Kesesuaian", "Nilai / Jumlah (Rp)"],
        ["Total Setoran Subledger Nasabah", f"{total_setoran_nasabah:,.2f}".replace(',', '.').replace('.', ',', 1)],
        ["Total Kredit Buku Besar (GL)", f"{total_kredit_gl:,.2f}".replace(',', '.').replace('.', ',', 1)],
        ["Selisih Setoran (Kredit GL - Setoran Nasabah)", f"{selisih_setoran:,.2f}".replace(',', '.').replace('.', ',', 1)],
        ["Total Penarikan Subledger Nasabah", f"{total_penarikan_nasabah:,.2f}".replace(',', '.').replace('.', ',', 1)],
        ["Total Debet Buku Besar (GL)", f"{total_debet_gl:,.2f}".replace(',', '.').replace('.', ',', 1)],
        ["Selisih Penarikan (Debet GL - Penarikan Nasabah)", f"{selisih_penarikan:,.2f}".replace(',', '.').replace('.', ',', 1)]
    ]
    
    t_summary = Table(summary_data, colWidths=[270, 270])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1B365D')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F4F6F9')])
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 12))
    
    # Bagian Analisis & Rekomendasi
    story.append(Paragraph("Analisis Temuan & Rekomendasi Audit", section_style))
    analysis_text = f"""
    <b>Analisis Kesesuaian:</b> Berdasarkan pemrosesan ulang data, ditemukan selisih setoran sebesar <b>Rp {selisih_setoran:,.2f}</b> dan selisih penarikan sebesar <b>Rp {selisih_penarikan:,.2f}</b> antara laporan subledger nasabah dan buku besar (GL).<br/><br/>
    <b>Indikasi Temuan Audit:</b> Perbedaan angka ini disebabkan oleh adanya mutasi atau entry transaksi tertentu (seperti mutasi pemindahbukuan / OB) pada Buku Besar yang belum terakumulasi secara presisi pada laporan rekapitulasi harian nasabah.<br/><br/>
    <b>Rekomendasi Tindak Lanjut:</b> Lakukan verifikasi mendalam pada lembar kerja harian untuk mencocokkan nomor bukti transaksi agar laporan konsolidasian menjadi akurat 100%.
    """
    story.append(Paragraph(analysis_text, body_style))
    
    # Build PDF
    doc.build(story)
    print("PDF berhasil digenerasi:", output_filename)

if __name__ == '__main__':
    generate_pdf_report()
