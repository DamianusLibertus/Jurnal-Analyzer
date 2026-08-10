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
import asyncio
from io import BytesIO
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

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
    initial_sidebar_state="expanded",
)

# ---------- Utility Helpers ----------
def to_num(x) -> float:
    if x is None:
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

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def _llm_call(system_message: str, text: str, images_b64=None, timeout: int = 600) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=str(uuid.uuid4()),
        system_message=system_message,
    ).with_model("openai", VISION_MODEL)
    contents = [ImageContent(image_base64=b) for b in (images_b64 or [])]
    msg = UserMessage(text=text, file_contents=contents) if contents else UserMessage(text=text)
    resp = await asyncio.wait_for(chat.send_message(msg), timeout=timeout)
    return resp if isinstance(resp, str) else str(resp)

def llm_call(system_message: str, text: str, images_b64=None, timeout: int = 600) -> str:
    return run_async(_llm_call(system_message, text, images_b64, timeout))

def pdf_to_b64_images(raw_bytes: bytes, max_pages: int = 20):
    import fitz
    out = []
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    for page in doc[:max_pages]:
        pix = page.get_pixmap(dpi=150)
        out.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return out

# ---------- 1. PROMPT AI VISION: Membaca Tabel Sesuai Aslinya ----------
def vision_extract_jurnal(images_b64, mode: str, timeout: int = 600) -> pd.DataFrame:
    system = (
        "Anda adalah pakar OCR Akuntansi presisi tinggi. Tugas Anda membaca tabel jurnal "
        "keuangan dan menyajikannya persis sesuai bentuk laporan aslinya."
    )
    
    prompt = (
        "Ekstrak seluruh baris transaksi dari gambar laporan jurnal ini ke dalam format JSON.\n"
        "ATURAN STRUKTUR PENTING:\n"
        "1. Kolom 'akun': Isi HANYA dengan Uraian / Nama Akun Transaksi yang bersih.\n"
        "   - Hapus Tanggal (misal 01/07/2026) dari nama akun.\n"
        "   - Hapus Kode Ref/Bukti (seperti TAB.002052040102, JU.001, BKK.002) dari nama akun.\n"
        "2. Kolom 'debet': Masukkan angka nominal Debet (tanpa 'Rp', gunakan titik untuk desimal).\n"
        "3. Kolom 'kredit': Masukkan angka nominal Kredit (tanpa 'Rp', gunakan titik untuk desimal).\n"
        "4. Jika salah satu kolom kosong/nihil, isi dengan angka 0.\n"
        "5. Jangan sertakan baris Total, Subtotal, atau Saldo Akhir.\n\n"
        'Balas HANYA JSON valid dengan format persis:\n'
        '{"rows": [{"akun": "Nama Akun Bersih", "debet": 0.0, "kredit": 0.0}]}'
    )
    
    raw = llm_call(system, prompt, images_b64=images_b64, timeout=timeout)
    
    # Parse JSON
    t = raw.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip().strip("```").strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return pd.DataFrame()
    
    try:
        data = json.loads(m.group(0))
        rows = data.get("rows", [])
        df = pd.DataFrame(rows)
        df["debet"] = df["debet"].apply(to_num)
        df["kredit"] = df["kredit"].apply(to_num)
        df.columns = ["Akun", "Debet", "Kredit"]
        return df
    except Exception:
        return pd.DataFrame()

# ---------- 2. HITUNG SELISIH & STATUS ----------
def compute_jurnal(df: pd.DataFrame):
    df = df.copy()
    df["Debet"] = df["Debet"].apply(to_num)
    df["Kredit"] = df["Kredit"].apply(to_num)
    df["Selisih"] = (df["Debet"] - df["Kredit"]).round(2)
    
    total_debet = float(df["Debet"].sum())
    total_kredit = float(df["Kredit"].sum())
    diff = round(total_debet - total_kredit, 2)
    
    totals = {
        "total_debet": total_debet,
        "total_kredit": total_kredit,
        "selisih": diff,
        "balanced": abs(diff) < 0.01
    }
    return df, totals

# ---------- 4 & 5. PROMPT AI AUDITOR: Alasan & Rekomendasi Masukan ----------
def ai_audit_analysis(df: pd.DataFrame, totals: dict) -> str:
    system = "Anda adalah Auditor Keuangan Senior. Berikan analisis audit profesional dalam Bahasa Indonesia."
    
    imbalanced_df = df[df["Selisih"].abs() > 0.001]
    table_sample = imbalanced_df.to_markdown(index=False) if not imbalanced_df.empty else df.head(15).to_markdown(index=False)
    
    prompt = (
        f"DATA RINGKASAN JURNAL:\n"
        f"- Total Debet: {rupiah(totals['total_debet'])}\n"
        f"- Total Kredit: {rupiah(totals['total_kredit'])}\n"
        f"- Total Selisih: {rupiah(totals['selisih'])}\n"
        f"- Status: {'SEIMBANG' if totals['balanced'] else 'TIDAK SEIMBANG'}\n\n"
        f"TABEL TRANSAKSI (FOKUS SELISIH):\n{table_sample}\n\n"
        "BUATKAN LAPORAN AUDIT DENGAN 3 BAGIAN WAJIB BERIKUT:\n"
        "### 1. Rincian Akun Transaksi yang Mengalami Selisih\n"
        "(Sebutkan nama-nama akun beserta nilai selisihnya secara spesifik)\n\n"
        "### 2. Alasan & Penyebab Ketidakseimbangan\n"
        "(Jelaskan secara logis kenapa selisih terjadi, misal: kelalaian input sisi kredit, pergeseran kolom kas/bank, atau transaksi pencairan tak seimbang)\n\n"
        "### 3. Masukan & Rekomendasi Tindakan Koreksi\n"
        "(Berikan langkah konkret perbaikan pembukuan dan draf ayat jurnal penyesuaian/koreksi yang harus dicatat)"
    )
    
    return llm_call(system, prompt)

# ---------- MAIN APP UI ----------
def main():
    st.markdown(f"# 📊 {APP_TITLE}")
    st.caption(f"Dikembangkan oleh {OWNER}")
    st.divider()

    up_files = st.file_uploader("Unggah PDF Jurnal Transaksi Asli", type=["pdf", "png", "jpg"], accept_multiple_files=True)

    if st.button("🚀 Mula-mula Baca & Analisis Dokumen", type="primary", disabled=not up_files):
        all_frames = []
        with st.spinner("Membaca isi tabel & menyesuaikan dengan laporan asli via AI Emergent..."):
            for f in up_files:
                if f.name.endswith(".pdf"):
                    imgs = pdf_to_b64_images(f.getvalue())
                    for img in imgs:
                        sub_df = vision_extract_jurnal([img], "jurnal")
                        if not sub_df.empty:
                            all_frames.append(sub_df)
                else:
                    b64_img = base64.b64encode(f.getvalue()).decode()
                    sub_df = vision_extract_jurnal([b64_img], "jurnal")
                    if not sub_df.empty:
                        all_frames.append(sub_df)
            
            if all_frames:
                st.session_state.df_raw = pd.concat(all_frames, ignore_index=True)
                st.success("Berhasil membaca tabel jurnal secara presisi!")
            else:
                st.error("Gagal membaca dokumen. Pastikan file berisi tabel jurnal yang jelas.")

    if "df_raw" in st.session_state and st.session_state.df_raw is not None:
        st.subheader("① Pratinjau & Koreksi Data Tabel")
        edited_df = st.data_editor(st.session_state.df_raw, num_rows="dynamic", use_container_width=True)

        if st.button("🔒 Kunci Data & Cari Selisih Otomatis", type="primary"):
            computed_df, totals = compute_jurnal(edited_df)
            st.session_state.computed_df = computed_df
            st.session_state.totals = totals
            
            with st.spinner("AI sedang menyusun alasan selisih & masukan koreksi..."):
                st.session_state.audit_reason = ai_audit_analysis(computed_df, totals)
            st.rerun()

    if "computed_df" in st.session_state:
        df = st.session_state.computed_df
        totals = st.session_state.totals

        st.divider()
        st.subheader("② Ringkasan Hasil Analisis Selisih")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Debet", rupiah(totals["total_debet"]))
        c2.metric("Total Kredit", rupiah(totals["total_kredit"]))
        c3.metric("Selisih Total", rupiah(totals["selisih"]))
        c4.metric("Status Jurnal", "SEIMBANG ✅" if totals["balanced"] else "TIDAK SEIMBANG ⚠️")

        st.subheader("③ Tabel Transaksi (Akun Selisih Ditandai Merah)")
        
        # ---------- 3. TANDA MERAH UNTUK AKUN SELISIH ----------
        def highlight_selisih_row(row):
            if abs(row["Selisih"]) > 0.001:
                # Merah muda terang untuk latar, teks merah tua bercetak tebal
                return ['background-color: #FEE2E2; color: #991B1B; font-weight: bold;'] * len(row)
            return [''] * len(row)

        styled_df = df.style.apply(highlight_selisih_row, axis=1).format({
            "Debet": "{:,.2f}",
            "Kredit": "{:,.2f}",
            "Selisih": "{:,.2f}"
        })
        
        st.dataframe(styled_df, use_container_width=True)

        # ---------- 4 & 5. ALASAN DAN REKOMENDASI AI ----------
        st.subheader("④ Alasan Ketidakseimbangan & Masukan Koreksi AI")
        st.markdown(st.session_state.audit_reason)

if __name__ == "__main__":
    main()
