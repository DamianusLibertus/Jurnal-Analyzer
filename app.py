# ==============================================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Selisih Laporan
# ==============================================================================

import os
import re
import io
import json
import uuid
import base64
import asyncio
from io import BytesIO
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# ReportLab Imports untuk PDF
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

load_dotenv()

# ----------- Konfigurasi & Konstanta -----------
CURRENT_YEAR = datetime.now().year
APP_TITLE = "Aplikasi Analisis Jurnal & Selisih Laporan"
OWNER = "Damianus Libertus"
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
VISION_MODEL = "gpt-5.4"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------- CSS Custom (Penghitam Teks & Perbaikan Metric) -----------
st.markdown("""
<style>
/* Mengatur latar belakang kartu metric */
div[data-testid="stMetric"] {
    background-color: #ffffff !important;
    padding: 12px 16px !important;
    border-radius: 8px !important;
    border: 1px solid #cbd5e1 !important;
}

/* Memaksa TEKS KETERANGAN / LABEL metric jadi HITAM PEKAT */
div[data-testid="stMetricLabel"] *, 
div[data-testid="stMetricLabel"] label, 
div[data-testid="stMetricLabel"] p {
    color: #0f172a !important;
    font-weight: 700 !important;
    font-size: 14px !important;
    opacity: 1 !important;
}

/* Memaksa TEKS ANGKA / VALUE metric jadi HITAM GELAP */
div[data-testid="stMetricValue"] *, 
div[data-testid="stMetricValue"] div {
    color: #0f172a !important;
    font-weight: 800 !important;
}
</style>
""", unsafe_allow_html=True)


# ----------- Fungsi Format Helper -----------
def rupiah(val):
    try:
        val = float(val)
        return f"Rp {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"Rp {val}"


# ----------- Fungsi PDF Builder Rapi -----------
def build_pdf(analysis_record: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    story = []
    styles = getSampleStyleSheet()

    # Styles Dokumen
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=12
    )
    meta_style = ParagraphStyle(
        'MetaText',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569')
    )
    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=14,
        spaceAfter=8
    )
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155')
    )
    callout_text_style = ParagraphStyle(
        'CalloutText',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor('#0F172A')
    )

    # Header Dokumen
    story.append(Paragraph("<b>LAPORAN HASIL ANALISIS AUDIT JURNAL</b>", title_style))
    
    ts = analysis_record.get("timestamp", "")
    mode = analysis_record.get("mode", "jurnal").upper()
    filename = analysis_record.get("filename", "-")
    
    meta_html = f"""
    <b>Tanggal Analisis:</b> {ts}<br/>
    <b>Mode Analisis:</b> {mode}<br/>
    <b>Nama File:</b> {filename}
    """
    story.append(Paragraph(meta_html, meta_style))
    story.append(Spacer(1, 12))

    # Ringkasan Angka Utama
    totals = analysis_record.get("totals", {})
    story.append(Paragraph("<b>1. Ringkasan Angka</b>", section_heading))
    
    if mode.lower() == "jurnal":
        summary_data = [
            [Paragraph("<b>Total Debet</b>", body_style), Paragraph(rupiah(totals.get("total_debet", 0)), body_style)],
            [Paragraph("<b>Total Kredit</b>", body_style), Paragraph(rupiah(totals.get("total_kredit", 0)), body_style)],
            [Paragraph("<b>Selisih (D-K)</b>", body_style), Paragraph(rupiah(totals.get("selisih", 0)), body_style)],
            [Paragraph("<b>Status</b>", body_style), Paragraph("SEIMBANG ✅" if totals.get("balanced") else "TIDAK SEIMBANG ⚠️", body_style)]
        ]
    else:
        summary_data = [
            [Paragraph("<b>Total Target</b>", body_style), Paragraph(rupiah(totals.get("total_target", 0)), body_style)],
            [Paragraph("<b>Total Realisasi</b>", body_style), Paragraph(rupiah(totals.get("total_realisasi", 0)), body_style)],
            [Paragraph("<b>Selisih (R-T)</b>", body_style), Paragraph(rupiah(totals.get("selisih", 0)), body_style)]
        ]

    t_summary = Table(summary_data, colWidths=[150, 370])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 14))

    # Callout Box: Penjelasan & Analisis AI
    explanation = analysis_record.get("explanation", "").strip()
    if explanation:
        story.append(Paragraph("<b>2. Penjelasan & Analisis Audit</b>", section_heading))
        
        exp_para = Paragraph(explanation.replace('\n', '<br/>'), callout_text_style)
        
        callout_table = Table([[exp_para]], colWidths=[520])
        callout_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
            ('LINELEFT', (0, 0), (0, 0), 4, colors.HexColor('#2563EB')),
            ('PADDING', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(callout_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ----------- UI Utama Aplikasi -----------
def main():
    st.title(f"📊 {APP_TITLE}")
    st.caption(f"Dikembangkan oleh {OWNER} © {CURRENT_YEAR}")

    # Bagian input file dan proses data Anda...
    # (Logika pemrosesan file Excel/CSV tetap berjalan seperti biasa)

    if "analysis" in st.session_state and st.session_state.analysis:
        res = st.session_state.analysis
        rmode = res["mode"]
        totals = res["totals"]

        st.subheader("③ Hasil Analisis & Selisih")

        if rmode == "jurnal":
            r1c1, r1c2 = st.columns(2)
            r1c1.metric("Total Debet", rupiah(totals.get("total_debet", 0)))
            r1c2.metric("Total Kredit", rupiah(totals.get("total_kredit", 0)))

            r2c1, r2c2 = st.columns(2)
            r2c1.metric("Selisih (D-K)", rupiah(totals.get("selisih", 0)))
            r2c2.metric("Status", "SEIMBANG ✅" if totals.get("balanced") else "TIDAK SEIMBANG ⚠️")

            if not totals.get("balanced"):
                st.error(f"⚠️ Jurnal TIDAK SEIMBANG. Selisih Debet-Kredit sebesar {rupiah(totals.get('selisih', 0))}.")
            else:
                st.success("✅ Jurnal SEIMBANG — Total Debet = Total Kredit.")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Target", rupiah(totals.get("total_target", 0)))
            m2.metric("Total Realisasi", rupiah(totals.get("total_realisasi", 0)))
            m3.metric("Selisih (R-T)", rupiah(totals.get("selisih", 0)))

        # Tombol Unduh PDF Rapi
        pdf_bytes = build_pdf(res)
        st.download_button(
            label="📥 Unduh Laporan Audit (PDF)",
            data=pdf_bytes,
            file_name=f"Laporan_Audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf"
        )


if __name__ == "__main__":
    main()
