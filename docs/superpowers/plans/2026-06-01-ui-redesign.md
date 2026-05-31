# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-tab Streamlit UI with a five-tab layout (Overview · Domains · API Surface · Insights · Raw JSON) that surfaces method signatures, HTTP endpoints, key patterns, and notable aspects.

**Architecture:** All changes are confined to `ui.py` and a new `src/ui_helpers.py` module. The helper module holds the pure `_collect_endpoints` function so it can be unit-tested without Streamlit. Result is persisted in `st.session_state` so expand/collapse buttons inside the Domains tab don't cause the result to disappear on rerender.

**Tech Stack:** Streamlit, Pydantic (`FinalOutput`, `DomainAnalysis`, `MethodInfo`)

---

## File Structure

- **Create:** `src/ui_helpers.py` — `_collect_endpoints(domains) -> list[dict]`
- **Modify:** `ui.py` — add `_VERB_COLOR` constant, import `_collect_endpoints`, persist result to session state, replace `elif result:` block (lines 146–190) with five-tab layout
- **Modify:** `tests/test_ui.py` — add `_collect_endpoints` tests (file already exists with `parse_github_url` tests)

---

### Task 1: `src/ui_helpers.py` + tests for `_collect_endpoints`

**Files:**
- Create: `src/ui_helpers.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py`:

```python
from src.models import DomainAnalysis, MethodInfo
from src.ui_helpers import _collect_endpoints


def _make_method(
    method_name: str,
    http_method: str | None = None,
    endpoint: str | None = None,
    complexity: str = "low",
) -> MethodInfo:
    return MethodInfo(
        class_name="Foo",
        method_name=method_name,
        signature=f"void {method_name}()",
        description="desc",
        http_method=http_method,
        endpoint=endpoint,
        complexity=complexity,
    )


def _make_domain(name: str, methods: list[MethodInfo]) -> DomainAnalysis:
    return DomainAnalysis(
        name=name,
        description="desc",
        file_count=1,
        complexity="low",
        methods=methods,
        notable_aspects=[],
    )


def test_collect_endpoints_empty_domains():
    assert _collect_endpoints([]) == []


def test_collect_endpoints_no_http_methods():
    domain = _make_domain("catalog", [_make_method("doSomething")])
    assert _collect_endpoints([domain]) == []


def test_collect_endpoints_returns_http_methods_only():
    domain = _make_domain("catalog", [
        _make_method("getProduct", "GET", "/products/{id}", "low"),
        _make_method("internalHelper"),
    ])
    rows = _collect_endpoints([domain])
    assert len(rows) == 1
    assert rows[0]["Method"] == "getProduct"


def test_collect_endpoints_row_fields():
    domain = _make_domain("catalog", [
        _make_method("createProduct", "POST", "/products", "medium"),
    ])
    row = _collect_endpoints([domain])[0]
    assert row == {
        "Verb": "POST",
        "Path": "/products",
        "Method": "createProduct",
        "Domain": "catalog",
        "Description": "desc",
        "Complexity": "medium",
    }


def test_collect_endpoints_sorted_by_domain_then_path():
    d1 = _make_domain("orders", [_make_method("getOrder", "GET", "/orders/{id}")])
    d2 = _make_domain("catalog", [
        _make_method("createProduct", "POST", "/products"),
        _make_method("getProduct", "GET", "/products/{id}"),
    ])
    rows = _collect_endpoints([d1, d2])
    assert [r["Domain"] for r in rows] == ["catalog", "catalog", "orders"]
    assert rows[0]["Path"] == "/products"
    assert rows[1]["Path"] == "/products/{id}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ui.py::test_collect_endpoints_empty_domains -v
```

Expected: `ModuleNotFoundError: No module named 'src.ui_helpers'`

- [ ] **Step 3: Create `src/ui_helpers.py`**

```python
from src.models import DomainAnalysis


def _collect_endpoints(domains: list[DomainAnalysis]) -> list[dict]:
    rows = []
    for domain in domains:
        for m in domain.methods:
            if m.http_method:
                rows.append({
                    "Verb": m.http_method,
                    "Path": m.endpoint or "",
                    "Method": m.method_name,
                    "Domain": domain.name,
                    "Description": m.description,
                    "Complexity": m.complexity,
                })
    return sorted(rows, key=lambda r: (r["Domain"], r["Path"]))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_ui.py -v
```

Expected: all tests pass (6 pre-existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add src/ui_helpers.py tests/test_ui.py
git commit -m "feat: add _collect_endpoints helper with tests"
```

---

### Task 2: Rewrite `ui.py` result display

**Files:**
- Modify: `ui.py`

The current `elif result:` block (lines 146–190) is inside `if analyze_clicked and url.strip():`. This means any rerender (e.g., the "Show methods" button click) causes `analyze_clicked` to be `False`, wiping the result display. We fix this by persisting the result in `st.session_state` and rendering outside the `if analyze_clicked` block.

- [ ] **Step 1: Add `_VERB_COLOR` constant and import to `ui.py`**

After line 16 (`from opentelemetry.trace import StatusCode`), add the import:

```python
from src.ui_helpers import _collect_endpoints
```

After the existing `_COMPLEXITY_BADGE` constant (line 35), add:

```python
_VERB_COLOR = {
    "GET":    "#4fc3f7",
    "POST":   "#81c784",
    "PUT":    "#ffb74d",
    "DELETE": "#ef9a9a",
    "PATCH":  "#fff176",
}
```

- [ ] **Step 2: Persist result to session state on success**

Replace lines 143–190 (the `if error_msg: ... elif result:` block at the bottom) with:

```python
    if error_msg:
        st.error(error_msg)
    elif result:
        st.session_state["result"] = result
        st.session_state["result_repo"] = repo
        st.session_state["result_lang"] = lang
        st.session_state["expanded_domain"] = None
```

- [ ] **Step 3: Add the five-tab results section below the analysis block**

Append to `ui.py` after the `if analyze_clicked` block (after the `shutil.rmtree` / `if error_msg` section):

```python
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
        )
        st.json(result.model_dump(by_alias=True))
```

- [ ] **Step 4: Run the existing tests to make sure nothing broke**

```bash
python -m pytest tests/test_ui.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add ui.py
git commit -m "feat: five-tab UI with domain expansion and API surface view"
```

---

### Task 3: Visual verification

The Streamlit UI cannot be automatically tested — verify manually by running the app.

- [ ] **Step 1: Start the app**

```bash
streamlit run ui.py
```

Open `http://localhost:8501` in a browser.

- [ ] **Step 2: Analyze a real repo**

Use `https://github.com/jeetendra-choudhary/spring-rest-sakila` with branch `main` and language `Java`. Click **Analyze**.

- [ ] **Step 3: Check Overview tab**

Verify: project name, overview text, purpose, 5 metrics (Architecture, Complexity, Files, Domains, Methods), tech stack pills all appear.

- [ ] **Step 4: Check Domains tab**

Verify: domain cards appear in a 3-column grid, each card shows name, complexity badge, file/method counts, description. Click **▼ Show methods** on one domain. Verify method cards appear below the grid with HTTP verb (colored), endpoint, class name, signature in monospace, description, complexity. Click **▲ Hide methods** to collapse. Click a different domain's button — verify first collapses, second expands.

- [ ] **Step 5: Check API Surface tab**

Verify: tab is present (the Sakila repo has REST endpoints). Header shows endpoint count and domain count. Dataframe shows Verb, Path, Method, Domain, Description, Complexity columns sorted by Domain then Path.

- [ ] **Step 6: Check Insights tab**

Verify: Key Patterns section shows pill badges, Notable Aspects section shows a bulleted list. (Skipped Files section only appears if any files were skipped — leave it if empty.)

- [ ] **Step 7: Check Raw JSON tab**

Verify: Download button and JSON viewer are present and functional.

- [ ] **Step 8: Verify expand/collapse persists across tab switches**

Expand a domain in the Domains tab, switch to Overview, switch back — domain should still be expanded.

- [ ] **Step 9: Commit if any fixes were needed**

```bash
git add ui.py
git commit -m "fix: <describe what needed fixing>"
```

If no fixes were needed, no commit required.
