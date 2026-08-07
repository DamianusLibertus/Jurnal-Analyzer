for h in hist:
            ts = h.get("timestamp", "")
            try:
                date_s = datetime.fromisoformat(ts).strftime("%d %b %H:%M")
            except Exception:
                date_s = ts[:16].replace("T", " ")
            src = h.get("source_label") or h.get("mode", "")
            short = src if len(src) <= 15 else src[:13] + "…"
            label = f"{short} ({date_s})"
            item_col, del_col = st.columns([0.75, 0.25])
            with item_col:
                if st.button(label, key=f"hist_{h.get('id')}", use_container_width=True):
                    # Muat kembali dari riwayat
                    saved_df = pd.DataFrame(h.get("rows", []))
                    st.session_state.df = normalize_df(saved_df, h.get("mode", "jurnal"))
                    st.session_state.analysis = h.get("analysis", "")
                    st.rerun()
            with del_col:
                if st.button("❌", key=f"del_{h.get('id')}", use_container_width=True):
                    delete_history(h.get("id"))
                    st.rerun()

    # Hero Banner
    st.markdown(
        f"""
        <div class='app-hero'>
            <div class='gold-pill'>DIBUAT OLEH {OWNER.upper()}</div>
            <h1>{APP_TITLE}</h1>
            <p>Ekstraksi cerdas, audit otomatis, dan deteksi selisih pembukuan keuangan secara instan & akurat.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Input Section
    st.markdown("### 📥 1. Masukkan Dokumen / Data")
    tab_upload, tab_paste, tab_manual = st.tabs(["📁 Unggah File (PDF / Excel / Gambar)", "📋 Tempel Teks Mentah", "✏️ Input Manual"])

    raw_files = []
    with tab_upload:
        uploaded_files = st.file_uploader(
            "Unggah dokumen akuntansi (mendukung banyak file sekaligus)",
            type=["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )
        if uploaded_files:
            for uf in uploaded_files:
                ext = uf.name.split(".")[-1].lower()
                kind = "excel" if ext in ("xlsx", "xls") else ("csv" if ext == "csv" else ("pdf" if ext == "pdf" else "image"))
                raw_files.append({"name": uf.name, "kind": kind, "data": uf.getvalue()})

    with tab_paste:
        pasted_text = st.text_area(
            "Tempel teks laporan keuangan atau jurnal di sini:",
            placeholder="Contoh:\nKas di Bank\t15000000\t0\nUtang Usaha\t0\t15000000",
            height=150,
        )
        if pasted_text.strip():
            raw_files.append({"name": "Teks Tempelan", "kind": "excel", "data": to_csv_bytes(parse_text_rows(pasted_text, mode))})

    with tab_manual:
        st.caption("Masukkan data langsung melalui tabel di bawah.")
        if mode == "jurnal":
            default_manual = pd.DataFrame([
                {"Akun": "Kas", "Debet": 5000000.0, "Kredit": 0.0},
                {"Akun": "Pendapatan Jasa", "Debet": 0.0, "Kredit": 5000000.0},
            ])
        else:
            default_manual = pd.DataFrame([
                {"Item": "Biaya Operasional", "Target": 10000000.0, "Realisasi": 9500000.0},
            ])
        manual_df = st.data_editor(default_manual, num_rows="dynamic", use_container_width=True, key="manual_editor")
        if st.button("Gunakan Data Manual", type="primary"):
            st.session_state.df = normalize_df(manual_df, mode)
            st.session_state.analysis = None
            st.success("Data manual berhasil dimuat!")
            st.rerun()

    # Tombol Ekstraksi & Proses Utama
    if raw_files:
        if st.button("🚀 Proses & Analisis Dokumen", type="primary", use_container_width=True):
            status_box = st.status("Sedang memproses dokumen...", expanded=True)
            def progress_cb(curr, total, name):
                status_box.update(label=f"Memproses file {curr}/{total}: {name}", state="running")
            
            combined_df, msgs = process_files(raw_files, mode, progress_cb=progress_cb)
            status_box.update(label="Pemrosesan selesai!", state="complete", expanded=False)

            for lvl, text in msgs:
                if lvl == "ok":
                    st.success(text)
                elif lvl == "warn":
                    st.warning(text)
                else:
                    st.error(text)

            if combined_df is not None and not combined_df.empty:
                cleaned_df = clean_journal_data(combined_df) if mode == "jurnal" else combined_df
                st.session_state.df = cleaned_df
                st.session_state.analysis = None
                st.rerun()

    # Hasil Analisis & Tampilan Data
    if st.session_state.get("df") is not None:
        df_current = st.session_state.df
        st.divider()
        st.markdown("### 📊 2. Hasil Ekstraksi & Analisis Selisih")

        processed_df, totals, imbalanced = compute(df_current, mode)

        # Metrik Ringkasan
        col1, col2, col3, col4 = st.columns(4)
        if mode == "jurnal":
            with col1:
                st.metric("Total Debet", rupiah(totals["total_debet"]))
            with col2:
                st.metric("Total Kredit", rupiah(totals["total_kredit"]))
            with col3:
                st.metric("Selisih (D - K)", rupiah(totals["selisih"]), delta_color="inverse")
            with col4:
                status_text = "SEIMBANG ✅" if totals["balanced"] else "TIDAK SEIMBANG ❌"
                st.metric("Status Pembukuan", status_text)
        else:
            with col1:
                st.metric("Total Target", rupiah(totals["total_target"]))
            with col2:
                st.metric("Total Realisasi", rupiah(totals["total_realisasi"]))
            with col3:
                st.metric("Selisih (R - T)", rupiah(totals["selisih"]))
            with col4:
                st.metric("Status Deviasi", "Terdeteksi" if not totals["balanced"] else "Sesuai Target")

        st.markdown("#### Tabel Rincian Data")
        edited_df = st.data_editor(processed_df, use_container_width=True, key="result_editor")

        # Tombol Hitung Ulang jika diedit
        if st.button("🔄 Perbarui Perhitungan"):
            st.session_state.df = normalize_df(edited_df, mode)
            st.rerun()

        # Tombol Analisis AI
        st.divider()
        st.markdown("### 🤖 3. Penjelasan & Rekomendasi Audit AI")
        if st.session_state.get("analysis") is None:
            if st.button("🧠 Jalankan Analisis & Audit AI", type="primary"):
                with st.spinner("AI sedang menganalisis selisih dan menyusun rekomendasi..."):
                    analysis_result = ai_analysis(processed_df, totals, imbalanced, mode)
                    st.session_state.analysis = analysis_result
                    
                    # Simpan ke riwayat MongoDB
                    record = {
                        "id": str(uuid.uuid4()),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "mode": mode,
                        "source_label": f"Analisis {mode.capitalize()}",
                        "rows": processed_df.to_dict(orient="records"),
                        "analysis": analysis_result,
                    }
                    save_history(record)
                    st.rerun()
        else:
            st.markdown(st.session_state.analysis)
            if st.button("🔄 Buat Ulang Analisis AI"):
                with st.spinner("Menyusun ulang analisis..."):
                    st.session_state.analysis = ai_analysis(processed_df, totals, imbalanced, mode)
                    st.rerun()

        # Ekspor Data
        st.divider()
        st.markdown("### 💾 4. Ekspor Laporan")
        ex_col1, ex_col2, ex_col3 = st.columns(3)
        
        with ex_col1:
            excel_data = to_excel_bytes(processed_df)
            st.download_button(
                "📥 Unduh Format Excel (.xlsx)",
                data=excel_data,
                file_name=f"analisis_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with ex_col2:
            csv_data = to_csv_bytes(processed_df)
            st.download_button(
                "📥 Unduh Format CSV",
                data=csv_data,
                file_name=f"analisis_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with ex_col3:
            try:
                pdf_data = build_pdf(
                    processed_df, totals, imbalanced,
                    st.session_state.get("analysis", ""), mode
                )
                st.download_button(
                    "📄 Unduh Laporan PDF Resmi",
                    data=pdf_data,
                    file_name=f"laporan_audit_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Gagal menghasilkan PDF: {friendly_error(e)}")

    # Footer
    st.markdown(
        f"""
        <div class='app-footer'>
            {APP_TITLE} &bull; Dibuat & Dimiliki oleh <b>{OWNER}</b> &bull; &copy; {CURRENT_YEAR} All Rights Reserved.
        </div>
        """,
        unsafe_allow_html=True,
    )

if __name__ == "__main__":
    main()
