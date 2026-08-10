# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Selisih Laporan
# =========================================================

import os
import re
import io
import json
import uuid
import base64
from io import BytesIO
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

CURRENT_YEAR = datetime.now().year
APP_TITLE = "Aplikasi Analisis Jurnal & Selisih Laporan"
OWNER = "Damianus Libertus"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

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
    if s in ("", "-", "--", "nil", "null", "nan", "none", "."):
        return 0.0
    neg = "(" in s and ")" in s
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[-1]) == 3):
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

# ---------- NORMALISASI TABEL ACCURATE / COOP ----------
STD_COLS = ["KD", "No. Bukti", "Kode Perkiraan", "Nama Perkiraan", "Uraian", "Debet", "Kredit"]

def clean_and_normalize_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Saring kolom & baris agar sesuai dengan struktur jurnal 7 kolom."""
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=STD_COLS)

    df = df_raw.copy()
    
    # Pemetaaan nama kolom otomatis
    col_map = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ["kd", "jenis", "tipe"]: col_map[c] = "KD"
        elif "bukti" in cl or "ref" in cl or "no" == cl: col_map[c] = "No. Bukti"
        elif "kode" in cl or "acc" in cl or "rekening" in cl: col_map[c] = "Kode Perkiraan"
        elif "nama" in cl or "perkiraan" in cl or "akun" in cl: col_map[c] = "Nama Perkiraan"
        elif "uraian" in cl or "keterangan" in cl or "memo" in cl: col_map[c] = "Uraian"
        elif "deb" in cl or "masuk" in cl: col_map[c] = "Debet"
        elif "kred" in cl or "keluar" in cl: col_map[c] = "Kredit"

    df = df.rename(columns=col_map)

    # Pastikan seluruh 7 kolom ada
    for col in STD_COLS:
        if col not in df.columns:
            df[col] = ""

    df = df[STD_COLS].copy()
    
    # Ganti seluruh string "nan", spasi kosong, atau NaN bawaan Pandas menjadi nilai kosong ""
    df = df.replace({'nan': '', 'NaN': '', np.nan: ''})

    # Format Angka
    df["Debet"] = df["Debet"].apply(to_num)
    df["Kredit"] = df["Kredit"].apply(to_num)

    # Buang baris rekap/total/sampah kosong
    def is_valid_row(r):
        str_val = (str(r["KD"]) + str(r["No. Bukti"]) + str(r["Nama Perkiraan"]) + str(r["Uraian"])).lower().replace(" ", "")
        if any(k in str_val for k in ["total", "jumlah", "sanggau", "saldoawal", "saldoakhir", "halaman"]):
            return False
        
        # Harus memiliki angka Debet/Kredit ATAU Nama Perkiraan ATAU No. Bukti
        if r["Debet"] == 0 and r["Kredit"] == 0 and str(r["Nama Perkiraan"]).strip() == "" and str(r["No. Bukti"]).strip() == "":
            return False
        return True

    df = df[df.apply(is_valid_row, axis=1)].reset_index(drop=True)
    return df

# ---------- PROSES PEMBACAAN DOKUMEN (EXCEL, CSV, PDF) ----------
def process_uploaded_file(uploaded_file) -> pd.DataFrame:
    fname = uploaded_file.name.lower()
    file_bytes = uploaded_file.getvalue()

    # 1. BACA FILE EXCEL (.xlsx, .xls)
    if fname.endswith((".xlsx", ".xls")):
        try:
            df_ex = pd.read_excel(BytesIO(file_bytes))
            return clean_and_normalize_df(df_ex)
        except Exception as e:
            st.error(f"Gagal membaca file Excel: {e}")
            return pd.DataFrame(columns=STD_COLS)

    # 2. BACA FILE CSV
    elif fname.endswith(".csv"):
        try:
            df_csv = pd.read_csv(BytesIO(file_bytes))
            return clean_and_normalize_df(df_csv)
        except Exception:
            df_csv = pd.read_csv(BytesIO(file_bytes), sep=";")
            return clean_and_normalize_df(df_csv)

    # 3. BACA FILE PDF
    elif fname.endswith(".pdf"):
        try:
            import pdfplumber
            lines = []
            with pdfplumber.open(BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    txt = page.extract_text() or ""
                    lines.extend(txt.splitlines())

            rows = []
            date_re = re.compile(r"\b\d{1,2}[/\.-]\d{1,2}[/\.-]\d{2,4}\b")
            ref_re = re.compile(r"\b(?:ACC|TAB|JU|OB|COA|BKK|BKM|KK|KM)[.-]?\d[\w.-]*\b", re.I)
            num_re = re.compile(r"\(?-?\d{1,3}(?:\.\d{3})*(?:,\d+)?\)?")

            curr_kd = "JU"
            curr_bukti = ""

            for line in lines:
                low = line.lower()
                if any(k in low for k in ["halaman", "jurnal transaksi", "periode", "total", "jumlah", "dicetak"]):
                    continue

                # Cari nomor bukti
                found_ref = ref_re.findall(line)
                if found_ref:
                    curr_bukti = found_ref[0]

                line_clean = date_re.sub(" ", line)
                line_clean = ref_re.sub(" ", line_clean)

                num_tokens = num_re.findall(line_clean)
                amts = [to_num(m) for m in num_tokens if not (m.isdigit() and 2020 <= int(m) <= 2030)]

                desc = line_clean
                for m in num_tokens:
                    desc = desc.replace(m, " ")
                desc = re.sub(r"\s+", " ", desc).strip(" .-,:|")

                if len(amts) >= 2 and len(desc) > 2:
                    rows.append({
                        "KD": curr_kd,
                        "No. Bukti": curr_bukti,
                        "Kode Perkiraan": "",
                        "Nama Perkiraan": desc[:100],
                        "Uraian": "",
                        "Debet": amts[-2] if len(amts) >= 2 else amts[0],
                        "Kredit": amts[-1] if len(amts) >= 2 else 0.0
                    })

            return clean_and_normalize_df(pd.DataFrame(rows))
        except Exception as e:
            st.error(f"Gagal membaca PDF: {e}")
            return pd.DataFrame(columns=STD_COLS)

    return pd.DataFrame(columns=STD_COLS)

# ---------- HITUNG ANALISIS & DETEKSI SELISIH TRANSAKSI (DENGAN PENGAMAN KOLOM) ----------
def compute_jurnal(df: pd.DataFrame):
    df = df.copy()
    
    # --- PENGAMAN TAMBAHAN: Mencegah KeyError jika kolom wajib terhapus user ---
    required_cols = ["KD", "No. Bukti", "Kode Perkiraan", "Nama Perkiraan", "Uraian", "Debet", "Kredit"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = 0.0 if col in ["Debet", "Kredit"] else ""
    # --------------------------------------------------------------------------

    df["Debet"] = df["Debet"].apply(to_num)
    df["Kredit"] = df["Kredit"].apply(to_num)

    total_debet = float(df["Debet"].sum())
    total_kredit = float(df["Kredit"].sum())
    diff = round(total_debet - total_kredit, 2)

    # Deteksi Selisih Per Nomor Bukti (Voucher / Pasangan Transaksi)
    df["_Bukti_Group"] = df["No. Bukti"].astype(str).replace("", None).ffill().fillna("UNASSIGNED")
    
    # Hitung total per bukti
    group_totals = df.groupby("_Bukti_Group")[["Debet", "Kredit"]].sum()
    group_totals["_Group_Diff"] = (group_totals["Debet"] - group_totals["Kredit"]).round(2)
    
    # Gabungkan status selisih ke dataframe utama
    df["_Selisih_Bukti"] = df["_Bukti_Group"].map(group_totals["_Group_Diff"])
    
    totals = {
        "total_debet": total_debet,
        "total_kredit": total_kredit,
        "selisih": diff,
        "balanced": abs(diff) < 0.01
    }
    return df, totals

# ---------- EKSPOR PDF REPORTLAB ----------
def build_pdf_report(df, totals):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=12*mm, bottomMargin=12*mm, leftMargin=10*mm, rightMargin=10*mm)
    styles = getSampleStyleSheet()
    
    elements = []
    navy = colors.HexColor("#1E3A5F")

    title_style = ParagraphStyle("T1", parent=styles["Title"], fontSize=14, leading=16, textColor=navy, alignment=0)
    sub_style = ParagraphStyle("S1", parent=styles["Normal"], fontSize=8, textColor=colors.gray)
    th_style = ParagraphStyle("TH", parent=styles["Normal"], fontSize=7.5, leading=9, textColor=colors.white, fontName="Helvetica-Bold")
    td_style = ParagraphStyle("TD", parent=styles["Normal"], fontSize=7, leading=8.5)
    td_red = ParagraphStyle("TDR", parent=styles["Normal"], fontSize=7, leading=8.5, textColor=colors.HexColor("#DC2626"), fontName="Helvetica-Bold")

    elements.append(Paragraph(f"<b>{APP_TITLE}</b>", title_style))
    elements.append(Paragraph(f"Pemilik: {OWNER} | Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M WIB')}", sub_style))
    elements.append(Spacer(1, 8))

    # Ringkasan Total
    summary_data = [
        [Paragraph("<b>Total Debet</b>", th_style), Paragraph("<b>Total Kredit</b>", th_style), Paragraph("<b>Selisih Total</b>", th_style), Paragraph("<b>Status Jurnal</b>", th_style)],
        [Paragraph(rupiah(totals["total_debet"]), td_style), Paragraph(rupiah(totals["total_kredit"]), td_style), Paragraph(rupiah(totals["selisih"]), td_style), Paragraph("<b>SEIMBANG</b>" if totals["balanced"] else "<font color='red'><b>TIDAK SEIMBANG</b></font>", td_style)]
    ]
    t_sum = Table(summary_data, colWidths=[48*mm, 48*mm, 48*mm, 46*mm])
    t_sum.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), navy), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1"))]))
    elements.append(t_sum)
    elements.append(Spacer(1, 10))

    # Tabel Rincian Data
    headers = [Paragraph(f"<b>{c}</b>", th_style) for c in STD_COLS]
    rows_table = [headers]

    for _, r in df.iterrows():
        is_bad = abs(r.get("_Selisih_Bukti", 0)) > 0.01
        curr_style = td_red if is_bad else td_style
        
        row_cells = [
            Paragraph(str(r["KD"]), curr_style),
            Paragraph(str(r["No. Bukti"]), curr_style),
            Paragraph(str(r["Kode Perkiraan"]), curr_style),
            Paragraph(str(r["Nama Perkiraan"]), curr_style),
            Paragraph(str(r["Uraian"]), curr_style),
            Paragraph(rupiah(r["Debet"]), curr_style),
            Paragraph(rupiah(r["Kredit"]), curr_style),
        ]
        rows_table.append(row_cells)

    t_detail = Table(rows_table, colWidths=[12*mm, 28*mm, 22*mm, 42*mm, 44*mm, 21*mm, 21*mm], repeatRows=1)
    t_detail.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), navy),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t_detail)

    doc.build(elements)
    return buf.getvalue()

# ---------- ANTARMUKA UTAMA (STREAMLIT) ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    st.caption(f"Dikembangkan oleh {OWNER}")
    st.divider()

    st.subheader("① Unggah Dokumen Laporan (Excel, CSV, PDF)")
    up_files = st.file_uploader(
        "Pilih file Excel (.xlsx / .xls), CSV, atau PDF Jurnal Transaksi",
        type=["xlsx", "xls", "csv", "pdf"],
        accept_multiple_files=True
    )

    if st.button("🚀 Ekstrak & Analisis Otomatis", type="primary", disabled=not up_files):
        all_frames = []
        with st.spinner("Membaca isi tabel & menyesuaikan otomatis..."):
            for f in up_files:
                parsed_df = process_uploaded_file(f)
                if not parsed_df.empty:
                    all_frames.append(parsed_df)

            if all_frames:
                st.session_state.df_raw = pd.concat(all_frames, ignore_index=True)
                st.success("Data berhasil diekstrak dan disesuaikan otomatis!")
            else:
                st.error("Gagal membaca dokumen. Pastikan format tabel memiliki kolom yang sesuai.")

    if "df_raw" in st.session_state and st.session_state.df_raw is not None:
        st.subheader("② Pratinjau Data Tabel Hasil Ekstraksi")

        # Alat Tambah / Hapus Kolom
        with st.expander("🛠️ Panel Alat Pengaturan Kolom Tabel", expanded=False):
            col_a, col_b = st.columns(2)
            with col_a:
                new_col = st.text_input("Nama Kolom Baru:")
                if st.button("➕ Tambah Kolom Baru"):
                    if new_col and new_col not in st.session_state.df_raw.columns:
                        st.session_state.df_raw[new_col] = ""
                        st.rerun()
            with col_b:
                del_col = st.selectbox("Pilih Kolom Dihapus:", st.session_state.df_raw.columns)
                if st.button("🗑️ Hapus Kolom Ini"):
                    if len(st.session_state.df_raw.columns) > 1:
                        st.session_state.df_raw = st.session_state.df_raw.drop(columns=[del_col])
                        st.rerun()

        edited_df = st.data_editor(
            st.session_state.df_raw,
            num_rows="dynamic",
            use_container_width=True,
            key="editor_grid"
        )

        if st.button("🔒 Kunci Data & Cari Selisih Otomatis", type="primary"):
            st.session_state.df_raw = edited_df
            computed_df, totals = compute_jurnal(edited_df)
            st.session_state.computed_df = computed_df
            st.session_state.totals = totals
            st.rerun()

    if "computed_df" in st.session_state:
        df = st.session_state.computed_df
        totals = st.session_state.totals

        st.divider()
        st.subheader("③ Ringkasan Hasil Analisis Selisih")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Debet", rupiah(totals["total_debet"]))
        c2.metric("Total Kredit", rupiah(totals["total_kredit"]))
        c3.metric("Selisih Total", rupiah(totals["selisih"]))
        c4.metric("Status Jurnal", "SEIMBANG ✅" if totals["balanced"] else "TIDAK SEIMBANG ⚠️")

        st.subheader("④ Tabel Transaksi (Hanya Transaksi Selisih Ditandai Merah)")

        # HIGHLIGHTING PRESISI: Hanya tandai merah jika NOMOR BUKTI tersebut tidak seimbang!
        def highlight_unbalanced_voucher(row):
            if abs(row.get("_Selisih_Bukti", 0)) > 0.01:
                return ['background-color: #FEE2E2; color: #991B1B; font-weight: bold;'] * len(row)
            return [''] * len(row)

        display_cols = [c for c in df.columns if not c.startswith("_")]
        styled_df = df[display_cols].style.apply(
            highlight_unbalanced_voucher, axis=1
        ).format({
            "Debet": "{:,.2f}",
            "Kredit": "{:,.2f}"
        })

        st.dataframe(styled_df, use_container_width=True)

        # ---------- FITUR EKSPOR PDF & EXCEL ----------
        st.divider()
        st.subheader("⑤ Cetak & Download Laporan")
        e1, e2 = st.columns(2)

        with e1:
            try:
                pdf_bytes = build_pdf_report(df, totals)
                st.download_button(
                    "🖨️ Cetak / Download Laporan PDF",
                    data=pdf_bytes,
                    file_name=f"Laporan_Selisih_Jurnal_{datetime.now():%Y%m%d_%H%M}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as ex:
                st.error(f"Gagal memuat PDF: {ex}")

        with e2:
            buf_excel = BytesIO()
            with pd.ExcelWriter(buf_excel, engine="openpyxl") as writer:
                df[display_cols].to_excel(writer, index=False, sheet_name="Hasil_Analisis")
            st.download_button(
                "📊 Download Laporan Excel (.xlsx)",
                data=buf_excel.getvalue(),
                file_name=f"Analisis_Jurnal_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

if __name__ == "__main__":
    main()
