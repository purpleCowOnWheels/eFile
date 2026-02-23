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
    SpouseProfile,
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

# ── Address autocomplete (Nominatim / OpenStreetMap) ──────────────────────────

def _nominatim_search(query: str) -> list[dict]:
    """Return up to 5 US address results from Nominatim. Returns [] on any error."""
    if not query or len(query) < 5:
        return []
    try:
        import requests
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "addressdetails": "1",
                    "countrycodes": "us", "limit": "5"},
            headers={"User-Agent": "pFile-tax-app/1.0"},
            timeout=4,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def _parse_nominatim(result: dict) -> dict:
    """Extract street/city/state/zip from a Nominatim address detail dict."""
    a = result.get("address", {})
    road = a.get("road", "")
    number = a.get("house_number", "")
    street = f"{number} {road}".strip() if number else road

    city = (
        a.get("city")
        or a.get("town")
        or a.get("village")
        or a.get("hamlet")
        or a.get("municipality")
        or ""
    )
    state_abbr = _state_abbr(a.get("state", ""))
    county = a.get("county", "").replace(" County", "").strip()
    zip_code = a.get("postcode", "")
    return {
        "street": street,
        "city": city,
        "state": state_abbr,
        "zip_code": zip_code,
        "county": county,
    }


# Mapping of full state names → 2-letter abbreviations for common states
_STATE_MAP = {
    "new york": "NY", "new jersey": "NJ", "connecticut": "CT",
    "pennsylvania": "PA", "massachusetts": "MA", "florida": "FL",
    "california": "CA", "texas": "TX", "illinois": "IL",
    "ohio": "OH", "michigan": "MI", "georgia": "GA",
    "north carolina": "NC", "virginia": "VA", "washington": "WA",
    "arizona": "AZ", "colorado": "CO", "maryland": "MD",
    "minnesota": "MN", "wisconsin": "WI", "oregon": "OR",
    "nevada": "NV", "utah": "UT", "new mexico": "NM",
    "south carolina": "SC", "alabama": "AL", "louisiana": "LA",
    "kentucky": "KY", "tennessee": "TN", "indiana": "IN",
    "missouri": "MO", "iowa": "IA", "kansas": "KS",
    "arkansas": "AR", "mississippi": "MS", "oklahoma": "OK",
    "nebraska": "NE", "idaho": "ID", "montana": "MT",
    "wyoming": "WY", "north dakota": "ND", "south dakota": "SD",
    "alaska": "AK", "hawaii": "HI", "maine": "ME",
    "vermont": "VT", "new hampshire": "NH", "rhode island": "RI",
    "delaware": "DE", "west virginia": "WV",
}


def _state_abbr(name: str) -> str:
    if len(name) == 2:
        return name.upper()
    return _STATE_MAP.get(name.lower(), name[:2].upper() if name else "")


def _address_lookup_widget(prefix: str = "") -> None:
    """
    Render an address search box + Nominatim lookup outside any st.form.
    Writes selected address components into st.session_state with the given prefix.
    """
    key_query = f"{prefix}addr_query"
    key_results = f"{prefix}addr_results"
    key_selected = f"{prefix}addr_selected"

    col_search, col_btn = st.columns([5, 1])
    with col_search:
        query = st.text_input(
            "Address search",
            key=key_query,
            placeholder="Start typing your address…",
            label_visibility="collapsed",
        )
    with col_btn:
        search_clicked = st.button("🔍 Search", key=f"{prefix}addr_search_btn", use_container_width=True)

    if search_clicked and query:
        with st.spinner("Looking up address…"):
            results = _nominatim_search(query)
        if results:
            st.session_state[key_results] = results
            st.session_state.pop(key_selected, None)
        else:
            st.warning("No results found — try a more specific address.")
            st.session_state.pop(key_results, None)

    results = st.session_state.get(key_results, [])
    if results:
        labels = [r.get("display_name", "")[:80] for r in results]
        idx = st.selectbox(
            "Select address",
            range(len(labels)),
            format_func=lambda i: labels[i],
            key=key_selected,
        )
        if idx is not None:
            parsed = _parse_nominatim(results[idx])
            for field, val in parsed.items():
                st.session_state[f"{prefix}addr_{field}"] = val
            st.caption(
                f"↳ {parsed['street']}, {parsed['city']}, "
                f"{parsed['state']} {parsed['zip_code']}"
            )


# ── New session form ──────────────────────────────────────────────────────────

_ALL_STATES = [
    "NY", "NJ", "CT", "PA", "MA", "FL", "CA", "TX", "IL",
    "OH", "MI", "GA", "NC", "VA", "WA", "AZ", "CO", "MD",
    "MN", "WI", "OR", "NV", "UT", "NM", "SC", "AL", "LA",
    "KY", "TN", "IN", "MO", "IA", "KS", "AR", "MS", "OK",
    "NE", "ID", "MT", "WY", "ND", "SD", "AK", "HI", "ME",
    "VT", "NH", "RI", "DE", "WV", "Other",
]


def _render_new_session_form(store) -> None:
    st.subheader("New Filing Session")

    # ── Step 1: Filing basics (outside form — controls visibility of spouse section) ──
    b1, b2, b3 = st.columns(3)
    with b1:
        tax_year = st.selectbox("Tax year", [2025, 2024, 2023], key="ns_tax_year")
    with b2:
        filing_status = st.selectbox(
            "Filing status",
            [fs.value for fs in FilingStatus],
            format_func=lambda v: v.replace("_", " ").title(),
            key="ns_filing_status",
        )
    is_mfj = filing_status == FilingStatus.MFJ.value

    st.divider()

    # ── Step 2: Address lookup (outside form — needs reactivity) ─────────────
    st.markdown("**Primary address**")
    _address_lookup_widget(prefix="ns_")
    st.caption("Search auto-fills the fields below; edit freely before submitting.")

    # ── Step 3: Full form ─────────────────────────────────────────────────────
    with st.form("new_session", clear_on_submit=False):
        # Primary taxpayer
        st.markdown("**Primary taxpayer**")
        p1, p2, p3 = st.columns(3)
        with p1:
            first_name = st.text_input("First name *")
            ssn = st.text_input("SSN *", placeholder="123-45-6789")
        with p2:
            last_name = st.text_input("Last name *")
            dob_str = st.text_input("Date of birth", placeholder="YYYY-MM-DD")
        with p3:
            occupation = st.text_input("Occupation", placeholder="Optional")

        # Address fields pre-filled from Nominatim lookup
        st.markdown("**Address**")
        ac1, ac2, ac3, ac4 = st.columns([3, 1, 2, 1])
        with ac1:
            street = st.text_input(
                "Street", value=st.session_state.get("ns_addr_street", ""))
        with ac2:
            apt = st.text_input("Apt / Unit")
        with ac3:
            city = st.text_input(
                "City", value=st.session_state.get("ns_addr_city", ""))
        with ac4:
            zip_code = st.text_input(
                "ZIP", value=st.session_state.get("ns_addr_zip_code", ""))

        default_state = st.session_state.get("ns_addr_state", "NY")
        state_idx = _ALL_STATES.index(default_state) if default_state in _ALL_STATES else 0
        state = st.selectbox("State", _ALL_STATES, index=state_idx)

        if state == "NY":
            ny_c1, ny_c2, ny_c3 = st.columns(3)
            with ny_c1:
                county = st.text_input(
                    "NY County",
                    value=st.session_state.get("ns_addr_county", ""),
                    help="e.g. Albany, Kings, New York",
                )
            with ny_c2:
                nyc = st.checkbox("NYC resident")
            with ny_c3:
                yonkers = st.checkbox("Yonkers resident")
        else:
            county, nyc, yonkers = "", False, False

        # Spouse (MFJ only)
        if is_mfj:
            st.divider()
            st.markdown("**Spouse**")
            s1, s2, s3 = st.columns(3)
            with s1:
                sp_first = st.text_input("Spouse first name *")
                sp_ssn = st.text_input("Spouse SSN *", placeholder="123-45-6789")
            with s2:
                sp_last = st.text_input("Spouse last name *")
                sp_dob_str = st.text_input("Spouse date of birth", placeholder="YYYY-MM-DD")
            with s3:
                sp_occupation = st.text_input("Spouse occupation", placeholder="Optional")
        else:
            sp_first = sp_last = sp_ssn = sp_dob_str = sp_occupation = ""

        submitted = st.form_submit_button("✓ Create session", type="primary")

    if not submitted:
        return

    # Validate
    errors = []
    if not (first_name.strip() and last_name.strip() and ssn.strip()):
        errors.append("Primary taxpayer: first name, last name, and SSN are required.")
    if is_mfj and not (sp_first.strip() and sp_last.strip() and sp_ssn.strip()):
        errors.append("Spouse: first name, last name, and SSN are required for MFJ.")
    if errors:
        for e in errors:
            st.error(e)
        return

    def _parse_dob(s: str) -> date:
        try:
            return date.fromisoformat(s.strip())
        except Exception:
            return date(1980, 1, 1)

    ny_res = NYResidencyInfo(
        county=county.strip() or None,
        nyc_resident=nyc,
        yonkers_resident=yonkers,
    ) if state == "NY" else None

    primary = TaxpayerProfile(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        ssn=ssn.strip(),
        dob=_parse_dob(dob_str),
        occupation=occupation.strip() or None,
        address=Address(
            street=street.strip() or "Unknown",
            apt=apt.strip() or None,
            city=city.strip() or "Unknown",
            state=state,
            zip_code=zip_code.strip() or "00000",
        ),
        ny_residency=ny_res,
    )

    spouse = None
    if is_mfj:
        spouse = SpouseProfile(
            first_name=sp_first.strip(),
            last_name=sp_last.strip(),
            ssn=sp_ssn.strip(),
            dob=_parse_dob(sp_dob_str),
            occupation=sp_occupation.strip() or None,
        )

    session = FilingSession(
        tax_year=int(tax_year),
        filing_status=FilingStatus(filing_status),
        primary=primary,
        spouse=spouse,
    )
    store.save(session)

    # Clean up address search state
    for key in list(st.session_state.keys()):
        if key.startswith("ns_addr_") or key.startswith("ns_"):
            st.session_state.pop(key, None)

    st.session_state["show_new_form"] = False
    set_active(session.id)
    st.rerun()


# ── Home ──────────────────────────────────────────────────────────────────────

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
                short_id = s.id[:8]
                st.caption(f"{status_icon} {s.status.value.title()} · {fs_label} · `{short_id}…`")
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
        _store = get_store()
        try:
            _s = _store.load(active_id)
            st.success(f"**{_s.display_name}**\nYear {_s.tax_year}")
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
