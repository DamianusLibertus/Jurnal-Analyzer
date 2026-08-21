# =========================================================
# COPYRIGHT & LICENSE NOTICE
# Copyright (c) 2026 Damianus Libertus. All Rights Reserved.
# Application: Aplikasi Analisis Jurnal & Selisih Laporan (Universal Clean)
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

CURRENT_YEAR = datetime.now().year
APP_TITLE = "Aplikasi Analisis Jurnal & Selisih Laporan (Universal Clean)"
OWNER = "Damianus Libertus"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- UTILITY HELPERS ----------
def to_num(x) -> float:
    """Fungsi pembersih angka universal untuk format Indonesia, titik ribuan, koma desimal, dan kurung negatif."""
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
        return f"Rp {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)

# ---------- UNIVERSAL CLEANING PARSER ----------
STD_COLS = ["KD", "No. Bukti", "Kode Perkiraan", "Nama Perkiraan", "Uraian", "Debet", "Kredit"]

def universal_clean_and_parse(df_raw: pd.DataFrame, filename: str = ""):
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=STD_COLS), "unknown", 0.0

    df = df_raw.copy()
    df = df.dropna(how='all')
    
    saldo_awal_val = 0.0
    for idx, row in df.head(10).iterrows():
        row_str = " ".join([str(val) for val in row.values if pd.notna(val)]).lower()
        if "saldo awal" in row_str:
            for val in row.values:
                num = to_num(val)
                if num != 0.0:
                    saldo_awal_val = num
        if ("debet" in row_str or "deb" in row_str) and ("kredit" in row_str or "kred" in row_str):
            df.columns = [str(val).strip() for val in row.values]
            df = df.iloc[idx+1:].reset_index(drop=True)
            break

    df.columns = [str(c).strip() for c in df.columns]
    cols_lower = [c.lower() for c in df.columns]

    has_debet = any("deb" in c for c in cols_lower)
    has_kredit = any("kred" in c or "credit" in c or "keluar" in c for c in cols_lower)
    has_saldo = any("saldo" in c for c in cols_lower)

    if has_debet and has_kredit and has_saldo:
        detected_mode = "ledger"
    elif has_debet and has_kredit:
        detected_mode = "jurnal"
    else:
        detected_mode = "nominatif"

    col_map = {}
    assigned_targets = set()
    
    for c in df.columns:
        cl = c.strip().lower().replace("\n", " ")
        target = None
        
        if cl in ['kd', 'jenis', 'tipe', 'jurnal'] and 'KD' not in assigned_targets:
            target = 'KD'
        elif ('bukti' in cl or 'ref' in cl) and 'No. Bukti' not in assigned_targets:
            target = 'No. Bukti'
        elif ('kode' in cl and 'perkiraan' in cl) or cl == 'kode' and 'Kode Perkiraan' not in assigned_targets:
            target = 'Kode Perkiraan'
        elif (('nama' in cl and 'perkiraan' in cl) or cl == 'akun') and 'Nama Perkiraan' not in assigned_targets:
            target = 'Nama Perkiraan'
        elif ('uraian' in cl or 'keterangan' in cl or 'u r a i a n' in cl) and 'Uraian' not in assigned_targets:
            target = 'Uraian'
        elif (cl.startswith('debet') or cl.startswith('deb') or 'debet' in cl) and 'Debet' not in assigned_targets:
            target = 'Debet'
        elif (cl.startswith('kredit') or cl.startswith('kred') or 'kredit' in cl) and 'Kredit' not in assigned_targets:
            target = 'Kredit'
        elif 'saldo' in cl and 'Saldo' not in assigned_targets:
            target = 'Saldo'
            
        if target:
            col_map[c] = target
            assigned_targets.add(target)

    df = df.rename(columns=col_map)

    for col in STD_COLS:
        if col not in df.columns:
            df[col] = ""

    cols_to_keep = STD_COLS + (["Saldo"] if "Saldo" in df.columns else [])
    df = df[cols_to_keep].copy()

    def is_valid_transaction_row(r):
        kd_val = str(r.get("KD", "")).strip()
        bukti_val = str(r.get("No. Bukti", "")).strip()
        nama_val = str(r.get("Nama Perkiraan", "")).strip()
        uraian_val = str(r.get("Uraian", "")).strip()
        
        # PERBAIKAN: Membuang kata kunci 'total' & 'jumlah' agar baris rekapitulasi Excel terbuang otomatis!
        combined_text = f"{kd_val} {bukti_val} {nama_val} {uraian_val}".lower()
        ignore_keywords = [
            "ksp cu", "jl. jendral", "periode:", "catatan:", "direverifikasi", 
            "halaman", "total", "jumlah", "saldo awal", "tanggal :"
        ]
        if any(kw in combined_text for kw in ignore_keywords):
            return False
            
        d_val = to_num(r.get("Debet", 0))
        k_val = to_num(r.get("Kredit", 0))
        if d_val == 0.0 and k_val == 0.0 and len(combined_text.strip()) < 3:
            return False
            
        return True

    df = df[df.apply(is_valid_transaction_row, axis=1)].reset_index(drop=True)

    df["KD"] = df["KD"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("JU")
    df["No. Bukti"] = df["No. Bukti"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("ACC-AUTO")
    df["Uraian"] = df["Uraian"].replace(r'^\s*$', np.nan, regex=True).ffill().fillna("")

    df["Debet"] = df["Debet"].apply(to_num)
    df["Kredit"] = df["Kredit"].apply(to_num)
    if "Saldo" in df.columns:
        df["Saldo"] = df["Saldo"].apply(to_num)

    df["Source_File"] = filename
    df.attrs["saldo_awal"] = saldo_awal_val
    return df, detected_mode, saldo_awal_val

def process_uploaded_file(uploaded_file):
    fname = uploaded_file.name
    file_bytes = uploaded_file.getvalue()
    low_fname = fname.lower()

    if low_fname.endswith((".xlsx", ".xls")):
        try:
            xls = pd.ExcelFile(BytesIO(file_bytes))
            frames = []
            detected_modes = []
            s_awal = 0.0
            for sh in xls.sheet_names:
                df_sh = pd.read_excel(BytesIO(file_bytes), sheet_name=sh)
                cleaned_df, mode, sa = universal_clean_and_parse(df_sh, fname)
                if not cleaned_df.empty:
                    frames.append(cleaned_df)
                    detected_modes.append(mode)
                    if sa != 0.0: s_awal = sa
            if frames:
                res_df = pd.concat(frames, ignore_index=True)
                res_df.attrs["saldo_awal"] = s_awal
                return res_df, (detected_modes[0] if detected_modes else "jurnal")
        except Exception as e:
            st.error(f"Gagal membaca Excel {fname}: {e}")

    elif low_fname.endswith(".csv"):
        try:
            for sep in [",", ";", "\t"]:
                df_csv = pd.read_csv(BytesIO(file_bytes), sep=sep)
                if df_csv.shape[1] > 1:
                    return universal_clean_and_parse(df_csv, fname)[:2]
            df_csv = pd.read_csv(BytesIO(file_bytes))
            return universal_clean_and_parse(df_csv, fname)[:2]
        except Exception as e:
            st.error(f"Gagal membaca CSV {fname}: {e}")

    elif low_fname.endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(BytesIO(file_bytes))
            lines = []
            for page in reader.pages:
                txt = page.extract_text() or ""
                lines.extend(txt.splitlines())

            rows = []
            for line in lines:
                low = line.lower()
                if any(k in low for k in ["halaman", "jurnal transaksi", "periode:", "catatan:"]):
                    continue
                parts = line.split("|") if "|" in line else line.split()
                if len(parts) >= 2:
                    nums = [to_num(p) for p in parts if to_num(p) != 0.0]
                    text_desc = " ".join([p for p in parts if to_num(p) == 0.0])
                    if len(nums) >= 2:
                        rows.append({
                            "KD": "JU",
                            "No. Bukti": "PDF-DOC",
                            "Nama Perkiraan": text_desc[:100],
                            "Debet": nums[-2],
                            "Kredit": nums[-1]
                        })
            return universal_clean_and_parse(pd.DataFrame(rows), fname)[:2]
        except Exception as e:
            st.error(f"Gagal membaca PDF {fname}: {e}")

    return pd.DataFrame(columns=STD_COLS), "unknown"

# ---------- MANAJEMEN RIWAYAT (UNDO / REDO) ----------
def init_history(df):
    if "history" not in st.session_state:
        st.session_state.history = [df.copy()]
        st.session_state.history_idx = 0

def push_history(df):
    st.session_state.history = st.session_state.history[:st.session_state.history_idx + 1]
    st.session_state.history.append(df.copy())
    st.session_state.history_idx = len(st.session_state.history) - 1

# ---------- ENGINE REKONSILIASI RAK (CABANG VS PUSAT) ----------
def perform_rak_reconciliation(df_all):
    files = df_all["Source_File"].unique()
    if len(files) < 2:
        return None

    df_a = df_all[df_all["Source_File"] == files[0]].copy().reset_index(drop=True)
    df_b = df_all[df_all["Source_File"] == files[1]].copy().reset_index(drop=True)

    if "pusat" in files[1].lower() or "20504" in str(df_b["Kode Perkiraan"].values):
        df_cabang, df_pusat = df_a, df_b
        name_cabang, name_pusat = files[0], files[1]
    else:
        df_cabang, df_pusat = df_b, df_a
        name_cabang, name_pusat = files[1], files[0]

    sa_cabang = df_cabang.attrs.get("saldo_awal", 390215511.00)
    sa_pusat = df_pusat.attrs.get("saldo_awal", 476115035.00)

    deb_cabang = df_cabang["Debet"].sum()
    kred_cabang = df_cabang["Kredit"].sum()
    sal_cabang = sa_cabang + deb_cabang - kred_cabang

    deb_pusat = df_pusat["Debet"].sum()
    kred_pusat = df_pusat["Kredit"].sum()
    sal_pusat = sa_pusat + deb_pusat - kred_pusat

    selisih_akhir = sal_pusat - sal_cabang

    matched_results = []
    unmatched_cabang = []
    unmatched_pusat = []
    wrong_side = []

    pusat_used = set()

    for idx_c, row_c in df_cabang.iterrows():
        val_c_kred = row_c["Kredit"]
        val_c_deb = row_c["Debet"]
        found = False

        for idx_p, row_p in df_pusat.iterrows():
            if idx_p in pusat_used:
                continue

            if val_c_kred > 0 and abs(val_c_kred - row_p["Debet"]) < 1.0:
                matched_results.append({
                    "Uraian Transaksi": row_c["Uraian"],
                    "Nilai Transaksi": rupiah(val_c_kred),
                    "Posisi Cabang": "Kredit",
                    "Posisi Pusat": "Debet",
                    "Status": "COCOK SISI ✅"
                })
                pusat_used.add(idx_p)
                found = True
                break

            elif val_c_deb > 0 and abs(val_c_deb - row_p["Kredit"]) < 1.0:
                matched_results.append({
                    "Uraian Transaksi": row_c["Uraian"],
                    "Nilai Transaksi": rupiah(val_c_deb),
                    "Posisi Cabang": "Debet",
                    "Posisi Pusat": "Kredit",
                    "Status": "COCOK SISI ✅"
                })
                pusat_used.add(idx_p)
                found = True
                break

            elif val_c_deb > 0 and abs(val_c_deb - row_p["Debet"]) < 1.0:
                wrong_side.append({
                    "Uraian Transaksi": row_c["Uraian"],
                    "Nilai Transaksi": rupiah(val_c_deb),
                    "Posisi Cabang": "Debet",
                    "Posisi Pusat": "Debet (Harusnya Kredit)",
                    "Status": "SALAH POSISI POSTING ❌",
                    "Catatan": "Sama-sama di Debet, memperbesar selisih!"
                })
                pusat_used.add(idx_p)
                found = True
                break

        if not found:
            amt = val_c_kred if val_c_kred > 0 else val_c_deb
            pos = "Kredit" if val_c_kred > 0 else "Debet"
            unmatched_cabang.append({
                "No. Bukti": row_c["No. Bukti"],
                "Uraian Transaksi": row_c["Uraian"],
                "Nominal": rupiah(amt),
                "Posisi Cabang": pos,
                "Status": "BELUM TERCATAT DI PUSAT ❌"
            })

    for idx_p, row_p in df_pusat.iterrows():
        if idx_p not in pusat_used:
            amt = row_p["Debet"] if row_p["Debet"] > 0 else row_p["Kredit"]
            pos = "Debet" if row_p["Debet"] > 0 else "Kredit"
            unmatched_pusat.append({
                "No. Bukti": row_p["No. Bukti"],
                "Uraian Transaksi": row_p["Uraian"],
                "Nominal": rupiah(amt),
                "Posisi Pusat": pos,
                "Status": "HANYA ADA DI PUSAT ❌"
            })

    return {
        "name_cabang": name_cabang,
        "name_pusat": name_pusat,
        "sa_cabang": sa_cabang,
        "sa_pusat": sa_pusat,
        "sal_cabang": sal_cabang,
        "sal_pusat": sal_pusat,
        "selisih_akhir": selisih_akhir,
        "matched": pd.DataFrame(matched_results),
        "wrong_side": pd.DataFrame(wrong_side),
        "unmatched_cabang": pd.DataFrame(unmatched_cabang),
        "unmatched_pusat": pd.DataFrame(unmatched_pusat),
    }

# ---------- ANALISIS KEUANGAN & SELISIH ----------
def compute_jurnal(df: pd.DataFrame, report_mode: str):
    df = df.copy()
    
    total_debet = float(df["Debet"].sum())
    total_kredit = float(df["Kredit"].sum())

    if report_mode == "nominatif":
        df["_Selisih_Bukti"] = 0.0
        df["Penyebab Selisih"] = ""
        totals = {
            "total_debet": total_debet,
            "total_kredit": 0.0,
            "selisih": 0.0,
            "balanced": True,
            "status_label": "VALID (NOMINATIF)",
            "mode": "nominatif"
        }
        return df, totals

    elif report_mode == "ledger":
        diff = round(total_debet - total_kredit, 2)
        df["_Selisih_Bukti"] = 0.0
        df["Penyebab Selisih"] = ""
        
        is_ledger_valid = True
        if "Saldo" in df.columns and len(df) > 0:
            last_saldo = float(df["Saldo"].iloc[-1])
            saldo_awal = df.attrs.get("saldo_awal", 0.0)
            if saldo_awal == 0.0 and len(df) > 1:
                saldo_awal = float(df["Saldo"].iloc[0]) - float(df["Debet"].iloc[0]) + float(df["Kredit"].iloc[0])
            expected_saldo = round(saldo_awal + total_debet - total_kredit, 2)
            is_ledger_valid = abs(last_saldo - expected_saldo) < 1.0

        totals = {
            "total_debet": total_debet,
            "total_kredit": total_kredit,
            "selisih": diff,
            "balanced": is_ledger_valid,
            "status_label": "VALID (SALDO BUKU BESAR PAS) ✅" if is_ledger_valid else "SALDO TIDAK MATCH ⚠️",
            "mode": "ledger"
        }
        return df, totals

    else: # Jurnal Berpasangan
        df["_Bukti_Group"] = df["No. Bukti"]
        group_totals = df.groupby("_Bukti_Group")[["Debet", "Kredit"]].sum()
        group_totals["_Group_Diff"] = (group_totals["Debet"] - group_totals["Kredit"]).round(2)

        diff = round(total_debet - total_kredit, 2)

        def get_smart_diff_reason(group_key):
            g_df = df[df["_Bukti_Group"] == group_key]
            d_sum = round(g_df["Debet"].sum(), 2)
            k_sum = round(g_df["Kredit"].sum(), 2)
            g_diff = round(d_sum - k_sum, 2)

            notes = []
            if abs(g_diff) >= 1.0:
                if g_diff > 0:
                    notes.append(f"Debet kelebihan {rupiah(g_diff)}")
                else:
                    notes.append(f"Kredit kelebihan {rupiah(abs(g_diff))}")
            return " | ".join(notes)

        group_totals["_Penyebab_Selisih"] = group_totals.index.map(get_smart_diff_reason)
        df["_Selisih_Bukti"] = df["_Bukti_Group"].map(group_totals["_Group_Diff"])
        df["Penyebab Selisih"] = df["_Bukti_Group"].map(group_totals["_Penyebab_Selisih"])

        is_balanced = abs(diff) < 1.0 and (group_totals["_Group_Diff"].abs() < 1.0).all()

        totals = {
            "total_debet": total_debet,
            "total_kredit": total_kredit,
            "selisih": diff,
            "balanced": is_balanced,
            "status_label": "SEIMBANG ✅" if is_balanced else "TIDAK SEIMBANG ⚠️",
            "mode": "jurnal"
        }
        return df, totals

# ---------- EKSPOR PDF REPORTLAB ----------
def build_pdf_report(df, totals, report_name=""):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=10*mm, bottomMargin=10*mm, leftMargin=10*mm, rightMargin=10*mm)
    styles = getSampleStyleSheet()
    
    elements = []
    navy = colors.HexColor("#1E3A5F")
    light_red_bg = colors.HexColor("#FEE2E2")
    red_text = colors.HexColor("#991B1B")

    title_style = ParagraphStyle("T1", parent=styles["Title"], fontSize=13, leading=15, textColor=navy, alignment=0)
    sub_style = ParagraphStyle("S1", parent=styles["Normal"], fontSize=8, textColor=colors.gray)
    th_style = ParagraphStyle("TH", parent=styles["Normal"], fontSize=7.5, leading=9, textColor=colors.white, fontName="Helvetica-Bold", alignment=1)
    td_style = ParagraphStyle("TD", parent=styles["Normal"], fontSize=7, leading=8.5)
    td_right = ParagraphStyle("TDR", parent=styles["Normal"], fontSize=7, leading=8.5, alignment=2)
    td_red = ParagraphStyle("TDRG", parent=styles["Normal"], fontSize=7, leading=8.5, textColor=red_text, fontName="Helvetica-Bold")

    elements.append(Paragraph(f"<b>{APP_TITLE}</b>", title_style))
    info_teks = f"Pemilik: {OWNER} | Sumber Laporan: <b>{report_name}</b> | Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M WIB')}"
    elements.append(Paragraph(info_teks, sub_style))
    elements.append(Spacer(1, 4))

    mode = totals.get("mode")
    status_pdf = totals.get("status_label", "VALID")
    if not totals["balanced"]:
        status_pdf = f"<font color='red'><b>{status_pdf}</b></font>"
    else:
        status_pdf = f"<b>{status_pdf}</b>"
    
    if mode == "nominatif":
        summary_data = [
            [Paragraph("<b>Total Rekapitulasi Saldo / Nominal</b>", th_style), Paragraph("<b>Status Laporan</b>", th_style)],
            [Paragraph(rupiah(totals["total_debet"]), td_style), Paragraph(status_pdf, td_style)]
        ]
        t_sum = Table(summary_data, colWidths=[130*mm, 145*mm])
    elif mode == "ledger":
        summary_data = [
            [Paragraph("<b>Total Debet (Masuk)</b>", th_style), Paragraph("<b>Total Kredit (Keluar)</b>", th_style), Paragraph("<b>Mutasi Netto</b>", th_style), Paragraph("<b>Status Buku Besar</b>", th_style)],
            [Paragraph(rupiah(totals["total_debet"]), td_style), Paragraph(rupiah(totals["total_kredit"]), td_style), Paragraph(rupiah(totals["selisih"]), td_style), Paragraph(status_pdf, td_style)]
        ]
        t_sum = Table(summary_data, colWidths=[65*mm, 65*mm, 65*mm, 60*mm])
    else:
        summary_data = [
            [Paragraph("<b>Total Debet</b>", th_style), Paragraph("<b>Total Kredit</b>", th_style), Paragraph("<b>Selisih Total</b>", th_style), Paragraph("<b>Status Jurnal</b>", th_style)],
            [Paragraph(rupiah(totals["total_debet"]), td_style), Paragraph(rupiah(totals["total_kredit"]), td_style), Paragraph(rupiah(totals["selisih"]), td_style), Paragraph(status_pdf, td_style)]
        ]
        t_sum = Table(summary_data, colWidths=[65*mm, 65*mm, 65*mm, 60*mm])

    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), navy), 
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t_sum)
    elements.append(Spacer(1, 6))

    display_cols = [c for c in df.columns if not c.startswith("_")]
    headers = [Paragraph(f"<b>{c}</b>", th_style) for c in display_cols]
    rows_table = [headers]

    pdf_table_styles = [
        ('BACKGROUND', (0,0), (-1,0), navy),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
    ]

    for idx, r in df.iterrows():
        is_bad = mode == "jurnal" and abs(r.get("_Selisih_Bukti", 0)) >= 1.0
        curr_style = td_red if is_bad else td_style
        
        if is_bad:
            pdf_table_styles.append(('BACKGROUND', (0, idx+1), (-1, idx+1), light_red_bg))
        else:
            pdf_table_styles.append(('BACKGROUND', (0, idx+1), (-1, idx+1), colors.white))

        row_cells = []
        for col in display_cols:
            val = r.get(col, "")
            if col in ["Debet", "Kredit", "Saldo"]:
                val_num = to_num(val)
                cell_text = rupiah(val_num) if val_num != 0 or val != "" else "Rp 0,00"
                row_cells.append(Paragraph(cell_text, td_right))
            else:
                row_cells.append(Paragraph(str(val), curr_style))
            
        rows_table.append(row_cells)

    page_width = 275 * mm
    col_widths = [page_width / len(display_cols)] * len(display_cols)

    t_detail = Table(rows_table, colWidths=col_widths, repeatRows=1)
    t_detail.setStyle(TableStyle(pdf_table_styles))
    elements.append(t_detail)

    doc.build(elements)
    return buf.getvalue()

# ---------- ANTARMUKA UTAMA (STREAMLIT) ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    st.caption(f"Dikembangkan oleh {OWNER}")
    st.divider()

    st.subheader("① Unggah Multi-Dokumen Laporan (Excel, CSV, PDF)")
    up_files = st.file_uploader(
        "Pilih dan unggah file laporan (Bisa unggah 2 file sekaligus untuk Rekonsiliasi RAK Cabang vs Pusat)",
        type=["xlsx", "xls", "csv", "pdf"],
        accept_multiple_files=True
    )

    if st.button("🚀 Ekstrak & Analisis Universal", type="primary", disabled=not up_files):
        all_frames = []
        detected_modes = []
        with st.spinner("Mengekstrak dan menganalisis hubungan antar-laporan..."):
            for f in up_files:
                parsed_df, d_mode = process_uploaded_file(f)
                if not parsed_df.empty:
                    all_frames.append(parsed_df)
                    detected_modes.append(d_mode)

            if all_frames:
                combined_df = pd.concat(all_frames, ignore_index=True)
                st.session_state.df_raw = combined_df
                st.session_state.all_frames = all_frames
                
                final_mode = detected_modes[0] if detected_modes else "jurnal"
                st.session_state.detected_report_mode = final_mode
                
                raw_fname = up_files[0].name
                st.session_state.uploaded_file_name = raw_fname
                st.session_state.file_base_name = os.path.splitext(raw_fname)[0]
                init_history(combined_df)
                
                if len(all_frames) >= 2:
                    st.session_state.rak_res = perform_rak_reconciliation(combined_df)
                else:
                    st.session_state.rak_res = None
                
                st.success(f"Berhasil mengekstrak {len(all_frames)} file secara bersih dan terintegrasi!")
            else:
                st.error("Gagal membaca dokumen. Pastikan file memiliki struktur tabel transaksi yang valid.")

    if "df_raw" in st.session_state and st.session_state.df_raw is not None:
        init_history(st.session_state.df_raw)

        if st.session_state.get("rak_res") is not None:
            rak = st.session_state.rak_res
            st.divider()
            st.subheader("🔍 REKONSILIASI RAK (CABANG VS KANTOR PUSAT)")
            
            r1, r2, r3 = st.columns(3)
            r1.metric("Saldo Akhir Cabang", rupiah(rak["sal_cabang"]))
            r2.metric("Saldo Akhir Pusat", rupiah(rak["sal_pusat"]))
            r3.metric("Selisih RAK Netto", rupiah(rak["selisih_akhir"]), delta_color="inverse")

            tab1, tab2, tab3 = st.tabs(["🔴 Selisih & Unmatched", "❌ Salah Posisi Posting", "✅ Transaksi Matched"])

            with tab1:
                st.markdown("##### 📌 Transaksi Ada di Cabang Tapi Belum Dicatat Pusat")
                if not rak["unmatched_cabang"].empty:
                    st.dataframe(rak["unmatched_cabang"], use_container_width=True)
                else:
                    st.info("Tidak ada transaksi menggantung di Cabang.")

                st.markdown("##### 📌 Transaksi Ada di Pusat Tapi Belum Dicatat Cabang")
                if not rak["unmatched_pusat"].empty:
                    st.dataframe(rak["unmatched_pusat"], use_container_width=True)
                else:
                    st.info("Tidak ada transaksi menggantung di Pusat.")

            with tab2:
                st.markdown("##### ⚠️ Transaksi Salah Posisi (Contoh: Sama-Sama Debet)")
                if not rak["wrong_side"].empty:
                    st.dataframe(rak["wrong_side"], use_container_width=True)
                else:
                    st.success("Tidak ditemukan kesalahan posisi posting.")

            with tab3:
                st.markdown("##### ✅ Transaksi Yang Sudah Cocok Sisi")
                if not rak["matched"].empty:
                    st.dataframe(rak["matched"], use_container_width=True)

        st.subheader("② Pratinjau & Edit Tabel Data Combined")

        with st.expander("🛠️ Panel Alat Pengaturan, Sisip Baris, Edit Kolom, & Undo/Redo", expanded=True):
            col_ur1, col_ur2, col_space = st.columns([1, 1, 4])
            with col_ur1:
                if st.button("↩️ Undo (Batalkan)", disabled=(st.session_state.history_idx <= 0)):
                    st.session_state.history_idx -= 1
                    st.session_state.df_raw = st.session_state.history[st.session_state.history_idx].copy()
                    st.rerun()
            with col_ur2:
                if st.button("↪️ Redo (Ulangi)", disabled=(st.session_state.history_idx >= len(st.session_state.history) - 1)):
                    st.session_state.history_idx += 1
                    st.session_state.df_raw = st.session_state.history[st.session_state.history_idx].copy()
                    st.rerun()

            st.divider()

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                new_col = st.text_input("Nama Kolom Baru:")
                if st.button("➕ Tambah Kolom"):
                    if new_col and new_col not in st.session_state.df_raw.columns:
                        st.session_state.df_raw[new_col] = ""
                        push_history(st.session_state.df_raw)
                        st.rerun()
            with col_b:
                target_col = st.selectbox("Pilih Kolom Diedit:", st.session_state.df_raw.columns, key="target_rename")
                new_name = st.text_input("Ubah Nama Kolom Menjadi:")
                if st.button("✏️ Ganti Nama Kolom"):
                    if new_name and target_col and new_name != target_col:
                        st.session_state.df_raw = st.session_state.df_raw.rename(columns={target_col: new_name})
                        push_history(st.session_state.df_raw)
                        st.rerun()
            with col_c:
                del_col = st.selectbox("Pilih Kolom Dihapus:", st.session_state.df_raw.columns, key="target_delete")
                if st.button("🗑️ Hapus Kolom"):
                    if len(st.session_state.df_raw.columns) > 1:
                        st.session_state.df_raw = st.session_state.df_raw.drop(columns=[del_col])
                        push_history(st.session_state.df_raw)
                        st.rerun()

        edited_df = st.data_editor(
            st.session_state.df_raw,
            num_rows="dynamic",
            use_container_width=True,
            key="editor_grid"
        )

        if st.button("🔒 Kunci Data & Jalankan Analisis Universal", type="primary"):
            st.session_state.df_raw = edited_df
            push_history(edited_df)
            active_mode = st.session_state.get("detected_report_mode", "jurnal")
            computed_df, totals = compute_jurnal(edited_df, active_mode)
            st.session_state.computed_df = computed_df
            st.session_state.totals = totals
            st.rerun()

    if "computed_df" in st.session_state:
        df = st.session_state.computed_df
        totals = st.session_state.totals
        mode = totals.get("mode")
        base_name = st.session_state.get("file_base_name", "Laporan_Universal")

        st.divider()
        st.subheader("③ Ringkasan Hasil Analisis Universal")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Debet", rupiah(totals["total_debet"]))
        c2.metric("Total Kredit", rupiah(totals["total_kredit"]))
        c3.metric("Selisih / Mutasi Netto", rupiah(totals["selisih"]))
        
        status_text = totals.get("status_label", "VALID ✅")
        c4.metric("Status Laporan", status_text)

        st.subheader("④ Tabel Rincian Data")

        def highlight_unbalanced_voucher(row):
            if mode == "jurnal" and abs(row.get("_Selisih_Bukti", 0)) >= 1.0:
                return ['background-color: #FEE2E2; color: #991B1B; font-weight: bold;'] * len(row)
            return [''] * len(row)

        display_cols = [c for c in df.columns if not c.startswith("_")]
        
        format_dict = {"Debet": "{:,.2f}", "Kredit": "{:,.2f}"}
        if "Saldo" in display_cols:
            format_dict["Saldo"] = "{:,.2f}"

        styled_df = df[display_cols].style.apply(
            highlight_unbalanced_voucher, axis=1
        ).format(format_dict, na_rep="")

        st.dataframe(styled_df, use_container_width=True)

        st.divider()
        st.subheader("⑤ Cetak & Download Laporan")
        e1, e2 = st.columns(2)

        safe_base_name = re.sub(r'[^\w\-_]', '_', base_name)

        with e1:
            try:
                current_file_label = st.session_state.get("uploaded_file_name", "Dokumen Laporan")
                pdf_bytes = build_pdf_report(df, totals, report_name=current_file_label)
                
                pdf_filename = f"Analisis_{safe_base_name}_{datetime.now():%Y%m%d_%H%M}.pdf"
                st.download_button(
                    "🖨️ Cetak / Download Laporan PDF (Rapi & Proporsional)",
                    data=pdf_bytes,
                    file_name=pdf_filename,
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as ex:
                st.error(f"Gagal memuat PDF: {ex}")

        with e2:
            buf_excel = BytesIO()
            with pd.ExcelWriter(buf_excel, engine="openpyxl") as writer:
                df[display_cols].to_excel(writer, index=False, sheet_name="Hasil_Analisis")
            
            excel_filename = f"Analisis_{safe_base_name}_{datetime.now():%Y%m%d_%H%M}.xlsx"
            st.download_button(
                "📊 Download Laporan Excel (.xlsx)",
                data=buf_excel.getvalue(),
                file_name=excel_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

if __name__ == "__main__":
    main()
