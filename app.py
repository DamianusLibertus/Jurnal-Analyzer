# ==========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Rekonsiliasi
# ==========================================================

import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import datetime
import io

st.title("Aplikasi Analisis Jurnal & Rekonsiliasi Keuangan")

# Widget Upload File Sesuai Interface Asli
uploaded_sub = st.file_uploader("Upload File Buku Besar / Simpanan Harian (Excel)", type=["xls", "xlsx"])
uploaded_gl = st.file_uploader("Upload File Laporan Transaksi / GL (Excel)", type=["xls", "xlsx"])

if uploaded_sub and uploaded_gl:
    # Membaca file langsung dari upload user tanpa path lokal
    df_sub = pd.read_excel(uploaded_sub)
    df_gl = pd.read_excel(uploaded_gl)
    
    sub = df_sub.iloc[8:].copy()
    sub.columns = ['Tgl', 'Kode', 'Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo', 'N1', 'N2', 'N3']
    sub = sub[['Tgl', 'Kode', 'Bukti', 'Uraian', 'Debet', 'Kredit', 'Saldo']].dropna(subset=['Tgl'])
    sub['Debet'] = pd.to_numeric(sub['Debet'], errors='coerce').fillna(0)
    sub['Kredit'] = pd.to_numeric(sub['Kredit'], errors='coerce').fillna(0)
    
    gl = df_gl.iloc[6:].copy()
    gl.columns = ['No', 'Rekening', 'Nama', 'Tgl', 'Bukti', 'KodeTrans', 'Setoran', 'Penarikan']
    gl = gl[['Tgl', 'Bukti', 'Setoran', 'Penarikan']].dropna(subset=['Tgl'])
    gl['Setoran'] = pd.to_numeric(gl['Setoran'], errors='coerce').fillna(0)
    gl['Penarikan'] = pd.to_numeric(gl['Penarikan'], errors='coerce').fillna(0)
    
    total_setoran_nasabah = gl['Setoran'].sum()
    total_kredit_gl = sub['Kredit'].sum()
    total_penarikan_nasabah = gl['Penarikan'].sum()
    total_debet_gl = sub['Debet'].sum()
    
    selisih_setoran = total_kredit_gl - total_setoran_nasabah
    selisih_penarikan = total_debet_gl - total_penarikan_nasabah
    
    st.success("File Berhasil Dimuat & Dianalisis!")
    st.write(f"**Total Setoran Subledger Nasabah:** Rp {total_setoran_nasabah:,.2f}")
    st.write(f"- **Total Kredit Buku Besar (GL):** Rp {total_kredit_gl:,.2f}")
    st.write(f"- **Selisih Setoran:** Rp {selisih_setoran:,.2f}")
    st.write(f"- **Total Penarikan Subledger Nasabah:** Rp {total_penarikan_nasabah:,.2f}")
    st.write(f"- **Total Debet Buku Besar (GL):** Rp {total_debet_gl:,.2f}")
    st.write(f"- **Selisih Penarikan:** Rp {selisih_penarikan:,.2f}")

    def generate_pdf_buffer():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        story = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, leading=18, alignment=1, textColor=colors.HexColor('#1B365D'))
        subtitle_style = ParagraphStyle('SubtitleStyle', parent=styles['Normal'], fontSize=9, leading=12, alignment=1, textColor=colors.HexColor('#555555'))
        section_style = ParagraphStyle('SectionStyle', parent=styles['Heading2'], fontSize=11, leading=15, textColor=colors.HexColor('#1B365D'), spaceBefore=10, spaceAfter=5)
        body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=9, leading=13, textColor=colors.HexColor('#333333'))

        story.append(Paragraph("Aplikasi Analisis Jurnal & Rekonsiliasi Keuangan", title_style))
        story.append(Paragraph(f"Tanggal Cetak: {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')} WIB", subtitle_style))
        story.append(Spacer(1, 12))
        
        story.append(Paragraph("Parameter Uji Kesesuaian (Rekonsiliasi Subledger vs GL)", section_style))
        summary_data = [
            ["Parameter Uji Kesesuaian", "Nilai / Jumlah (Rp)"],
            ["Total Setoran Subledger Nasabah", f"{total_setoran_nasabah:,.2f}"],
            ["Total Kredit Buku Besar (GL)", f"{total_kredit_gl:,.2f}"],
            ["Selisih Setoran", f"{selisih_setoran:,.2f}"],
            ["Total Penarikan Subledger Nasabah", f"{total_penarikan_nasabah:,.2f}"],
            ["Total Debet Buku Besar (GL)", f"{total_debet_gl:,.2f}"],
            ["Selisih Penarikan", f"{selisih_penarikan:,.2f}"]
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
        
        analysis_text = f"Ditemukan selisih setoran sebesar Rp {selisih_setoran:,.2f} dan selisih penarikan sebesar Rp {selisih_penarikan:,.2f} antara laporan subledger nasabah dan buku besar (GL)."
        story.append(Paragraph(analysis_text, body_style))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    pdf_file = generate_pdf_buffer()
    st.download_button(
        label="Download Laporan PDF",
        data=pdf_file,
        file_name="Laporan_Analisis_RAK_Revisi.pdf",
        mime="application/pdf"
    )
else:
    st.info("Silakan upload kedua file Excel di atas untuk memulai analisis.")
