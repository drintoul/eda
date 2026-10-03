"""Regression tests for the Streamlit EDA app, driven by streamlit's AppTest.

Run:  pip install -r requirements-dev.txt && pytest
"""
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "app" / "app.py"


def _csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def make_app(file_bytes: bytes, name: str = "test.csv", **session_overrides) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["file_bytes"] = file_bytes
    at.session_state["file_name"] = name
    for k, v in session_overrides.items():
        at.session_state[k] = v
    return at


@pytest.fixture
def demo_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "a": rng.normal(size=100),
        "b": rng.normal(size=100),
        "c": rng.normal(size=100),
        "user_id": [f"u{i:04d}" for i in range(100)],
        "cat": rng.choice(["x", "y", "z"], 100),
    })


def _metrics(at: AppTest) -> dict:
    return {m.label: m.value for m in at.metric}


def test_basic_load(demo_df):
    at = make_app(_csv(demo_df))
    at.run()
    assert len(at.exception) == 0
    metrics = _metrics(at)
    assert metrics["Rows (total)"] == "100"
    assert metrics["Rows (analyzed)"] == "100"
    # user_id auto-excluded as ID-like; a/b/c/cat remain
    assert metrics["Columns (analyzed)"] == "4"


def test_float_columns_not_treated_as_ids():
    # Continuous float measurements are ~unique but must NOT be ID-excluded
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"measurement": rng.normal(size=100), "label": rng.choice(["p", "q"], 100)})
    at = make_app(_csv(df))
    at.run()
    assert len(at.exception) == 0
    assert _metrics(at)["Columns (analyzed)"] == "2"


def test_id_name_regex_no_false_positive_on_key_suffix():
    # "monkey" ends in "key" but is not an ID column
    df = pd.DataFrame({"monkey": ["capuchin"] * 50 + ["macaque"] * 50})
    at = make_app(_csv(df))
    at.run()
    assert _metrics(at)["Columns (analyzed)"] == "1"


def test_real_id_column_still_excluded():
    df = pd.DataFrame({"api_key": [f"k{i}" for i in range(60)], "val": [i % 7 for i in range(60)]})
    at = make_app(_csv(df))
    at.run()
    assert _metrics(at)["Columns (analyzed)"] == "1"


def test_single_column_csv_not_misparsed():
    # csv.Sniffer must not pick a letter as delimiter on single-column data
    df = pd.DataFrame({"monkey": ["capuchin"] * 50 + ["macaque"] * 50})
    at = make_app(_csv(df))
    at.run()
    assert len(at.exception) == 0
    assert _metrics(at)["Columns (analyzed)"] == "1"


def test_auto_separator_sniffs_semicolons():
    at = make_app(b"a;b;c\n1;2;3\n4;5;6\n")
    at.run()
    assert len(at.exception) == 0
    assert _metrics(at)["Columns (analyzed)"] == "3"


def test_auto_encoding_falls_back_to_latin1():
    latin = "name,city\nJosé,São Paulo\n".encode("latin-1")
    at = make_app(latin, name="latin.csv")
    at.run()
    assert len(at.exception) == 0
    assert any("latin-1" in w.value for w in at.warning)


def test_malformed_csv_error_mode_raises(demo_df):
    bad = b"a,b\n1,2\n3,4,EXTRA\n5,6\n"
    at = make_app(bad, bad_lines="error")
    at.run()
    assert len(at.exception) == 1


def test_malformed_csv_skip_mode_warns_and_loads():
    bad = b"a,b\n1,2\n3,4,EXTRA\n5,6\n"
    at = make_app(bad, bad_lines="skip")
    at.run()
    assert len(at.exception) == 0
    assert any("malformed" in w.value.lower() for w in at.warning)


def test_empty_column_filter_does_not_kill_corr_tab(demo_df):
    at = make_app(_csv(demo_df), col_search="zzz_no_match")
    at.run()
    assert len(at.exception) == 0
    assert any("No columns match" in w.value for w in at.warning)
    subheaders = [s.value for s in at.subheader]
    assert any("correlation" in s.lower() for s in subheaders)


def test_stale_corr_cache_does_not_crash():
    df = pd.DataFrame({
        "z": np.arange(60, dtype=float),
        "a": np.random.default_rng(0).normal(size=60),
        "b": np.random.default_rng(1).normal(size=60),
        "c": np.random.default_rng(2).normal(size=60),
    })
    at = make_app(_csv(df))
    # First run with z excluded -> corr cache built on [a,b,c] only
    at.session_state["excluded_cols"] = ["z"]
    at.run()
    assert len(at.exception) == 0
    # Un-exclude z without re-running correlations, then pick z
    at.session_state["excluded_cols"] = []
    at.run()
    sb = [s for s in at.selectbox if s.key == "corr_pick"][0]
    sb.set_value("z").run()
    assert len(at.exception) == 0
    assert any("Re-run correlations" in i.value for i in at.info)
