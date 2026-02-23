"""
Session detail view — the main workspace for a single filing session.

Tabs:
  1. Documents   — upload PDFs (saved to disk immediately, no parsing)
  2. Compute     — parse queued files + run tax computation
  3. Results     — 1040 / IT-201 summary + estimated tax
  4. Generate    — download filing package ZIP
"""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import streamlit as st

from pfile.models.session import FilingSession
from pfile.session.store import SessionStore
from pfile.ui import uploads
from pfile.ui.state import get_store

# ── Entry point ───────────────────────────────────────────────────────────────

def render(session_id: str) -> None:
    store = get_store()
    try:
        session = store.load(session_id)
    except Exception as exc:
        st.error(f"Could not load session: {exc}")
        return

    st.title(f"📄 {session.display_name} — {session.tax_year}")
    st.caption(
        f"Filing status: **{session.filing_status.value.replace('_', ' ').title()}** · "
        f"Status: **{session.status.value.title()}** · ID: `{session.id}`"
    )

    tab_docs, tab_compute, tab_results, tab_generate = st.tabs([
        "📎 Documents", "🧮 Compute", "📊 Results", "📦 Generate"
    ])

    with tab_docs:
        _render_documents(session, store)

    with tab_compute:
        _render_compute(session, store)

    with tab_results:
        _render_results(session)

    with tab_generate:
        _render_generate(session, store)


# ── Tab: Documents ────────────────────────────────────────────────────────────

def _render_documents(session: FilingSession, store: SessionStore) -> None:
    sid = session.id

    st.subheader("Upload Tax Documents")
    st.info(
        "Drop your PDFs here — W-2, 1099-INT/DIV/B/R, K-1 (1065/1120S), SSA-1099, "
        "Fidelity consolidated 1099. Files are saved instantly; pFile will parse them "
        "when you run **Compute**.",
        icon="ℹ️",
    )

    if session.is_mfj:
        filer_choice = st.radio("Documents for", ["Primary", "Spouse"], horizontal=True)
        filer = "primary" if filer_choice == "Primary" else "spouse"
    else:
        filer = "primary"

    # ── Upload widget — just saves bytes, no parsing ──────────────────────────
    uploaded = st.file_uploader(
        "Drop PDFs here",
        type="pdf",
        accept_multiple_files=True,
        key=f"uploader_{sid}_{filer}",
        label_visibility="collapsed",
    )

    if uploaded:
        saved = []
        for f in uploaded:
            data = f.read()
            if data:
                uploads.save_upload(sid, filer, f.name, data)
                saved.append(f.name)
        if saved:
            names = ", ".join(f"`{n}`" for n in saved)
            st.success(f"Saved {len(saved)} file(s): {names} — they'll be parsed when you run Compute.")

    # ── Queue overview ────────────────────────────────────────────────────────
    st.divider()

    primary_queue = uploads.list_uploads(sid, "primary")
    spouse_queue = uploads.list_uploads(sid, "spouse") if session.is_mfj else []

    _render_queue("Primary", primary_queue, sid, "primary")
    if session.is_mfj:
        _render_queue("Spouse", spouse_queue, sid, "spouse")

    # ── Already-parsed documents ──────────────────────────────────────────────
    if session.primary_documents or session.spouse_documents:
        st.divider()
        st.subheader("Parsed Documents")
        _render_parsed_summary(session)


def _render_queue(label: str, queue: list[Path], session_id: str, filer: str) -> None:
    if not queue:
        st.caption(f"**{label}**: no files queued.")
        return

    st.markdown(f"**{label}** — {len(queue)} file(s) pending parse")
    for path in queue:
        c1, c2 = st.columns([7, 1])
        with c1:
            size_kb = path.stat().st_size // 1024
            st.markdown(f"📄 `{path.name}` &nbsp; <span style='color:grey'>{size_kb} KB</span>", unsafe_allow_html=True)
        with c2:
            if st.button("✕", key=f"rm_{session_id}_{filer}_{path.name}", help="Remove"):
                uploads.remove_upload(session_id, filer, path.name)
                st.rerun()


def _render_parsed_summary(session: FilingSession) -> None:
    def _show(label: str, ds):
        if ds is None:
            return
        rows = []
        for w in ds.w2s:
            rows.append(("W-2", w.employer.name, f"${w.box1_wages:,.2f}"))
        for f in ds.f1099_ints:
            rows.append(("1099-INT", f.payer.name, f"${f.box1_interest_income:,.2f}"))
        for f in ds.f1099_divs:
            rows.append(("1099-DIV", f.payer.name, f"${f.box1a_total_ordinary_dividends:,.2f}"))
        for f in ds.f1099_bs:
            amt = f.aggregate_proceeds or sum(t.proceeds for t in f.transactions)
            rows.append(("1099-B", f.payer.name, f"${amt:,.2f} proceeds"))
        for f in ds.f1099_rs:
            rows.append(("1099-R", f.payer.name, f"${f.box1_gross_distribution:,.2f}"))
        for f in ds.ssa_1099s:
            rows.append(("SSA-1099", "Social Security Admin", f"${f.box3_benefits_paid:,.2f}"))
        for k in ds.k1_1065s:
            rows.append(("K-1 (1065)", k.partnership.name, f"${k.box1_ordinary_income:,.2f} ordinary"))
        for k in ds.k1_1120ss:
            rows.append(("K-1 (1120S)", k.corporation.name, f"${k.box1_ordinary_income:,.2f} ordinary"))
        if rows:
            st.markdown(f"**{label}**")
            st.table({
                "Type": [r[0] for r in rows],
                "Payer / Employer": [r[1] for r in rows],
                "Key Amount": [r[2] for r in rows],
            })
        else:
            st.caption(f"{label}: no documents parsed yet.")

    _show("Primary", session.primary_documents)
    if session.is_mfj:
        _show("Spouse", session.spouse_documents)


def _doc_summary(doc) -> str:
    """Return a short human-readable description of a parsed document."""
    from pfile.models.documents import F1099_B, F1099_DIV, F1099_INT, F1099_R, K1_1065, K1_1120S, SSA_1099, W2
    try:
        if isinstance(doc, W2):
            return f"W-2 · {doc.employer.name} · ${doc.box1_wages:,.0f} wages"
        if isinstance(doc, F1099_INT):
            return f"1099-INT · {doc.payer.name} · ${doc.box1_interest_income:,.2f}"
        if isinstance(doc, F1099_DIV):
            return f"1099-DIV · {doc.payer.name} · ${doc.box1a_total_ordinary_dividends:,.2f} ord div"
        if isinstance(doc, F1099_B):
            proceeds = doc.aggregate_proceeds or sum(t.proceeds for t in doc.transactions)
            return f"1099-B · {doc.payer.name} · ${proceeds:,.2f} proceeds"
        if isinstance(doc, F1099_R):
            return f"1099-R · {doc.payer.name} · ${doc.box1_gross_distribution:,.2f}"
        if isinstance(doc, SSA_1099):
            return f"SSA-1099 · ${doc.box3_benefits_paid:,.2f} benefits"
        if isinstance(doc, K1_1065):
            return f"K-1 (1065) · {doc.partnership.name} · ${doc.box1_ordinary_income:,.2f}"
        if isinstance(doc, K1_1120S):
            return f"K-1 (1120S) · {doc.corporation.name} · ${doc.box1_ordinary_income:,.2f}"
    except Exception:
        pass
    return type(doc).__name__


def _attach(doc_set, doc):
    """Append a parsed document to the correct DocumentSet list."""
    from pfile.models.documents import F1099_B, F1099_DIV, F1099_INT, F1099_R, K1_1065, K1_1120S, SSA_1099, W2

    d = doc_set.model_copy(deep=True)
    if isinstance(doc, W2):
        d.w2s.append(doc)
    elif isinstance(doc, K1_1065):
        d.k1_1065s.append(doc)
    elif isinstance(doc, K1_1120S):
        d.k1_1120ss.append(doc)
    elif isinstance(doc, F1099_INT):
        d.f1099_ints.append(doc)
    elif isinstance(doc, F1099_DIV):
        d.f1099_divs.append(doc)
    elif isinstance(doc, F1099_B):
        d.f1099_bs.append(doc)
    elif isinstance(doc, F1099_R):
        d.f1099_rs.append(doc)
    elif isinstance(doc, SSA_1099):
        d.ssa_1099s.append(doc)
    return d


# ── Tab: Compute ──────────────────────────────────────────────────────────────

def _render_compute(session: FilingSession, store: SessionStore) -> None:
    sid = session.id

    # Overrides
    with st.expander("Estimated payments & withholding overrides", expanded=False):
        with st.form("overrides_form"):
            c1, c2 = st.columns(2)
            with c1:
                est_paid = st.number_input(
                    "Federal estimated tax paid ($)",
                    value=float(session.estimated_tax_paid or 0),
                    min_value=0.0, step=100.0,
                )
            with c2:
                other_wh = st.number_input(
                    "Other federal withholding ($)",
                    value=float(session.other_withholding or 0),
                    min_value=0.0, step=100.0,
                )
            if st.form_submit_button("Save overrides"):
                session.estimated_tax_paid = Decimal(str(est_paid))
                session.other_withholding = Decimal(str(other_wh))
                store.save(session)
                st.success("Saved.")
                st.rerun()

    st.divider()

    # Queue status banner
    primary_q = uploads.list_uploads(sid, "primary")
    spouse_q = uploads.list_uploads(sid, "spouse") if session.is_mfj else []
    total_queued = len(primary_q) + len(spouse_q)

    # ── Queue table ───────────────────────────────────────────────────────────
    if total_queued:
        all_queued = (
            [(p, "Primary") for p in primary_q] +
            [(p, "Spouse")  for p in spouse_q]
        )
        st.markdown(f"**{total_queued} file(s) ready to parse:**")
        st.dataframe(
            {
                "File": [p.name for p, _ in all_queued],
                "Person": [person for _, person in all_queued],
                "Size": [f"{p.stat().st_size // 1024} KB" for p, _ in all_queued],
            },
            use_container_width=True,
            hide_index=True,
        )
    elif not (session.primary_documents and session.primary_documents.all_documents()):
        st.warning("No documents uploaded yet. Go to the **Documents** tab to add PDFs.", icon="⚠️")

    col_run, col_year = st.columns([2, 1])
    with col_year:
        compute_year = st.selectbox("Tax year", [2025, 2024, 2023], index=0)
    with col_run:
        st.write("")
        run_clicked = st.button("▶ Parse & Compute", type="primary", use_container_width=True)

    if not run_clicked:
        return

    from pfile.models.session import DocumentSet
    from pfile.parsers.dispatcher import UnknownDocumentError
    from pfile.parsers.dispatcher import parse as dispatcher_parse

    parse_errors: list[str] = []

    # ── Step 1: Parse queued PDFs file-by-file with live status ──────────────
    if primary_q or spouse_q:
        all_files = (
            [(p, "primary", session.primary or session.spouse) for p in primary_q] +
            [(p, "spouse",  session.spouse) for p in spouse_q]
        )

        results_rows: list[dict] = []   # accumulates rows for the live results table
        results_placeholder = st.empty()

        with st.status("Parsing documents…", expanded=True) as parse_status:
            for path, filer, profile in all_files:
                person_label = "Primary" if filer == "primary" else "Spouse"
                st.write(f"⏳ **{path.name}** ({person_label})…")

                row: dict = {"File": path.name, "Person": person_label, "Type": "…", "Key Info": ""}
                try:
                    docs = dispatcher_parse(path)
                    doc_labels = []
                    doc_set = (
                        session.primary_documents if filer == "primary" else session.spouse_documents
                    ) or DocumentSet()
                    for doc in docs:
                        doc_set = _attach(doc_set, doc)
                        doc_labels.append(_doc_summary(doc))
                    if filer == "primary":
                        session.primary_documents = doc_set
                    else:
                        session.spouse_documents = doc_set
                    row["Type"] = " + ".join(type(d).__name__ for d in docs)
                    row["Key Info"] = "  |  ".join(doc_labels)
                    row["Status"] = "✅"
                except UnknownDocumentError as e:
                    parse_errors.append(f"**{path.name}**: {e}")
                    row["Type"] = "Unknown"
                    row["Status"] = "⚠️"
                except Exception as e:
                    parse_errors.append(f"**{path.name}**: {e}")
                    row["Type"] = "Error"
                    row["Status"] = "❌"

                results_rows.append(row)
                results_placeholder.dataframe(results_rows, use_container_width=True, hide_index=True)

            label = f"Parsed {len(all_files)} file(s)"
            if parse_errors:
                label += f" — {len(parse_errors)} error(s)"
            parse_status.update(
                label=label,
                state="complete" if not parse_errors else "error",
                expanded=True,
            )

        for e in parse_errors:
            st.warning(e)

    # ── Step 2: Run tax engine ────────────────────────────────────────────────
    with st.spinner("Computing federal and NY returns…"):
        try:
            from pfile.compute.engine import compute_federal_return
            from pfile.compute.state.engine_ny import compute_ny_return
            from pfile.models.session import SessionStatus

            federal = compute_federal_return(session, year=int(compute_year))
            session.computed_federal = federal

            if session.needs_ny:
                ny = compute_ny_return(session, federal, year=int(compute_year))
                session.computed_ny = ny
            else:
                session.computed_ny = None

            session.status = SessionStatus.COMPUTED
            store.save(session)

            st.success("✅ Done — check the **Results** tab.")
            st.rerun()
        except Exception as e:
            st.error(f"Computation failed: {e}")
            import traceback
            st.code(traceback.format_exc())


# ── Tab: Results ──────────────────────────────────────────────────────────────

def _render_results(session: FilingSession) -> None:
    if not session.computed_federal:
        st.info("No results yet — run **Compute** first.")
        return

    f = session.computed_federal
    form = f.form_1040

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("AGI", f"${form.line11_agi:,.0f}")
    m2.metric("Taxable income", f"${form.line15_taxable_income:,.0f}")
    m3.metric("Total tax", f"${form.line24_total_tax:,.0f}")
    if f.balance_due > 0:
        m4.metric("Balance due 🔴", f"${f.balance_due:,.0f}")
    else:
        m4.metric("Refund 🟢", f"${f.refund:,.0f}")

    st.divider()
    col_fed, col_ny = st.columns(2)

    with col_fed:
        st.subheader("Federal 1040")
        _1040_table(form)

        if f.schedule_b:
            with st.expander("Schedule B — Interest & Dividends"):
                sb = f.schedule_b
                st.metric("Taxable interest", f"${sb.total_taxable_interest:,.2f}")
                st.metric("Ordinary dividends", f"${sb.total_ordinary_dividends:,.2f}")

        if f.schedule_d:
            with st.expander("Schedule D — Capital Gains"):
                sd = f.schedule_d
                c1, c2 = st.columns(2)
                c1.metric("Net short-term", f"${sd.net_short_term:,.2f}")
                c2.metric("Net long-term", f"${sd.net_long_term:,.2f}")
                txns = sd.short_term_transactions + sd.long_term_transactions
                if txns:
                    st.dataframe(
                        [{"Term": t.term, "Description": t.description,
                          "Proceeds": f"${t.proceeds:,.2f}", "Basis": f"${t.cost_basis:,.2f}",
                          "Gain/Loss": f"${t.gain_loss:,.2f}"} for t in txns],
                        use_container_width=True,
                    )

        if f.schedule_e:
            with st.expander("Schedule E — K-1 Pass-through"):
                for entry in f.schedule_e.entries:
                    st.write(f"• **{entry.entity_name}**: ${entry.net_income:,.2f}")

    with col_ny:
        ny = session.computed_ny
        if ny:
            st.subheader("NY IT-201")
            _it201_table(ny)
        else:
            st.subheader("NY IT-201")
            st.caption("Not applicable.")

    if form.line24_total_tax > 0:
        st.divider()
        st.subheader(f"1040-ES — {session.tax_year + 1} Estimated Payments")
        try:
            from pfile.compute.estimated_tax import compute_estimated_tax_for_year
            plan = compute_estimated_tax_for_year(f, session.filing_status, session.tax_year)
            em1, em2, em3 = st.columns(3)
            em1.metric("Prior-year tax", f"${plan.prior_year_tax:,.0f}")
            em2.metric("Safe-harbor rate", f"{int(plan.safe_harbor_rate * 100)}%")
            em3.metric("Annual estimate", f"${plan.annual_estimate:,.0f}")
            rows = [
                {"Quarter": f"Q{q.quarter}", "Due Date": q.due_date.strftime("%b %-d, %Y"),
                 "Payment": f"${q.payment:,.2f}"}
                for q in plan.quarters
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.caption(plan.method_note)
        except Exception as e:
            st.caption(f"Could not compute estimated tax: {e}")


def _1040_table(form) -> None:
    rows = [
        ("1a  W-2 wages", form.line1a_w2_wages),
        ("2b  Taxable interest", form.line2b_taxable_interest),
        ("3b  Ordinary dividends", form.line3b_ordinary_dividends),
        ("4b  IRA distributions", form.line4b_ira_distributions),
        ("5b  SS benefits (taxable)", form.line5b_taxable_ss),
        ("7   Capital gain/loss", form.line7_capital_gain_loss),
        ("8   Other income", form.line8_other_income),
        ("9   Total income", form.line9_total_income),
        ("11  AGI", form.line11_agi),
        ("15  Taxable income", form.line15_taxable_income),
        ("16  Income tax", form.line16_tax),
        ("19  Child tax credit", form.line19_ctc),
        ("24  Total tax", form.line24_total_tax),
        ("25a W-2 withholding", form.line25a_w2_withheld),
        ("26  Estimated payments", form.line26_estimated_payments),
        ("33  Total payments", form.line33_total_payments),
    ]
    st.dataframe(
        {"Line": [r[0] for r in rows], "Amount": [f"${r[1]:,.2f}" for r in rows]},
        use_container_width=True, hide_index=True,
    )


def _it201_table(ny) -> None:
    it = ny.it201
    rows = [
        ("Federal AGI", it.federal_agi),
        ("NY AGI", it.ny_agi),
        ("NY deduction used", it.ny_deduction_used),
        ("NY taxable income", it.ny_taxable_income),
        ("NY income tax", it.ny_tax),
        ("NY total tax", ny.total_ny_tax),
        ("NY total payments", ny.total_ny_payments),
    ]
    st.dataframe(
        {"Line": [r[0] for r in rows], "Amount": [f"${r[1]:,.2f}" for r in rows]},
        use_container_width=True, hide_index=True,
    )
    st.divider()
    if ny.balance_due > 0:
        st.metric("NY Balance due", f"${ny.balance_due:,.2f}")
    else:
        st.metric("NY Refund", f"${ny.refund:,.2f}")


# ── Tab: Generate ─────────────────────────────────────────────────────────────

def _render_generate(session: FilingSession, store: SessionStore) -> None:
    st.subheader("Generate Filing Package")

    if not session.computed_federal:
        st.info("Run **Compute** first before generating the package.")
        return

    fill_forms = st.checkbox(
        "Fill official IRS 1040 & NY IT-201 PDFs (requires downloaded form templates)",
    )
    no_es = st.checkbox("Skip 1040-ES estimated tax vouchers")

    st.caption(
        "The ZIP includes a cover sheet, line-item data sheets, payment vouchers, "
        "and optionally filled official PDFs."
    )

    if st.button("⬇ Build & Download Package", type="primary"):
        with st.spinner("Building filing package…"):
            try:
                from pfile.output.package import generate_package
                with tempfile.TemporaryDirectory() as tmp:
                    zip_path = generate_package(
                        session=session,
                        federal=session.computed_federal,
                        ny=session.computed_ny,
                        output_dir=Path(tmp),
                        fill_forms=fill_forms,
                        include_estimated_tax=not no_es,
                    )
                    zip_bytes = zip_path.read_bytes()
                    zip_name = zip_path.name

                st.success("Package ready!")
                st.download_button(
                    label=f"📥 Download {zip_name}",
                    data=zip_bytes,
                    file_name=zip_name,
                    mime="application/zip",
                    type="primary",
                )
            except Exception as e:
                st.error(f"Package generation failed: {e}")
                import traceback
                st.code(traceback.format_exc())
