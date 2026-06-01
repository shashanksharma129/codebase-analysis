import asyncio
import io
import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import click
import requests
import streamlit as st
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.analyzers import get_analyzer
from src.cache import create_cache
from src.llm_factory import create_llm
from src.observability import setup_telemetry
from src.pipeline import run_pipeline
from src.ui_helpers import _collect_endpoints

load_dotenv()
setup_telemetry()

st.set_page_config(page_title="Codebase Analyzer", layout="wide")

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_GITHUB_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+))?/?$"
)
_COMPLEXITY_BADGE = {"low": "🟢 low", "medium": "🟡 medium", "high": "🔴 high"}
_VERB_COLOR = {
    "GET":    "#4fc3f7",
    "POST":   "#81c784",
    "PUT":    "#ffb74d",
    "DELETE": "#ef9a9a",
    "PATCH":  "#fff176",
}


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Returns (owner, repo, branch). Raises ValueError on no match."""
    m = _GITHUB_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not a valid GitHub URL: {url!r}")
    owner, repo, branch = m.group(1), m.group(2), m.group(3) or "main"
    return owner, repo, branch


def _download_and_extract(owner: str, repo: str, branch: str, dest: Path) -> tuple[Path, int]:
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    resp = requests.get(zip_url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download repository: HTTP {resp.status_code}")
    zip_bytes = len(resp.content)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(dest)
    return next(dest.iterdir()), zip_bytes


# LLM + cache initialised once at startup
try:
    _llm = create_llm()
    _cache = create_cache()
except click.ClickException as e:
    st.error(e.format_message())
    st.stop()

# ── Page header ───────────────────────────────────────────────────────────────
st.title("Codebase Analyzer")

_provider = os.environ.get("LLM_PROVIDER", "anthropic")
_model = os.environ.get("LLM_MODEL", "")
st.caption(
    f"Provider: **{_provider}**" + (f"  ·  Model: **{_model}**" if _model else "")
)

# ── Input ─────────────────────────────────────────────────────────────────────
col_url, col_branch = st.columns([4, 1])
with col_url:
    url = st.text_input(
        "GitHub Repository URL", placeholder="https://github.com/owner/repo"
    )
with col_branch:
    branch_input = st.text_input("Branch", value="main")

_LANG_EXT = {"Java": ".java", "Python": ".py"}
lang = st.selectbox("Language", list(_LANG_EXT), index=0)
analyzer = get_analyzer(_LANG_EXT[lang])

analyze_clicked = st.button("Analyze", type="primary", disabled=not url.strip())

# ── Analysis ──────────────────────────────────────────────────────────────────
if analyze_clicked and url.strip():
    try:
        owner, repo, branch_from_url = parse_github_url(url)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    branch = branch_input.strip() or branch_from_url
    tmp = tempfile.mkdtemp()
    result = None
    error_msg = None

    with tracer.start_as_current_span(
        "analyze_repo",
        attributes={"repo": repo, "branch": branch, "provider": _provider},
    ) as span:
        try:
            with st.status("Downloading repository...", expanded=True) as status:
                with tracer.start_as_current_span(
                    "download_zip",
                    attributes={"repo": repo, "branch": branch},
                ) as dl_span:
                    source, zip_bytes = _download_and_extract(owner, repo, branch, Path(tmp))
                    dl_span.set_attribute("zip_bytes", zip_bytes)
                status.update(label="Analyzing repository...")
                result = asyncio.run(run_pipeline(source, _llm, _cache, analyzer))
                status.update(label="Done.", state="complete")
            span.set_status(StatusCode.OK)
        except RuntimeError as e:
            error_msg = str(e)
            logger.error(
                "Download failed",
                extra={"repo": repo, "branch": branch, "error": str(e)},
            )
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, description=str(e))
        except requests.RequestException as e:
            error_msg = f"Network error: {e}"
            logger.error(
                "Download failed",
                extra={"repo": repo, "branch": branch, "error": str(e)},
            )
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, description=str(e))
        except Exception as e:
            error_msg = f"Analysis failed: {e}"
            logger.error("Analysis failed", extra={"repo": repo, "error": str(e)})
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, description=str(e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if error_msg:
        st.error(error_msg)
    elif result:
        st.session_state["result"] = result
        st.session_state["result_repo"] = repo
        st.session_state["result_lang"] = lang
        st.session_state["expanded_domain"] = None

# ── Results ───────────────────────────────────────────────────────────────────
if "result" in st.session_state:
    result = st.session_state["result"]
    repo = st.session_state["result_repo"]
    lang = st.session_state["result_lang"]
    if "expanded_domain" not in st.session_state:
        st.session_state["expanded_domain"] = None

    endpoint_rows = _collect_endpoints(result.domains)
    tab_names = ["Overview", "Domains"]
    if endpoint_rows:
        tab_names.append("API Surface")
    tab_names += ["Insights", "Raw JSON"]
    tabs = st.tabs(tab_names)
    tab_idx = {name: i for i, name in enumerate(tab_names)}

    # ── Overview ──────────────────────────────────────────────────────────────
    with tabs[tab_idx["Overview"]]:
        st.subheader(result.project.name)
        st.markdown(result.project.overview)
        st.caption(result.project.purpose)
        st.markdown(f"**Architecture:** {result.project.architecture_pattern}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Complexity", _COMPLEXITY_BADGE[result.summary.overall_complexity])
        c2.metric("Files", result.summary.total_files)
        c3.metric("Domains", result.summary.total_domains)
        c4.metric("Methods", result.summary.total_methods)
        if result.project.tech_stack:
            st.markdown(
                "**Tech stack:** "
                + "  ".join(f"`{t}`" for t in result.project.tech_stack)
            )

    # ── Domains ───────────────────────────────────────────────────────────────
    with tabs[tab_idx["Domains"]]:
        if result.domains:
            cols = st.columns(3)
            for i, domain in enumerate(result.domains):
                with cols[i % 3]:
                    with st.container(border=True):
                        st.markdown(
                            f"**{domain.name}** — {_COMPLEXITY_BADGE[domain.complexity]}\n\n"
                            f"{domain.file_count} files · {len(domain.methods)} methods\n\n"
                            f"_{domain.description}_"
                        )
                        if domain.notable_aspects:
                            st.markdown(
                                " ".join(f"`{a}`" for a in domain.notable_aspects)
                            )
                        is_expanded = st.session_state["expanded_domain"] == domain.name
                        label = "▲ Hide methods" if is_expanded else "▼ Show methods"
                        if st.button(label, key=f"expand_{domain.name}"):
                            st.session_state["expanded_domain"] = (
                                None if is_expanded else domain.name
                            )
                            st.rerun()

            expanded = st.session_state["expanded_domain"]
            if expanded:
                domain_map = {d.name: d for d in result.domains}
                d = domain_map[expanded]
                st.markdown(f"---\n### {d.name} — methods")
                if not d.methods:
                    st.info("No methods found in this domain.")
                else:
                    for m in d.methods:
                        with st.container(border=True):
                            if m.http_method:
                                color = _VERB_COLOR.get(m.http_method, "#ffffff")
                                st.markdown(
                                    f'<span style="color:{color};font-weight:600;">'
                                    f"{m.http_method}</span> "
                                    f'<span style="color:{color};">{m.endpoint}</span>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    '<span style="color:#888;">internal</span>',
                                    unsafe_allow_html=True,
                                )
                            st.caption(m.class_name or "")
                            st.code(m.signature, language="text")
                            st.write(m.description)
                            st.markdown(f"Complexity: {_COMPLEXITY_BADGE[m.complexity]}")
        else:
            st.info(f"No {lang.lower()} files detected in this repository.")

    # ── API Surface ───────────────────────────────────────────────────────────
    if endpoint_rows:
        with tabs[tab_idx["API Surface"]]:
            domain_count = len({r["Domain"] for r in endpoint_rows})
            st.caption(
                f"{len(endpoint_rows)} endpoint{'s' if len(endpoint_rows) != 1 else ''} "
                f"across {domain_count} domain{'s' if domain_count != 1 else ''}"
            )
            st.dataframe(endpoint_rows, use_container_width=True)

    # ── Insights ──────────────────────────────────────────────────────────────
    with tabs[tab_idx["Insights"]]:
        any_content = False
        if result.summary.key_patterns:
            any_content = True
            st.markdown("### Key Patterns")
            st.markdown(" ".join(f"`{p}`" for p in result.summary.key_patterns))
        if result.summary.notable_aspects:
            any_content = True
            st.markdown("### Notable Aspects")
            st.markdown("\n".join(f"- {a}" for a in result.summary.notable_aspects))
        if result.summary.skipped_files:
            any_content = True
            with st.expander(f"Skipped files ({len(result.summary.skipped_files)})"):
                st.code("\n".join(result.summary.skipped_files))
        if not any_content:
            st.info("No insights available.")

    # ── Raw JSON ──────────────────────────────────────────────────────────────
    with tabs[tab_idx["Raw JSON"]]:
        st.download_button(
            "Download report.json",
            data=result.model_dump_json(indent=2, by_alias=True),
            file_name=f"{repo}-report.json",
            mime="application/json",
            key="download_report",
        )
        st.json(result.model_dump(by_alias=True))
