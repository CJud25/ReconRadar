"""ReconRadar Streamlit entry point."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import streamlit as st

from tens_hq.constants import APP_VERSION, DEFAULT_SEED, DEFAULT_TARGET, SYNTHETIC_BANNER
from tens_hq.demo_tour import DEMO_TOUR
from tens_hq.pages import PAGE_RENDERERS, apply_theme
from tens_hq.roles import allowed_pages, pilot_mode_enabled
from tens_hq.synthetic import generate_demo_data

st.set_page_config(
    page_title="ReconRadar",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner="Generating deterministic synthetic validation data...")
def load_demo_data(seed: int):
    return generate_demo_data(seed)


def _query_value(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[-1] if value else None
    return value


def _restore_and_clamp_navigation(visible_pages: Sequence[str]) -> None:
    """Restore URL state before widgets exist, then clamp it to visible choices."""

    query_nav = _query_value("nav")
    if "nav" not in st.session_state and query_nav in visible_pages:
        st.session_state["nav"] = query_nav
    if st.session_state.get("nav") not in visible_pages:
        st.session_state["nav"] = visible_pages[0]

    if "tour_step" not in st.session_state:
        try:
            st.session_state["tour_step"] = int(_query_value("tour") or 0)
        except ValueError:
            st.session_state["tour_step"] = 0
    st.session_state["tour_step"] = min(
        max(int(st.session_state.get("tour_step", 0)), 0),
        len(DEMO_TOUR) - 1,
    )


def _open_tour_step(step: int) -> None:
    """Mutate navigation only from a callback, before the nav radio renders."""

    clamped_step = min(max(step, 0), len(DEMO_TOUR) - 1)
    st.session_state["tour_step"] = clamped_step
    st.session_state["nav"] = DEMO_TOUR[clamped_step].target_page


def _open_current_tour_page() -> None:
    _open_tour_step(int(st.session_state.get("tour_step", 0)))


def _render_guided_demo() -> None:
    step = int(st.session_state["tour_step"])
    beat = DEMO_TOUR[step]
    st.markdown("**▶ Guided demo**")
    st.progress((step + 1) / len(DEMO_TOUR), text=f"Beat {step + 1} of {len(DEMO_TOUR)}")
    st.markdown(f"**{beat.title}**")
    st.caption(beat.sentence)
    st.caption(f"Point at: {beat.highlight}")
    controls = st.columns(3)
    controls[0].button(
        "◀",
        key="tour_previous",
        disabled=step == 0,
        on_click=_open_tour_step,
        args=(step - 1,),
        help="Previous beat",
        use_container_width=True,
    )
    controls[1].button(
        "Open",
        key="tour_open",
        on_click=_open_current_tour_page,
        help=f"Go to {beat.target_page}",
        use_container_width=True,
    )
    controls[2].button(
        "▶",
        key="tour_next",
        disabled=step == len(DEMO_TOUR) - 1,
        on_click=_open_tour_step,
        args=(step + 1,),
        help="Next beat",
        use_container_width=True,
    )


def main() -> None:
    apply_theme()
    data = load_demo_data(DEFAULT_SEED)

    pilot_mode = pilot_mode_enabled()
    with st.sidebar:
        st.markdown("# ReconRadar")
        st.caption("part of TENS HQ")
        if pilot_mode:
            st.caption("PILOT MODE — guided tour and planning controls hidden")
        visible_pages = allowed_pages()
        _restore_and_clamp_navigation(visible_pages)
        page = st.radio(
            "Navigate",
            visible_pages,
            key="nav",
            label_visibility="collapsed",
        )
        if page == "BD Feasibility":
            st.markdown(
                '<div class="sidebar-banner">PUBLIC EVIDENCE PILOT — '
                'ORGANIZATIONAL / CONTRACT DIRECTORY DATA ONLY</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="sidebar-banner">{SYNTHETIC_BANNER}</div>',
                unsafe_allow_html=True,
            )
        st.markdown("---")
        if not pilot_mode:
            # The guided tour is a demo aid; a pilot session is real work.
            _render_guided_demo()
            st.markdown("---")
        # Both page renderers immediately `del` these args (pages.py,
        # bd_page.py) -- the "Planning controls" selectbox/slider changed
        # nothing on the Governance page and invited a reviewer to distrust
        # a trust page (§5.10). scenario/target_pct stay defined as harmless
        # constants for the PAGE_RENDERERS(...) call below.
        scenario = "Base"
        target_pct = DEFAULT_TARGET * 100.0
        st.markdown("---")
        st.caption(f"Demo v{APP_VERSION} · Seed {DEFAULT_SEED}")

    st.query_params["nav"] = page
    st.query_params["tour"] = str(st.session_state["tour_step"])
    PAGE_RENDERERS[page](data, target_pct / 100.0, scenario)


if __name__ == "__main__":
    main()
