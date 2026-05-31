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
from src.cache import DiskCache
from src.llm_factory import create_llm
from src.observability import setup_telemetry
from src.pipeline import run_pipeline

load_dotenv()
setup_telemetry()

st.set_page_config(page_title="Codebase Analyzer", layout="wide")

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_GITHUB_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+))?/?$"
)
_COMPLEXITY_BADGE = {"low": "🟢 low", "medium": "🟡 medium", "high": "🔴 high"}


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
    _cache = DiskCache()
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
        tab_summary, tab_json = st.tabs(["Summary", "Raw JSON"])

        with tab_summary:
            st.subheader(result.project.name)
            st.markdown(result.project.overview)
            st.caption(result.project.purpose)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Architecture", result.project.architecture_pattern)
            c2.metric("Complexity", _COMPLEXITY_BADGE[result.summary.overall_complexity])
            c3.metric("Files", result.summary.total_files)
            c4.metric("Domains", result.summary.total_domains)
            c5.metric("Methods", result.summary.total_methods)

            if result.project.tech_stack:
                st.markdown(
                    "**Tech stack:** "
                    + "  ".join(f"`{t}`" for t in result.project.tech_stack)
                )

            if result.domains:
                st.markdown("### Domains")
                cols = st.columns(3)
                for i, domain in enumerate(result.domains):
                    with cols[i % 3]:
                        st.markdown(
                            f"**{domain.name}** — "
                            f"{_COMPLEXITY_BADGE[domain.complexity]}\n\n"
                            f"{domain.file_count} files · {len(domain.methods)} methods\n\n"
                            f"_{domain.description}_"
                        )
            else:
                st.info(
                    f"No {lang.lower()} files detected in this repository."
                )

        with tab_json:
            st.download_button(
                "Download report.json",
                data=result.model_dump_json(indent=2, by_alias=True),
                file_name=f"{repo}-report.json",
                mime="application/json",
            )
            st.json(result.model_dump(by_alias=True))
