# UI Redesign Implementation Spec

## Goal

Replace the current two-tab Streamlit UI (Summary / Raw JSON) with a richer five-tab layout that surfaces all analyzed data — method signatures, HTTP endpoints, key patterns, and notable aspects — in focused, scannable views.

## Architecture

All changes are confined to `ui.py`. No backend changes required. The data model (`FinalOutput`, `DomainAnalysis`, `MethodInfo`, `ProjectSummary`) already carries everything needed; the current UI simply doesn't display most of it.

Tab list is built dynamically: the "API Surface" tab is only added when at least one method across all domains has a non-null `http_method`. This avoids a useless empty tab for library repos.

Session state (`st.session_state`) is used to track which domain card is currently expanded, enabling click-to-expand / click-to-collapse behavior with only one domain open at a time.

## Tech Stack

- Streamlit (existing)
- Pure Python — no new dependencies

---

## Tab Designs

### Tab 1 — Overview

Unchanged from current Summary tab content:

- Project name as `st.subheader`
- Overview as `st.markdown`
- Purpose as `st.caption`
- 5-column metrics row: Architecture, Complexity (with badge), Files, Domains, Methods
- Tech stack pills rendered as inline code spans

### Tab 2 — Domains

3-column card grid. Each domain renders as a `st.container` with a border showing:

- Domain name + complexity badge
- File count and method count
- Description
- `notable_aspects` as small inline pill tags (rendered via `st.markdown` with backtick spans)
- An expand/collapse button ("▼ Show methods" / "▲ Hide methods")

**Expand behavior:**

Clicking the button toggles `st.session_state["expanded_domain"]`. Only one domain can be expanded at a time — expanding a second one collapses the first.

When expanded, a method card section renders below that domain's card (not below the entire grid). Each method card is a styled `st.container` showing:

- HTTP verb badge (colored text: GET=blue `#4fc3f7`, POST=green `#81c784`, PUT=orange `#ffb74d`, DELETE=red `#ef9a9a`, PATCH=yellow `#fff176`) + endpoint path, or "internal" in muted grey if `http_method` is None
- Class name in muted text
- Full signature in `st.code(..., language="text")`
- One-line description as regular text
- Complexity badge aligned right

Method cards are rendered in order as returned by the model.

### Tab 3 — API Surface (conditional)

Only added to the tab list if `any(m.http_method for d in result.domains for m in d.methods)`.

Header line: `"{N} endpoints across {D} domains"` where N = total endpoint count, D = number of domains that have at least one endpoint.

Single `st.dataframe` (or `st.table`) with columns:

| Verb | Path | Method | Domain | Description | Complexity |
|------|------|--------|--------|-------------|------------|

Sorted by domain name, then path. Verb column values are plain strings (GET, POST, etc.) — no color in dataframe cells (Streamlit dataframe doesn't support per-cell color without custom CSS; plain text is fine).

### Tab 4 — Insights

Three sections rendered in order:

**Key Patterns** — `st.markdown("### Key Patterns")` followed by pill badges rendered as a single markdown line of backtick-wrapped items joined by spaces. Only rendered if `summary.key_patterns` is non-empty.

**Notable Aspects** — `st.markdown("### Notable Aspects")` followed by `st.markdown` of a bulleted list (`"- " + aspect` per line). Only rendered if `summary.notable_aspects` is non-empty.

**Skipped Files** — Only rendered if `summary.skipped_files` is non-empty. Wrapped in `st.expander("Skipped files ({N})")`. Inside: `st.code("\n".join(summary.skipped_files))`.

If all three sections are empty (edge case), show `st.info("No insights available.")`.

### Tab 5 — Raw JSON

Unchanged from current Raw JSON tab:

- `st.download_button` for `report.json`
- `st.json(result.model_dump(by_alias=True))`

---

## Session State

One key used: `st.session_state["expanded_domain"]` — holds the name (string) of the currently expanded domain, or `None` if all are collapsed. Initialized to `None` before the tab block renders.

---

## HTTP Verb Color Map

```python
_VERB_COLOR = {
    "GET":    "#4fc3f7",
    "POST":   "#81c784",
    "PUT":    "#ffb74d",
    "DELETE": "#ef9a9a",
    "PATCH":  "#fff176",
}
```

Used in method cards within the Domains tab to color the verb+endpoint line via `st.markdown`.

---

## Error and Edge Cases

- **No domains found** — Domains tab shows the existing `st.info("No {lang} files detected…")` message.
- **Domain has no methods** — expanded panel shows `st.info("No methods found in this domain.")`.
- **No endpoints at all** — API Surface tab is not added to the tab list.
- **Empty key_patterns / notable_aspects / skipped_files** — each Insights section is skipped independently; no empty headings rendered.

---

## Files Changed

- **Modify:** `ui.py` — replace the `tab_summary, tab_json = st.tabs(...)` block and everything inside it with the new five-tab layout. Everything above that block (LLM init, input widgets, analysis trigger, OTel spans, error handling) is unchanged.
