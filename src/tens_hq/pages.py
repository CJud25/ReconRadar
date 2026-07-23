"""Streamlit page renderers for the ReconRadar packet surface."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from .bd_page import render_public_bd_page
from .constants import SYNTHETIC_BANNER
from .synthetic import DemoData
from .validation import validate_demo_data


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root { --navy:#15324B; --teal:#167D7F; --slate:#52606D; --paper:#F4F6F8; }
        .stApp { background: #F4F6F8; }
        [data-testid="stSidebar"] { background: #15324B; color: white; }
        [data-testid="stSidebar"] * { color: #F7FAFC; }
        [data-testid="stSidebar"] div[role="radiogroup"] label {
            padding: .42rem .55rem; border-radius: .45rem; margin: .08rem 0;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] label:hover { background:#234A68; }
        .sidebar-banner { font-size:.72rem; line-height:1.25; padding:.65rem; border:1px solid #4F718B;
            border-radius:.5rem; background:#1D405B; margin:.8rem 0 1rem; }
        .page-kicker { color:#167D7F; text-transform:uppercase; letter-spacing:.08em;
            font-size:.76rem; font-weight:700; margin-bottom:.2rem; }
        .page-title { color:#15324B; font-size:2.15rem; line-height:1.12; font-weight:750; margin:0; }
        .page-subtitle { color:#52606D; font-size:1rem; margin:.35rem 0 1rem; }
        .demo-banner, .planning-banner { padding:.62rem .82rem; border-radius:.45rem;
            font-size:.78rem; font-weight:700; margin:.35rem 0 1rem; }
        .demo-banner { background:#E6F4F1; color:#115E59; border-left:4px solid #167D7F; }
        .planning-banner { background:#FFF7E6; color:#8A5A13; border-left:4px solid #B7791F; }
        .insight-box { background:white; border:1px solid #D9E2EC; border-left:5px solid #167D7F;
            padding:1rem 1.1rem; border-radius:.55rem; margin:.6rem 0 1rem; color:#243B53; }
        div[data-testid="stMetric"] { background:white; border:1px solid #D9E2EC;
            padding:.8rem .9rem; border-radius:.6rem; min-height:112px; }
        div[data-testid="stMetricLabel"] { color:#52606D; }
        div[data-testid="stDataFrame"] { border:1px solid #D9E2EC; border-radius:.5rem; }
        .small-note { color:#52606D; font-size:.82rem; }
        h2, h3 { color:#15324B; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _page_header(title: str, subtitle: str, kicker: str) -> None:
    st.markdown(f'<div class="page-kicker">{html.escape(kicker)}</div>', unsafe_allow_html=True)
    st.markdown(f'<h1 class="page-title">{html.escape(title)}</h1>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">{html.escape(subtitle)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="demo-banner">{SYNTHETIC_BANNER}</div>', unsafe_allow_html=True)


def render_bd_feasibility(data: DemoData, target: float, scenario: str) -> None:
    """Route BD work to the governed public-evidence tracker.

    BD Feasibility is the isolated public-evidence scanner and cited
    Opportunity Packet: Eligibility Gate, Contract Facts, Capture Window,
    Geography, and the Procurement List cross-reference. The legacy
    synthetic feasibility engine has been deleted (ADR-016): no synthetic
    score, confidence, or planning control may make a public directory row
    look like a forecast or a bid/no-go call.
    """

    render_public_bd_page(data, target, scenario)


def render_governance(data: DemoData, target: float, scenario: str) -> None:
    del target, scenario
    _page_header(
        "Privacy & Governance",
        "The synthetic-data checks and public-evidence boundaries that keep the packet cited, explainable, and decision-support only.",
        "Governance / Trust",
    )
    validation = validate_demo_data(data)
    if validation.ok:
        st.success("Synthetic-data validation passed: row counts, ID prefixes, stage gate, domains, references, flags, and labor-hour math are consistent.")
    else:
        st.error("Validation failed. Dashboard outputs should not be used until corrected.")
        for error in validation.errors:
            st.markdown(f"- {error}")

    counts = pd.DataFrame(
        [
            {
                "dataset": name,
                "rows": len(frame),
                "synthetic_flag_complete": bool(frame["synthetic_flag"].all()),
            }
            for name, frame in data.frames().items()
        ]
    )
    left, right = st.columns([1, 1.1])
    with left:
        st.markdown("### Data inventory")
        st.caption(
            "All rows below are deterministic synthetic fixtures used only to validate the app's "
            "privacy/schema contracts; none are real people or organizations, and none join to public evidence."
        )
        st.dataframe(counts, hide_index=True, use_container_width=True)
    with right:
        st.markdown("### Deliberately excluded")
        st.markdown(
            "- Medical diagnoses or disability narratives\n"
            "- Doctor notes or psychological evaluations\n"
            "- IEP/504 or accommodation details\n"
            "- Scanned eligibility documents\n"
            "- Real applicant, employee, or partner data\n"
            "- Automated email sending\n"
            "- Person-level disability or worth scoring\n"
            "- Official ODLH compliance certification\n"
            "- Final bid/no-bid automation"
        )
        st.markdown("### Decision boundaries")
        st.markdown(
            "- The Opportunity Packet is a cited, non-numeric evidence sheet — never a feasibility score, PWin, ranking, or bid/no-bid recommendation.\n"
            "- Live sources are pulled only on an explicit analyst action, each fails loud, and every fact carries a source URL, retrieval time, and assurance label.\n"
            "- Public workbook rows and synthetic demonstration data never join; synthetic fixtures never become claims about real organizations or people.\n"
            "- The case ledger is local, single-user pilot infrastructure — not an authentication, authorization, encryption, backup, or multi-user boundary.\n"
            "- Analyst-typed and analyst-uploaded values are attestations, not independently verified evidence.\n"
            "- All generated communications and reports require human review."
        )

    st.markdown("### Manager-facing value statement")
    st.markdown(
        '<div class="insight-box">ReconRadar assembles cited, source-aware evidence for a prospective business-development opportunity into an explainable Opportunity Packet. It helps an analyst see what is known, what remains unverified, and which public sources support each section. It never produces a feasibility score or bid/no-bid recommendation, and it does not replace business-development, compliance, or legal judgment.</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Current primary-source framing used by this concept"):
        st.markdown(
            "- [41 U.S.C. § 8501](https://uscode.house.gov/view.xhtml?edition=prelim&num=0&req=granuleid%3AUSC-prelim-title41-section8501)\n"
            "- [AbilityOne Commission Policy 51.404 — Direct Labor Hour Ratio Requirements](https://www.abilityone.gov/laws%2C_regulations_and_policy/documents/U.S.%20AbilityOne%20Commission%20Policy%2051.404%20Direct%20Labor%20Hour%20Ratio%20Requirements%2020250902-a%20signed.pdf)\n"
            "- [AbilityOne Commission Policy 51.403 — QDL Employee Determination](https://www.abilityone.gov/laws%2C_regulations_and_policy/documents/U.S.%20AbilityOne%20Commission%20Policy%2051.403%20Qualifying%20Direct%20Labor%20Employee%20Determination%2020250902-a%20signed.pdf)\n"
            "- [EEOC — Pre-Employment Inquiries and Medical Questions](https://www.eeoc.gov/pre-employment-inquiries-and-medical-questions-examinations)"
        )
        st.caption("Policies can change. A future real-data implementation requires current legal, HR, compliance, CNA, privacy, and security review.")


PAGE_RENDERERS = {
    "BD Feasibility": render_bd_feasibility,
    "Privacy & Governance": render_governance,
}
