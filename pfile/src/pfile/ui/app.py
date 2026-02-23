"""
pFile — main Streamlit app entry point.

Run with:
    poetry run streamlit run src/pfile/ui/app.py
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from pfile.models.filer import (
    Address,
    FilingStatus,
    NYResidencyInfo,
    TaxpayerProfile,
)
from pfile.models.session import FilingSession
from pfile.ui.state import clear_active, get_active_id, get_store, set_active

st.set_page_config(
    page_title="pFile — Tax Filing",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_new_session_form(store) -> None:
    st.subheader("New Filing Session")
    with st.form("new_session", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            tax_year = st.selectbox("Tax year", [2025, 2024, 2023], index=0)
            filing_status = st.selectbox(
                "Filing status",
                [fs.value for fs in FilingStatus],
                format_func=lambda v: v.replace("_", " ").title(),
            )
        with c2:
            first_name = st.text_input("First name *")
            last_name = st.text_input("Last name *")
            ssn = st.text_input("SSN *", placeholder="123-45-6789")

        st.markdown("**Address**")
        ac1, ac2, ac3, ac4 = st.columns([3, 1, 2, 1])
        with ac1:
            street = st.text_input("Street")
        with ac2:
            apt = st.text_input("Apt / Unit")
        with ac3:
            city = st.text_input("City")
        with ac4:
            zip_code = st.text_input("ZIP")

        state_opts = ["NY", "NJ", "CT", "PA", "MA", "FL", "CA", "TX", "IL", "Other"]
        state = st.selectbox("State", state_opts)

        if state == "NY":
            ny_c1, ny_c2, ny_c3 = st.columns(3)
            with ny_c1:
                county = st.text_input("NY County", help="e.g. Albany, Kings, New York")
            with ny_c2:
                nyc = st.checkbox("NYC resident")
            with ny_c3:
                yonkers = st.checkbox("Yonkers resident")
        else:
            county, nyc, yonkers = "", False, False

        submitted = st.form_submit_button("✓ Create session", type="primary")

    if submitted:
        if not (first_name.strip() and last_name.strip() and ssn.strip()):
            st.error("First name, last name, and SSN are required.")
            return

        ny_res = NYResidencyInfo(
            county=county.strip() or None,
            nyc_resident=nyc,
            yonkers_resident=yonkers,
        ) if state == "NY" else None

        profile = TaxpayerProfile(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            ssn=ssn.strip(),
            dob=date(1980, 1, 1),
            address=Address(
                street=street.strip() or "Unknown",
                apt=apt.strip() or None,
                city=city.strip() or "Unknown",
                state=state,
                zip_code=zip_code.strip() or "00000",
            ),
            ny_residency=ny_res,
        )

        session = FilingSession(
            tax_year=int(tax_year),
            filing_status=FilingStatus(filing_status),
            primary=profile,
        )
        store.save(session)
        st.session_state["show_new_form"] = False
        set_active(session.id)
        st.rerun()


def _render_home() -> None:
    store = get_store()
    st.title("Filing Sessions")

    if st.button("＋ New session", type="primary"):
        st.session_state["show_new_form"] = not st.session_state.get("show_new_form", False)

    if st.session_state.get("show_new_form"):
        st.divider()
        _render_new_session_form(store)
        st.divider()

    sessions = store.list()
    if not sessions:
        st.info("No sessions yet — click **＋ New session** to get started.")
        return

    for s in sessions:
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 2, 2])
            with c1:
                st.markdown(f"**{s.display_name}** &nbsp;·&nbsp; Tax Year {s.tax_year}", unsafe_allow_html=True)
                status_icon = {"draft": "🟡", "computed": "🟢", "filed": "🔵"}.get(s.status.value, "⚪")
                fs_label = s.filing_status.value.replace("_", " ").title()
                st.caption(f"{status_icon} {s.status.value.title()} · {fs_label} · `{s.id[:8]}…`")
            with c2:
                if s.computed_federal:
                    f = s.computed_federal
                    if f.balance_due > 0:
                        st.metric("Balance due", f"${f.balance_due:,.0f}")
                    else:
                        st.metric("Refund", f"${f.refund:,.0f}")
            with c3:
                btn_c, del_c = st.columns(2)
                with btn_c:
                    if st.button("Open →", key=f"open_{s.id}", use_container_width=True, type="primary"):
                        set_active(s.id)
                        st.rerun()
                with del_c:
                    if st.button("🗑", key=f"del_{s.id}", use_container_width=True, help="Delete this session"):
                        store.delete(s.id)
                        st.rerun()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📄 pFile")
    st.caption("Open-source US federal & NY state tax filing")
    st.divider()

    active_id = get_active_id()
    if active_id:
        store = get_store()
        try:
            s = store.load(active_id)
            st.success(f"**{s.display_name}**\nYear {s.tax_year}")
        except Exception:
            pass
        if st.button("← All sessions", use_container_width=True):
            clear_active()
            st.rerun()
    else:
        st.info("Select or create a session to begin.")


# ── Route ─────────────────────────────────────────────────────────────────────

active_id = get_active_id()
if active_id:
    from pfile.ui.views.session_detail import render
    render(active_id)
else:
    _render_home()
