"""TraceGrade web interface (Streamlit entry point).

Launch with ``tracegrade ui`` or ``streamlit run src/tracegrade/ui/app.py``.
"""

from __future__ import annotations

import streamlit as st

from tracegrade.config import get_settings
from tracegrade.errors import TraceGradeError
from tracegrade.logging_utils import configure_logging

st.set_page_config(
    page_title="TraceGrade",
    page_icon=":material/fact_check:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem; max-width: 1280px;}
      [data-testid="stMetricValue"] {font-size: 1.6rem;}
      [data-testid="stSidebarNav"] {padding-top: 0.5rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def _configure_logging_once() -> bool:
    try:
        cfg = get_settings()
    except TraceGradeError:
        return False
    secrets = [k.get_secret_value() for k in (cfg.openai_api_key, cfg.groq_api_key) if k]
    configure_logging(cfg.log_level, cfg.log_format, cfg.log_file, secrets)
    return True


_configure_logging_once()

pages = {
    "": [
        st.Page("pages/home.py", title="Overview", icon=":material/dashboard:", default=True),
    ],
    "Evaluate": [
        st.Page("pages/evaluate.py", title="New evaluation", icon=":material/play_circle:"),
        st.Page("pages/results.py", title="Run results", icon=":material/analytics:"),
        st.Page("pages/compare.py", title="Compare runs", icon=":material/compare_arrows:"),
    ],
    "Explore": [
        st.Page("pages/playground.py", title="Agent playground", icon=":material/forum:"),
        st.Page("pages/datasets.py", title="Datasets", icon=":material/dataset:"),
    ],
    "Help": [
        st.Page("pages/settings_help.py", title="Settings & help", icon=":material/settings:"),
    ],
}

with st.sidebar:
    st.markdown("### :material/fact_check: TraceGrade")
    st.caption("Evaluation workbench for tool-using LangChain agents")

st.navigation(pages).run()
