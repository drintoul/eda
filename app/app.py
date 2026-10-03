import csv
import io
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt


# -----------------------------
# Formatting helpers
# -----------------------------
def _format_int(n: int) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _pct(x: float) -> str:
    try:
        return f"{float(x) * 100.0:.2f}%"
    except Exception:
        return str(x)


# -----------------------------
# ID-like detection
# -----------------------------
@dataclass
class IdDetectionResult:
    auto_excluded: List[str]
    reasons: List[Tuple[str, str]]


ID_NAME_RE = re.compile(r"(^id$|_id$|^id_|uuid|guid|hash|token|(^|_)key$|identifier)", re.IGNORECASE)


def is_probably_id_like(series: pd.Series, col_name: str) -> Tuple[bool, str]:
    s = series.dropna()
    if s.empty:
        return False, "empty"

    name = str(col_name or "")
    if ID_NAME_RE.search(name):
        return True, "name looks like id"

    n = len(s)
    nunique = s.nunique(dropna=True)
    unique_ratio = nunique / max(n, 1)

    # high-uniqueness heuristic — skip floats: continuous measurements are
    # naturally ~unique without being IDs
    if not pd.api.types.is_float_dtype(s):
        if n >= 50 and unique_ratio >= 0.98:
            return True, f"~unique ({unique_ratio:.2%})"
        if n < 50 and unique_ratio >= 0.95 and nunique >= 20:
            return True, f"~unique small-n ({unique_ratio:.2%})"

    # uuid-ish strings
    if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
        sample = s.astype(str).head(200)
        uuidish = sample.str.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            case=False,
        ).mean()
        if uuidish >= 0.20:
            return True, "uuid-like values"

    return False, "not id-like"


def detect_id_like_columns(df: pd.DataFrame) -> IdDetectionResult:
    auto, reasons = [], []
    for col in df.columns:
        ok, reason = is_probably_id_like(df[col], str(col))
        if ok:
            auto.append(col)
            reasons.append((str(col), reason))
    return IdDetectionResult(auto, reasons)


# -----------------------------
# CSV loading (more robust)
# -----------------------------
def _sniff_sep(file_bytes: bytes, default: str = ",") -> str:
    """Detect the delimiter among common candidates; fall back to comma."""
    try:
        sample = file_bytes[:100_000].decode("utf-8", errors="replace")
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        return default


@st.cache_data(show_spinner=False)
def load_csv_bytes(
    file_bytes: bytes,
    encoding: Optional[str],
    sep: Optional[str],
    bad_lines: str = "error",  # "error" or "skip"
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Returns (df, warning_message).
    Uses a safe fallback if pandas' C engine hits tokenization errors.
    """
    buf = io.BytesIO(file_bytes)
    kwargs: Dict[str, Any] = {}

    if encoding and encoding != "auto":
        kwargs["encoding"] = encoding

    if sep and sep != "auto":
        kwargs["sep"] = "\t" if sep == "\\t" else sep
    else:
        kwargs["sep"] = _sniff_sep(file_bytes)

    warning = None

    # First attempt: default engine (fast)
    try:
        return pd.read_csv(buf, **kwargs), None
    except UnicodeDecodeError:
        # Not UTF-8 — latin-1 covers most common legacy encodings
        kwargs["encoding"] = "latin-1"
        warning = "Encoding notice: file is not UTF-8; decoded as latin-1."
        buf = io.BytesIO(file_bytes)
        try:
            return pd.read_csv(buf, **kwargs), warning
        except pd.errors.ParserError as e:
            parse_err = e
    except pd.errors.ParserError as e:
        parse_err = e

    if bad_lines != "skip":
        # Surface the parse error to the user
        raise parse_err

    # Fallback: python engine + on_bad_lines
    kwargs2 = dict(kwargs)
    kwargs2["engine"] = "python"
    kwargs2["on_bad_lines"] = "skip"
    skip_msg = (
        "CSV parse warning: detected malformed rows; using python engine with on_bad_lines='skip'. "
        "Some rows may be dropped."
    )
    warning = f"{warning} {skip_msg}" if warning else skip_msg
    return pd.read_csv(io.BytesIO(file_bytes), **kwargs2), warning


@st.cache_data(show_spinner=False)
def get_excel_sheet_names(file_bytes: bytes) -> List[str]:
    workbook = pd.ExcelFile(io.BytesIO(file_bytes))
    return workbook.sheet_names


@st.cache_data(show_spinner=False)
def load_excel_bytes(file_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)


def _safe_series_for_numeric(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return s
    return pd.to_numeric(s, errors="coerce")


def _looks_datetime(s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if pd.api.types.is_numeric_dtype(s):
        return False
    sample = s.dropna().astype(str).head(200)
    if sample.empty:
        return False
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return parsed.notna().mean() >= 0.9


# -----------------------------
# Plot helpers (matplotlib)
# -----------------------------
def plot_hist(values: np.ndarray, bins: int = 30):
    fig, ax = plt.subplots()
    ax.hist(values, bins=bins)
    ax.set_xlabel("Value")
    ax.set_ylabel("Count")
    ax.set_title("Histogram")
    st.pyplot(fig, clear_figure=True)


def plot_bar(categories: List[str], counts: List[int], title: str = "Value counts"):
    fig, ax = plt.subplots()
    ax.barh(categories[::-1], counts[::-1])
    ax.set_xlabel("Count")
    ax.set_title(title)
    st.pyplot(fig, clear_figure=True)


def plot_scatter(x: pd.Series, y: pd.Series, x_name: str, y_name: str, max_points: int = 5000):
    df_xy = pd.DataFrame({x_name: x, y_name: y}).dropna()
    if len(df_xy) > max_points:
        df_xy = df_xy.sample(max_points, random_state=42)

    fig, ax = plt.subplots()
    ax.scatter(df_xy[x_name].to_numpy(), df_xy[y_name].to_numpy(), s=10)
    ax.set_xlabel(x_name)
    ax.set_ylabel(y_name)
    ax.set_title("Scatter (sampled)")
    st.pyplot(fig, clear_figure=True)


def plot_box_by_category(num: pd.Series, cat: pd.Series, num_name: str, cat_name: str, top_k: int = 15):
    df_nc = pd.DataFrame({num_name: num, cat_name: cat}).dropna()
    if df_nc.empty:
        st.info("Not enough non-null data to plot.")
        return

    vc = df_nc[cat_name].astype(str).value_counts()
    keep = vc.head(top_k).index
    df_nc = df_nc[df_nc[cat_name].astype(str).isin(keep)]

    groups, labels = [], []
    for k in keep:
        vals = df_nc.loc[df_nc[cat_name].astype(str) == k, num_name].dropna().to_numpy()
        if len(vals) > 0:
            groups.append(vals)
            labels.append(str(k))

    if not groups:
        st.info("No data after filtering categories.")
        return

    fig, ax = plt.subplots(figsize=(min(12, 0.5 * len(labels) + 2), 6))
    ax.boxplot(groups, labels=labels, vert=True, showfliers=False)
    ax.set_title(f"{num_name} by {cat_name} (top {top_k})")
    ax.set_ylabel(num_name)
    ax.tick_params(axis="x", rotation=45)
    st.pyplot(fig, clear_figure=True)


def corr_heatmap(corr: pd.DataFrame, title: str = "Correlation heatmap"):
    if corr.empty:
        st.info("No numeric columns available.")
        return
    fig, ax = plt.subplots(
        figsize=(min(12, 0.6 * len(corr.columns) + 2), min(12, 0.6 * len(corr.columns) + 2))
    )
    im = ax.imshow(corr.to_numpy(), aspect="auto")
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.index)))
    ax.set_xticklabels(corr.columns, rotation=90)
    ax.set_yticklabels(corr.index)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    st.pyplot(fig, clear_figure=True)


# -----------------------------
# Correlation caching (session-state)
# -----------------------------
def _corr_fingerprint(file_name: str, sample_rows: int, excluded_set: Tuple[str, ...], method: str, num_cols: List[str]) -> str:
    # A simple, stable fingerprint. (Not hashing full data on purpose.)
    return f"{file_name}|sample={sample_rows}|excluded={','.join(excluded_set)}|method={method}|num={','.join(num_cols)}"


def reset_ui_state(keep_file: bool = True):
    keep_keys = {"file_bytes", "file_name", "excel_sheet_name"} if keep_file else set()
    for k in list(st.session_state.keys()):
        if k not in keep_keys:
            del st.session_state[k]
    st.rerun()


# -----------------------------
# Columns drill-down tab
# -----------------------------
def render_columns_tab(df_used: pd.DataFrame):
    # Build visible columns list using the applied search/group filters
    visible_cols = list(df_used.columns)

    # group filter
    group = st.session_state.get("col_group", "All")
    if group != "All":
        if group == "Numeric":
            visible_cols = [c for c in visible_cols if pd.api.types.is_numeric_dtype(_safe_series_for_numeric(df_used[c]))]
        elif group == "Datetime":
            visible_cols = [c for c in visible_cols if _looks_datetime(df_used[c])]
        else:  # Categorical/Text
            visible_cols = [
                c
                for c in visible_cols
                if not pd.api.types.is_numeric_dtype(_safe_series_for_numeric(df_used[c]))
                and not _looks_datetime(df_used[c])
            ]

    # search filter
    needle = (st.session_state.get("col_search", "") or "").strip().lower()
    if needle:
        visible_cols = [c for c in visible_cols if needle in str(c).lower()]

    # favorites: show on top (still keep full list)
    favs = [c for c in st.session_state.get("favorites", []) if c in visible_cols]
    non_favs = [c for c in visible_cols if c not in favs]
    visible_cols = favs + non_favs

    if not visible_cols:
        st.warning("No columns match your filters. Adjust search/group/exclusions in the sidebar and click Apply.")
        return

    left, right = st.columns([1, 2])

    with left:
        st.subheader("Pick a column")
        default_col = st.session_state.get("selected_col")
        if default_col not in visible_cols:
            default_col = visible_cols[0]

        col = st.selectbox(
            "Column",
            options=visible_cols,
            index=visible_cols.index(default_col),
            key="selected_col_widget",
        )
        st.session_state["selected_col"] = col

        st.divider()
        st.subheader("Compare (optional)")
        compare_options = ["(none)"] + [c for c in df_used.columns if c != col]
        default_compare = st.session_state.get("compare_with", "(none)")
        if default_compare not in compare_options:
            default_compare = "(none)"

        compare_with = st.selectbox(
            "Compare with",
            options=compare_options,
            index=compare_options.index(default_compare),
            key="compare_with_widget",
        )
        st.session_state["compare_with"] = compare_with
        st.caption("Comparison plots are sampled to stay fast.")

    with right:
        s = df_used[col]
        st.subheader(f"Column: `{col}`")
        st.write(f"**dtype:** `{s.dtype}`")

        n = len(s)
        missing = int(s.isna().sum())
        nunique = int(s.nunique(dropna=True))
        st.write(
            f"- **rows:** {_format_int(n)}  \n"
            f"- **missing:** {_format_int(missing)} ({_pct(missing / max(n,1))})  \n"
            f"- **unique:** {_format_int(nunique)}"
        )

        s_num = _safe_series_for_numeric(s)
        is_numeric = pd.api.types.is_numeric_dtype(s_num)

        st.divider()
        if is_numeric:
            st.markdown("### Numeric summary")
            desc = s_num.describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
            st.dataframe(desc.to_frame(name="value"), width="stretch")

            st.markdown("### Distribution")
            vals = s_num.dropna().to_numpy()
            if len(vals) == 0:
                st.info("No non-null numeric values to plot.")
            else:
                bins = st.slider("Histogram bins", 10, 200, 40, step=5, key="hist_bins")
                plot_hist(vals, bins=bins)

            if nunique <= st.session_state["max_unique"]:
                st.markdown("### Value counts")
                vc = s_num.value_counts(dropna=True).head(st.session_state["top_k"])
                st.dataframe(vc.rename("count").to_frame(), width="stretch")
            else:
                st.caption("Value counts hidden (too many unique values). Increase the threshold if needed.")
        else:
            st.markdown("### Categorical / text summary")
            s_str = s.astype("string")
            lens = s_str.dropna().str.len()
            if len(lens) > 0:
                st.write(
                    f"- **min length:** {int(lens.min())}\n"
                    f"- **median length:** {int(lens.median())}\n"
                    f"- **max length:** {int(lens.max())}"
                )

            st.markdown("### Value counts")
            if nunique > st.session_state["max_unique"]:
                st.warning(
                    f"High cardinality: {_format_int(nunique)} unique values. Showing top values only."
                )

            vc = s.astype(str).replace("nan", np.nan).dropna().value_counts()
            vc_head = vc.head(st.session_state["top_k"])
            st.dataframe(vc_head.rename("count").to_frame(), width="stretch")

            if len(vc_head) > 0:
                plot_bar(vc_head.index.tolist(), vc_head.values.tolist(), title=f"Top {len(vc_head)} values")

            show_all = st.checkbox("Show ALL value counts (may be large / slow)", value=False, key="show_all_counts")
            if show_all and nunique <= 50_000:
                st.dataframe(vc.rename("count").to_frame(), width="stretch")
            elif show_all:
                st.error("Too many unique values to display safely (cap is 50,000).")

        # Compare plot
        if compare_with != "(none)":
            st.divider()
            st.markdown(f"### Compare: `{col}` vs `{compare_with}`")

            a = df_used[col]
            b = df_used[compare_with]

            a_num = _safe_series_for_numeric(a)
            b_num = _safe_series_for_numeric(b)

            a_is_num = pd.api.types.is_numeric_dtype(a_num)
            b_is_num = pd.api.types.is_numeric_dtype(b_num)

            if a_is_num and b_is_num:
                plot_scatter(a_num, b_num, col, compare_with)
                pair = pd.DataFrame({col: a_num, compare_with: b_num}).dropna()
                if len(pair) >= 3:
                    r = float(pair[col].corr(pair[compare_with]))
                    st.write(f"**Pearson r:** `{r:.4f}` (on {_format_int(len(pair))} non-null pairs)")
            elif a_is_num and not b_is_num:
                plot_box_by_category(a_num, b.astype("string"), col, compare_with, top_k=st.session_state["top_k"])
            elif (not a_is_num) and b_is_num:
                plot_box_by_category(b_num, a.astype("string"), compare_with, col, top_k=st.session_state["top_k"])
            else:
                st.info("For two non-numeric columns, add a task-specific comparison (e.g., crosstab).")
                a_str, b_str = a.astype("string"), b.astype("string")
                n_cells = int(a_str.nunique(dropna=True)) * int(b_str.nunique(dropna=True))
                if n_cells <= 2500:
                    st.dataframe(pd.crosstab(a_str, b_str), width="stretch")
                else:
                    st.caption(
                        f"Crosstab too large to render ({_format_int(n_cells)} cells). "
                        "Reduce categories or sample more aggressively."
                    )


# -----------------------------
# Main UI
# -----------------------------
def main():
    st.set_page_config(page_title="Exploratory Data Analyzer", layout="wide")
    st.title("Exploratory Data Analyzer")
    st.caption("Upload a dataset (CSV, XLSX, XLS), configure analysis settings, then drill into columns interactively.")

    # ---------- Sidebar: load + settings ----------
    with st.sidebar:
        st.header("1) Load data")
        uploaded = st.file_uploader("Upload file (CSV, XLSX, XLS supported)", type=["csv", "xls", "xlsx"], key="uploader")

        if uploaded:
            st.session_state["file_bytes"] = uploaded.getvalue()
            st.session_state["file_name"] = uploaded.name

        if "file_bytes" not in st.session_state:
            st.info("Upload a CSV or Excel file (CSV, XLSX, XLS) to continue.")
            st.stop()

        current_file_name = st.session_state.get("file_name", "")
        is_excel_file = str(current_file_name).lower().endswith((".xls", ".xlsx"))

        if is_excel_file:
            try:
                sheet_names = get_excel_sheet_names(st.session_state["file_bytes"])
            except Exception as e:
                st.error(f"Failed to inspect Excel workbook: {e}")
                st.stop()

            if not sheet_names:
                st.error("No worksheets were found in the Excel file.")
                st.stop()

            if st.session_state.get("excel_sheet_name") not in sheet_names:
                st.session_state["excel_sheet_name"] = sheet_names[0]

            st.divider()
            st.header("2) Workbook")
            st.selectbox(
                "Worksheet",
                options=sheet_names,
                index=sheet_names.index(st.session_state["excel_sheet_name"]),
                key="excel_sheet_name",
                help="Choose which Excel worksheet to analyze.",
            )

        st.divider()
        st.header("3) Parsing & performance")

        encoding = st.selectbox("Encoding", ["auto", "utf-8", "latin-1"], index=0, key="encoding")
        sep = st.selectbox("Separator", ["auto", ",", "\\t", ";", "|"], index=0, key="sep")
        bad_lines = st.selectbox(
            "Malformed rows",
            ["error", "skip"],
            index=0,
            help="If your CSV has broken rows (extra delimiters, unescaped quotes), choose 'skip' to drop them.",
            key="bad_lines",
        )

        if is_excel_file:
            st.caption("CSV parsing options below do not apply to Excel files.")

        sample_rows = st.slider("Max rows to analyze (sampling)", 1_000, 200_000, 50_000, step=1_000, key="sample_rows")
        max_unique_for_counts = st.slider("Max unique values to show counts for", 10, 5000, 200, step=10, key="max_unique")
        top_k_counts = st.slider("Top K values (charts/tables)", 5, 100, 30, step=5, key="top_k")

        st.divider()
        st.header("4) Reset")
        if st.button("Reset sidebar / selections", type="secondary"):
            reset_ui_state(keep_file=True)

        st.divider()
        st.header("5) Correlations refresh")
        auto_update_corr = st.checkbox(
            "Auto-update correlations when analysis config changes",
            value=False,
            key="auto_update_corr",
            help="If off, correlations only recompute when you click 'Re-run correlations'.",
        )
        rerun_corr_clicked = st.button("Re-run correlations", type="primary")
        st.session_state["rerun_corr_clicked"] = rerun_corr_clicked

    # ---------- Load data ----------
    file_name = st.session_state.get("file_name", "").lower()

    if file_name.endswith((".xls", ".xlsx")):
        selected_sheet = st.session_state.get("excel_sheet_name")
        try:
            available_sheets = get_excel_sheet_names(st.session_state["file_bytes"])
            if not selected_sheet or selected_sheet not in available_sheets:
                selected_sheet = available_sheets[0]
                st.session_state["excel_sheet_name"] = selected_sheet
            df = load_excel_bytes(st.session_state["file_bytes"], selected_sheet)
            parse_warning = None
        except Exception as e:
            st.error(f"Failed to read Excel file: {e}")
            st.stop()
    else:
        df, parse_warning = load_csv_bytes(
            st.session_state["file_bytes"],
            st.session_state.get("encoding", "auto"),
            st.session_state.get("sep", "auto"),
            bad_lines=st.session_state.get("bad_lines", "error"),
        )
        if parse_warning:
            st.warning(parse_warning)

    # sample if huge
    df_for_analysis = df
    if len(df_for_analysis) > st.session_state["sample_rows"]:
        df_for_analysis = df_for_analysis.sample(st.session_state["sample_rows"], random_state=42)

    id_detection = detect_id_like_columns(df_for_analysis)

    # ---------- Sidebar: drill-down form (Apply button) ----------
    with st.sidebar:
        st.header("6) Drill-down controls")

        # Initialize defaults once
        if "excluded_cols" not in st.session_state:
            st.session_state["excluded_cols"] = id_detection.auto_excluded
        if "force_include_cols" not in st.session_state:
            st.session_state["force_include_cols"] = []
        if "col_search" not in st.session_state:
            st.session_state["col_search"] = ""
        if "favorites" not in st.session_state:
            st.session_state["favorites"] = []
        if "col_group" not in st.session_state:
            st.session_state["col_group"] = "All"

        with st.form("drilldown_form"):
            st.caption(f"Total rows: **{_format_int(len(df))}** • Analyzing: **{_format_int(len(df_for_analysis))}**")

            col_search = st.text_input("Search columns", value=st.session_state["col_search"])
            col_group = st.radio(
                "Column group",
                ["All", "Numeric", "Datetime", "Categorical/Text"],
                index=["All", "Numeric", "Datetime", "Categorical/Text"].index(st.session_state["col_group"]),
                horizontal=True,
            )

            excluded_cols = st.multiselect(
                "Excluded columns (ID-like preselected)",
                options=list(df_for_analysis.columns),
                default=st.session_state["excluded_cols"],
            )
            force_include_cols = st.multiselect(
                "Force-include (overrides exclusion)",
                options=list(df_for_analysis.columns),
                default=st.session_state["force_include_cols"],
            )
            favorites = st.multiselect(
                "Favorites",
                options=list(df_for_analysis.columns),
                default=st.session_state["favorites"],
                help="Purely for quick access; doesn’t change analysis.",
            )

            applied = st.form_submit_button("Apply selection")

        if applied:
            st.session_state["col_search"] = col_search
            st.session_state["col_group"] = col_group
            st.session_state["excluded_cols"] = excluded_cols
            st.session_state["force_include_cols"] = force_include_cols
            st.session_state["favorites"] = favorites

    # ---------- Apply exclusions/inclusions ----------
    exclude_set = set(st.session_state.get("excluded_cols", [])) - set(st.session_state.get("force_include_cols", []))
    df_used = df_for_analysis.drop(columns=list(exclude_set), errors="ignore")

    # ---------- Tabs ----------
    tab_overview, tab_columns, tab_corr = st.tabs(["Overview", "Columns", "Correlations"])

    # -----------------------------
    # Overview
    # -----------------------------
    with tab_overview:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Rows (total)", _format_int(len(df)))
        with c2:
            st.metric("Rows (analyzed)", _format_int(len(df_used)))
        with c3:
            st.metric("Columns (analyzed)", str(len(df_used.columns)))

        if file_name.endswith((".xls", ".xlsx")):
            st.caption(f"Worksheet: **{st.session_state.get('excel_sheet_name', '')}**")

        st.subheader("Preview")
        st.dataframe(df.head(200), width="stretch")

        st.subheader("Schema & missingness (analyzed sample)")
        summary = pd.DataFrame(
            {
                "column": df_used.columns,
                "dtype": [str(df_used[c].dtype) for c in df_used.columns],
                "missing": [int(df_used[c].isna().sum()) for c in df_used.columns],
                "missing_%": [(df_used[c].isna().mean() * 100.0) for c in df_used.columns],
                "n_unique": [int(df_used[c].nunique(dropna=True)) for c in df_used.columns],
            }
        ).sort_values(["missing_%", "n_unique"], ascending=[False, False])
        st.dataframe(summary, width="stretch")

        if id_detection.reasons:
            st.subheader("Auto-detected ID-like columns (on analyzed sample)")
            st.dataframe(pd.DataFrame(id_detection.reasons, columns=["column", "reason"]), width="stretch")

    # -----------------------------
    # Columns drill-down
    # -----------------------------
    with tab_columns:
        render_columns_tab(df_used)

    # -----------------------------
    # Correlations (re-run toggle separate from drill-down)
    # -----------------------------
    with tab_corr:
        st.subheader("Numeric correlations (analyzed sample)")

        num_df = df_used.select_dtypes(include=[np.number]).copy()
        if num_df.shape[1] < 2:
            st.info("Need at least 2 numeric columns for correlations.")
            return

        method = st.selectbox("Correlation method", ["pearson", "spearman", "kendall"], index=0, key="corr_method")

        excluded_sorted = tuple(sorted(exclude_set))
        num_cols = list(num_df.columns)
        fp = _corr_fingerprint(
            file_name=st.session_state.get("file_name", "uploaded.csv"),
            sample_rows=st.session_state["sample_rows"],
            excluded_set=excluded_sorted,
            method=method,
            num_cols=num_cols,
        )

        # Determine whether we should recompute
        cached_fp = st.session_state.get("corr_fingerprint")
        cached_corr = st.session_state.get("corr_cache")

        want_rerun = bool(st.session_state.get("rerun_corr_clicked", False))
        auto_update = bool(st.session_state.get("auto_update_corr", False))

        if cached_corr is None:
            # first time
            want_recompute = True
        elif auto_update and cached_fp != fp:
            want_recompute = True
        elif want_rerun:
            want_recompute = True
        else:
            want_recompute = False

        if want_recompute:
            with st.spinner("Computing correlations..."):
                corr = num_df.corr(method=method)
            st.session_state["corr_cache"] = corr
            st.session_state["corr_fingerprint"] = fp
            # reset button click latch
            st.session_state["rerun_corr_clicked"] = False
        else:
            corr = cached_corr
            if cached_fp != fp:
                st.caption("Analysis config changed since correlations were last computed — click **Re-run correlations** to refresh.")

        corr_heatmap(corr, title=f"{method.title()} correlation heatmap")

        st.divider()
        st.subheader("Selected numeric column vs others")
        pick = st.selectbox("Numeric column", options=list(num_df.columns), index=0, key="corr_pick")

        if pick not in corr.columns:
            st.info(
                f"`{pick}` isn't in the cached correlation matrix. "
                "Click **Re-run correlations** in the sidebar to include it."
            )
        else:
            corrs = corr[pick].drop(index=pick).sort_values(key=lambda x: x.abs(), ascending=False)
            st.dataframe(corrs.rename("corr").to_frame(), width="stretch")

        st.caption(
            f"Correlation cache key: `{st.session_state.get('corr_fingerprint','(none)')}`  \n"
            "Use **Sidebar → Re-run correlations** to refresh without changing drill-down selections."
        )


if __name__ == "__main__":
    main()
