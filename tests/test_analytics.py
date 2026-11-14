"""Tests on a tiny made-up dataset where every answer can be calculated by hand.

Run with:  python -m pytest -q
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from epresso import analytics as A  # noqa: E402
from epresso.data_loader import DataError, build_model, check_merge, load  # noqa: E402


def tiny_tables():
    sales = pd.DataFrame({
        "Sales ID": ["S1", "S2", "S3", "S4", "S5", "S6"],
        "Date": ["2025-01-31", "2025-12-31", "2026-01-31", "2026-12-31", "2025-12-31", "2026-12-31"],
        "Store ID": ["W", "W", "W", "W", "A", "A"],
        "StoreYear": ["W_25", "W_25", "W_26", "W_26", "A_25", "A_26"],
        "Category ID": ["C1", "C1", "C1", "C2", "C1", "C1"],
        "Product ID": ["P1", "P1", "P1", "P2", "P1", "P1"],
        "Revenue": [100, 300, 200, 400, 1000, 500],
    })
    stores = pd.DataFrame({"ID": ["W", "A"], "City": [None, "Aville"], "State": [None, "MT"],
                           "StoreType": ["Website", "Brick & Mortar"], "Market": ["5-Global", "1-Small"],
                           "Location": ["Website", "West"]})
    products = pd.DataFrame({"Product ID": ["P1", "P2"], "Product": ["Base Model", "Base Model"]})
    cats = pd.DataFrame({"Category ID": ["C1", "C2"], "Category": ["Beans", "Machines"]})
    survey = pd.DataFrame({"Survey ID": ["W_25", "W_26", "A_25", "A_26"], "Store ID": ["W", "W", "A", "A"],
                           "Year": ["Y2025", "Y2026", "Y2025", "Y2026"], "Satisfaction": [None, None, 4.0, 2.0],
                           "Interest": [None, None, 80, 70]})
    return {"Sales": sales, "Stores": stores, "Products": products, "Categories": cats, "Survey": survey}


@pytest.fixture
def model():
    return build_model(tiny_tables(), {})


def test_total_and_channels(model):
    df = model.sales
    assert A.get_revenue_summary(df)["value"]["total_revenue"] == 2500
    ch = A.get_revenue_by_channel(df)["value"]["revenue"]
    assert ch == {"Website": 1000, "Brick & Mortar": 1500}


def test_filters(model):
    df = model.sales
    assert A.get_revenue_summary(df, year=2026, channel="website")["value"]["total_revenue"] == 600
    assert A.get_revenue_summary(df, category="Machines")["value"]["total_revenue"] == 400
    assert A.get_revenue_summary(df, store="Aville")["value"]["total_revenue"] == 1500


def test_by_year_and_growth(model):
    r = A.get_revenue_by_year(model.sales)["value"]["by_year"]
    assert [x["revenue"] for x in r] == [1400, 1100]
    g = {x["channel"]: x["change_pct"] for x in A.get_channel_growth(model.sales)["value"]["channels"]}
    assert g == {"Website": 50.0, "Brick & Mortar": -50.0}


def test_store_trend_and_no_decline_case(model):
    v = A.get_store_trend(model.sales)["value"]
    assert v["largest_pct_decline"]["store"] == "Aville (A)" and v["largest_pct_decline"]["change_pct"] == -50.0
    v2 = A.get_store_trend(model.sales, channel="Website")
    assert v2["value"]["stores_declined"] == 0 and v2["value"]["largest_pct_decline"] is None
    assert any("No store declined" in c for c in v2["caveats"])


def test_monthly_share_denominator(model):
    v = A.get_monthly_revenue_share(model.sales)["value"]
    by = {x["month"]: x["share_pct"] for x in v["by_month"]}
    assert by["Jan"] == 12.0 and by["Dec"] == 88.0  # (100+200)/2500, (300+400+1000+500)/2500


def test_products_grouped_by_id_not_name(model):
    assert model.sales["Product Label"].nunique() == 2  # two different 'Base Model' products stay separate


def test_unknown_values_return_errors(model):
    assert "error" in A.get_revenue_summary(model.sales, store="Nowhere")
    assert "error" in A.get_revenue_summary(model.sales, year=1999)
    assert "error" in A.get_revenue_summary(model.sales, channel="carrier pigeon")


def test_satisfaction_uses_store_year_grain(model):
    v = A.get_satisfaction_vs_revenue(model.sales, model.survey)["value"]
    assert v["store_years_used"] == 2 and v["store_years_missing_satisfaction"] == 2
    sy = A.survey_store_year(model.survey, model.sales)
    assert sy["Revenue"].sum() == 2500  # aggregating before joining keeps revenue intact


def test_duplicate_dimension_key_cannot_duplicate_revenue():
    t = tiny_tables()
    t["Stores"] = pd.concat([t["Stores"], t["Stores"].iloc[[1]]])  # duplicate store A
    m = build_model(t, {})
    assert m.sales["Revenue"].sum() == 2500 and len(m.sales) == 6
    assert any("duplicate ID" in w for w in m.warnings)


def test_blank_revenue_reported_not_crashing():
    t = tiny_tables()
    t["Sales"].loc[0, "Revenue"] = None
    m = build_model(t, {})
    r = A.get_revenue_summary(m.sales)
    assert r["value"]["total_revenue"] == 2400 and any("blank" in c for c in r["caveats"])


def test_missing_column_gives_plain_message():
    from epresso.data_loader import read_any
    with pytest.raises(DataError, match="Revenue"):
        read_any("sales.csv", b"Sales ID,Date,Store ID,StoreYear,Category ID,Product ID\nS1,2025-01-31,W,W_25,C1,P1\n")


def test_check_merge_detects_duplication():
    left = pd.DataFrame({"k": [1, 2], "Revenue": [10, 20]})
    right = pd.DataFrame({"k": [1, 1, 2], "x": ["a", "b", "c"]})
    assert check_merge(left, left.merge(right, on="k"), "bad")["OK"] is False


def test_original_files_match_course_figures():
    """The bundled E-Presso files reproduce the figures printed in the Power BI walkthrough."""
    m = load()
    df = m.sales
    assert len(df) == 25200
    assert A.get_revenue_summary(df)["value"]["total_revenue"] == 42174440.0
    share = {x["month"]: x["share_pct"] for x in A.get_monthly_revenue_share(df)["value"]["by_month"]}
    assert share["Nov"] == 12.71 and share["Dec"] == 25.61


def test_sales_row_with_unknown_store_does_not_crash():
    """Regression test: a Store ID missing from Stores used to crash the store-label step."""
    t = tiny_tables()
    t["Sales"].loc[0, "Store ID"] = "ZZ"
    m = build_model(t, {})
    assert "Unknown store (ZZ)" in set(m.sales["Store"])
    assert A.get_revenue_by_channel(m.sales)["value"]["revenue"]["Unknown store"] == 100


def test_gemini_loop_uses_only_named_tools(monkeypatch):
    """Simulated Gemini responses: one function call, then a final text answer."""
    from epresso import agent as G
    m = build_model(tiny_tables(), {})
    replies = iter([
        {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "get_revenue_summary", "args": {"year": 2026, "channel": "Website"}}}]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [
            {"text": "Scope: 2026, Website.\n**Findings** Revenue was $600 and $9,999."}]}}]},
    ])
    monkeypatch.setattr(G, "_post", lambda url, payload, key, timeout=40: next(replies))
    turn = G.ask("website 2026?", m, api_key="test", model_names=["fake"], sidebar_filters={}, use_sidebar=False)
    assert turn.calls[0]["tool"] == "get_revenue_summary"
    assert turn.calls[0]["result"]["value"]["total_revenue"] == 600
    assert turn.unverified_numbers == ["$9,999"]  # invented number is flagged


def test_gemini_failure_falls_back_to_rules(monkeypatch):
    from epresso import agent as G
    m = build_model(tiny_tables(), {})

    def boom(*a, **k):
        raise G.LLMUnavailable("quota reached.")
    monkeypatch.setattr(G, "_post", boom)
    turn = G.ask("How much revenue in 2026?", m, api_key="k", model_names=["x"], sidebar_filters={}, use_sidebar=False)
    assert turn.mode == "Rules-based" and "quota" in turn.notice
    assert turn.calls and turn.calls[0]["result"]["value"]["total_revenue"] == 1100


def test_router_regressions():
    """Defects found during agent testing (see docs/AGENT_TESTS.md) stay fixed."""
    from epresso import agent as G
    m = load()
    plan = G.route_rules("How much revenue did Chicago generate in 2029?", m)
    assert plan == [("get_revenue_summary", {"year": [2029], "store": "Chicago"})]  # year was being dropped
    assert G.route_rules("What's the weather in Denver?", m) == []                  # not a business question
    assert G.route_rules("How did Orlando do?", m)[0][0] == "get_revenue_by_year"   # was 'unsupported'
