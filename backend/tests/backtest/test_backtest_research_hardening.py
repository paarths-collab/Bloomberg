"""Input validation / report-file hardening for /api/backtest and /api/research (offline, monkeypatched)."""
import os
import re
import sys
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.backtest import main as bt_main
from backend.backtest import service
from backend.backtest.core.strategy_adapter import STRATEGY_REGISTRY
from backend.research import main as rs_main

XSS = "<img src=x onerror=alert(1)>"
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(bt_main.router, prefix="/api/backtest")
    app.include_router(rs_main.router, prefix="/api/research")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def backtest_reports(tmp_path, monkeypatch):
    """Point both the generator (service) and the download route at a temp reports dir."""
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(service, "__file__", str(tmp_path / "service.py"))
    monkeypatch.setattr(bt_main, "REPORTS_DIR", reports)
    return reports


@pytest.fixture
def research_reports(tmp_path, monkeypatch):
    reports = tmp_path / "research_reports"
    reports.mkdir()
    monkeypatch.setattr(rs_main, "REPORTS_DIR", reports)
    return reports


@pytest.fixture
def candles(monkeypatch, long_candles):
    monkeypatch.setattr(bt_main, "fetch_candles", lambda *a, **k: [dict(c) for c in long_candles])
    monkeypatch.setattr(service, "_fetch_candles_with_fallback", lambda **k: [dict(c) for c in long_candles])
    return long_candles


def _fake_qs(monkeypatch, calls=None):
    def html(returns, benchmark=None, output=None, title=None, download_filename=None, **kw):
        if calls is not None:
            calls.append({"returns": returns, "benchmark": benchmark, "output": output, "title": title})
        with open(output, "w", encoding="utf-8") as f:
            f.write("<html><title>%s</title></html>" % title)

    monkeypatch.setitem(sys.modules, "quantstats", SimpleNamespace(reports=SimpleNamespace(html=html)))


# ---------------------------------------------------------------------------
# 1. /heatmap
# ---------------------------------------------------------------------------

def _heatmap(client, **extra):
    return client.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": "sma_crossover", **extra})


@pytest.fixture
def fast_engine(monkeypatch, candles):
    calls = []

    def fake(df, strategy, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame({"equity": [100000.0, 101000.0]})

    monkeypatch.setattr(bt_main, "run_backtest_on_df", fake)
    return calls


def test_heatmap_cell_cap(client, fast_engine):
    ok = _heatmap(client, x_values=list(range(5, 15)), y_values=list(range(20, 30)))  # 100 cells
    assert ok.status_code == 200, ok.text
    assert len(fast_engine) == 100
    fast_engine.clear()
    too_many = _heatmap(client, x_values=list(range(5, 16)), y_values=list(range(20, 29)))  # 99 -> ok
    assert too_many.status_code == 200
    fast_engine.clear()
    r = _heatmap(client, x_values=list(range(10)), y_values=list(range(11)))  # 110 cells
    assert r.status_code == 400
    assert "100" in r.json()["detail"] and "too large" in r.json()["detail"]
    r = _heatmap(client, x_values=list(range(1000)), y_values=list(range(1000)))
    assert r.status_code == 400
    assert fast_engine == []  # nothing was computed for the rejected grids


@pytest.mark.parametrize("bad", [[None], ["a"], [True], [[1]], [{"a": 1}], [], "5", 5, None])
def test_heatmap_values_must_be_finite_numbers(client, fast_engine, bad):
    for key in ("x_values", "y_values"):
        other = {"y_values" if key == "x_values" else "x_values": [20, 30]}
        r = _heatmap(client, **{key: bad}, **other)
        assert r.status_code == 400, (key, bad, r.text)


def test_heatmap_rejects_non_finite_and_bad_types(client, fast_engine):
    r = client.post(
        "/api/backtest/heatmap", headers={"content-type": "application/json"},
        content='{"symbol":"TEST","strategy":"sma_crossover","x_values":[NaN],"y_values":[Infinity]}',
    )
    assert r.status_code == 400
    assert _heatmap(client, x_values=[5], y_values=[20], param_x=["fast"]).status_code == 400
    assert client.post("/api/backtest/heatmap", json={"symbol": "TEST", "strategy": ["macd"]}).status_code == 400
    assert client.post("/api/backtest/heatmap", json={"symbol": ["A"], "strategy": "macd"}).status_code == 400


def test_heatmap_overridden_param_names_do_not_500_on_the_fast_slow_comparison(client, fast_engine):
    r = client.post("/api/backtest/heatmap", json={
        "symbol": "TEST", "strategy": "macd", "param_x": "signal", "param_y": "signal",
        "x_values": [5, 9], "y_values": [9],
    })
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 2. /run
# ---------------------------------------------------------------------------

def test_run_dedupes_and_caps_strategies(client, candles, monkeypatch):
    seen = {}
    real_single, real_multi = service.run_backtest_service, service.run_multi_strategy_backtest

    def spy_single(**kw):
        seen["single"] = kw["strategy_name"]
        return real_single(**kw)

    def spy_multi(**kw):
        seen["multi"] = kw["strategy_names"]
        return real_multi(**kw)

    monkeypatch.setattr(bt_main, "run_backtest_service", spy_single)
    monkeypatch.setattr(bt_main, "run_multi_strategy_backtest", spy_multi)

    r = client.post("/api/backtest/run", json={"symbol": "T", "strategies": ["sma_crossover"] * 40})
    assert r.status_code == 200, r.text
    assert seen == {"single": "sma_crossover"}  # 40 copies are one run

    seen.clear()
    r = client.post("/api/backtest/run", json={
        "symbol": "T", "strategies": ["sma_crossover", " SMA_Crossover", "ema_crossover", "sma_crossover"],
    })
    assert r.status_code == 200, r.text
    assert seen == {"multi": ["sma_crossover", "ema_crossover"]}
    assert set(r.json()["strategies"]) == {"sma_crossover", "ema_crossover"}

    names = list(STRATEGY_REGISTRY)[:6]
    assert len(names) == 6
    seen.clear()
    r = client.post("/api/backtest/run", json={"symbol": "T", "strategies": names[:5]})
    assert r.status_code == 200 and seen["multi"] == names[:5]
    seen.clear()
    r = client.post("/api/backtest/run", json={"symbol": "T", "strategies": names})
    assert r.status_code == 400 and "5" in r.json()["detail"] and not seen
    r = client.post("/api/backtest/run", json={"symbol": "T", "strategies": names + names * 20})
    assert r.status_code == 400 and not seen
    assert client.post("/api/backtest/run", json={"symbol": "T", "strategies": "macd"}).status_code == 400
    assert client.post("/api/backtest/run", json={"symbol": "T", "strategies": ["macd", ""]}).status_code == 400


@pytest.mark.parametrize("symbol", [5, ["A"], {"a": 1}, "", "   ", True])
def test_run_symbol_must_be_a_non_empty_string(client, candles, symbol):
    r = client.post("/api/backtest/run", json={"symbol": symbol, "strategy": "sma_crossover"})
    assert r.status_code == 400, r.text


def test_run_market_must_be_a_string(client, candles):
    for market in (5, ["us"], {"a": 1}):
        r = client.post("/api/backtest/run", json={"symbol": "T", "strategy": "sma_crossover", "market": market})
        assert r.status_code == 400, (market, r.text)


@pytest.mark.parametrize("strategy,params", [
    ("sma_crossover", {"fast_period": -5}),
    ("ema_crossover", {"fast_period": -5}),
    ("rsi_reversal", {"window": -3}),
    ("breakout", {"lookback": -1}),
])
def test_run_bad_window_params_are_a_400_not_an_internal_error(client, candles, strategy, params):
    r = client.post("/api/backtest/run", json={"symbol": "T", "strategy": strategy, "params": params})
    assert r.status_code == 400, r.text
    assert "Invalid parameters" in r.json()["detail"]
    assert "span" not in r.json()["detail"] and "integer 0 or greater" not in r.json()["detail"]


def test_run_bad_window_params_in_multi_mode_are_reported_per_strategy(client, candles):
    r = client.post("/api/backtest/run", json={
        "symbol": "T", "strategies": ["sma_crossover", "ema_crossover"],
        "params": {"sma_crossover": {"fast_period": -5}, "ema_crossover": {"fast": 8, "slow": 21}},
    })
    assert r.status_code == 200, r.text
    body = r.json()["strategies"]
    assert body["sma_crossover"]["metrics"] is None and "Invalid parameters" in body["sma_crossover"]["error"]
    assert body["ema_crossover"]["metrics"]


# ---------------------------------------------------------------------------
# 3. /report
# ---------------------------------------------------------------------------

def _report(client, **payload):
    return client.post("/api/backtest/report", json=payload)


def test_report_bad_result_types_are_400(client, backtest_reports):
    assert _report(client, symbol="T", results=[]).status_code == 400
    assert _report(client, symbol="T", results="x").status_code == 400
    assert _report(client, symbol="T", results={"metrics": {"totalReturn": "abc"}}).status_code == 400
    assert _report(client, symbol="T", results={"metrics": []}).status_code == 400
    assert _report(client, symbol="T", results={"metrics": {"finalEquity": "1"}}, format="csv").status_code == 400
    assert _report(client, symbol="T", results={"initialCapital": "x"}).status_code == 400
    multi = {"mode": "multi_strategy", "strategies": {"a": {"metrics": {"sharpeRatio": "z"}}}}
    assert _report(client, symbol="T", results=multi).status_code == 400
    assert _report(client, symbol="T", results={"mode": "multi_strategy", "strategies": []}).status_code == 400
    assert _report(client, symbol="T", results={"mode": "multi_strategy", "ranking": [{"strategy": "a"}]}).status_code == 400
    assert _report(client, symbol=5).status_code == 400
    assert _report(client, symbol="T", strategies="macd").status_code == 400
    assert _report(client, symbol="T", strategies=[1]).status_code == 400
    assert list(backtest_reports.iterdir()) == []  # nothing generated for rejected requests


def test_report_null_or_missing_metrics_are_not_shown_as_zero(client, backtest_reports):
    import csv, io
    metrics = {"sharpeRatio": None, "totalReturn": 1.5, "maxDrawdown": 0.0, "totalTrades": 0}
    # CSV: null/missing -> empty cell; a real 0 stays 0
    r = _report(client, symbol="T", results={"metrics": metrics}, format="csv")
    assert r.status_code == 200, r.text
    rows = {row[0]: row[1:] for row in csv.reader(io.StringIO(client.get(r.json()["downloadUrl"]).text)) if row}
    assert rows["Sharpe Ratio"] == [""] and rows["Win Rate"] == [""] and rows["Final Equity"] == [""]
    assert rows["Total Return"] == ["1.5%"] and rows["Max Drawdown"] == ["0.0%"] and rows["Total Trades"] == ["0"]
    # HTML: null/missing -> N/A (also for initial capital); a real 0 stays 0
    r = _report(client, symbol="T", results={"metrics": metrics}, format="html")
    assert r.status_code == 200, r.text
    body = client.get(r.json()["downloadUrl"]).text
    cells = dict(re.findall(r'<span class="label">([^<]+)</span><span class="value[^"]*">([^<]*)</span>', body))
    assert cells["Sharpe Ratio"] == "N/A" and cells["Win Rate"] == "N/A" and cells["Final Value"] == "N/A"
    assert cells["Total Return"] == "1.5%" and cells["Max Drawdown"] == "0.0%" and cells["Total Trades"] == "0"
    assert 'meta-value">N/A<' in body and "$100,000" not in body
    # nothing at all -> every metric N/A, no 0 anywhere
    r = _report(client, symbol="T", results={"metrics": {"totalReturn": None}}, format="html")
    body = client.get(r.json()["downloadUrl"]).text
    cells = dict(re.findall(r'<span class="label">([^<]+)</span><span class="value[^"]*">([^<]*)</span>', body))
    assert set(cells.values()) == {"N/A"} and len(cells) == 6 and 'meta-value">N/A<' in body


def test_multi_strategy_report_null_metrics_render_na_and_empty(client, backtest_reports):
    import csv, io
    multi = {"mode": "multi_strategy", "initialCapital": 5000,
             "strategies": {"a": {"metrics": {"totalReturn": None, "maxDrawdown": 2.5, "sharpeRatio": None,
                                              "totalTrades": 3, "finalEquity": None}}},
             "ranking": []}
    r = _report(client, symbol="T", results=multi, format="html")
    body = client.get(r.json()["downloadUrl"]).text
    row = re.search(r"<td><strong>a</strong></td>(.*?)</tr>", body, re.S).group(1)
    assert re.findall(r"<td[^>]*>([^<]*)</td>", row) == ["N/A", "2.50%", "N/A", "3", "N/A"]
    assert "$5,000.00" in body
    r = _report(client, symbol="T", results=multi, format="csv")
    rows = list(csv.reader(io.StringIO(client.get(r.json()["downloadUrl"]).text)))
    assert ["a", "", "2.5", "", "3", ""] in rows


def test_report_format_pdf_and_unknown_are_400(client, backtest_reports):
    for fmt in ("pdf", "PDF", "xml", "", None, 5, ["html"]):
        r = _report(client, symbol="T", results={}, format=fmt)
        assert r.status_code == 400, (fmt, r.text)
        assert "format" in r.json()["detail"]
    assert list(backtest_reports.iterdir()) == []
    assert _report(client, symbol="T", results={}, format="HTML").status_code == 200
    assert _report(client, symbol="T", results={}).status_code == 200  # default stays html


def test_generate_backtest_report_service_rejects_pdf():
    with pytest.raises(service.BacktestInputError):
        service.generate_backtest_report("T", [], {}, "pdf")


def test_csv_report_escapes_formula_injection(client, backtest_reports):
    evil = "=HYPERLINK(\"http://x\")"
    multi = {
        "mode": "multi_strategy",
        "strategies": {"+cmd": {"metrics": {"totalReturn": -3.5, "totalTrades": 2}}},
        "ranking": [{"strategy": "@SUM(1)", "return": -3.5}],
    }
    r = _report(client, symbol=evil, strategies=["-1+1", "ok"], results=multi, format="csv")
    assert r.status_code == 200, r.text
    text = client.get(r.json()["downloadUrl"]).text
    import csv, io
    rows = list(csv.reader(io.StringIO(text)))
    flat = [cell for row in rows for cell in row]
    assert "'" + evil in flat
    assert "'-1+1, ok" in flat
    assert "'+cmd" in flat and "'@SUM(1)" in flat
    assert evil not in flat and "+cmd" not in flat
    assert "-3.5" in flat  # numeric cells are untouched
    for cell in ("\tx", "\rx"):
        assert service.csv_safe(cell) == "'" + cell
    assert service.csv_safe("AAPL") == "AAPL" and service.csv_safe(-5) == -5


def test_xss_symbol_is_sanitised_in_backtest_report_filename_and_html(client, backtest_reports):
    r = _report(client, symbol=XSS, strategies=[XSS], results={}, format="html")
    assert r.status_code == 200, r.text
    name = r.json()["filename"]
    assert "<" not in name and ">" not in name and "=" not in name and service.REPORT_FILENAME_RE.match(name)
    body = client.get(r.json()["downloadUrl"]).text
    assert "<img" not in body and "&lt;img" in body
    assert [p.name for p in backtest_reports.iterdir()] == [name]


def test_generated_report_names_always_pass_the_download_validation(client, backtest_reports):
    for sym in ("^NSEI", "A=B", "a..b", "AAPL.NS", "..", "x" * 500):
        r = _report(client, symbol=sym, results={}, format="csv")
        assert r.status_code == 200, (sym, r.text)
        assert client.get(r.json()["downloadUrl"]).status_code == 200, sym


# ---------------------------------------------------------------------------
# 4. /interpret-image
# ---------------------------------------------------------------------------

class _FakeGroq:
    calls = []

    def generate_vision_response(self, **kw):
        _FakeGroq.calls.append(kw)
        return "analysis text"


def _image(client, **extra):
    payload = {"symbol": "AAPL", "imageDataUrl": "data:image/png;base64,AAAA", **extra}
    return client.post("/api/backtest/interpret-image", json=payload)


def test_interpret_image_types_are_400(client, monkeypatch):
    monkeypatch.setattr(bt_main, "GroqAgent", _FakeGroq)
    _FakeGroq.calls.clear()
    for extra in (
        {"selectedStrategies": [1]}, {"selectedStrategies": "macd"}, {"selectedStrategies": {"a": 1}},
        {"context": "str"}, {"context": [1]}, {"market": 5},
    ):
        r = _image(client, **extra)
        assert r.status_code == 400, (extra, r.text)
    assert client.post("/api/backtest/interpret-image", json={
        "symbol": ["A"], "imageDataUrl": "data:image/png;base64,AAAA"}).status_code == 400
    assert client.post("/api/backtest/interpret-image", json={"symbol": "A", "imageDataUrl": 5}).status_code == 400
    assert _FakeGroq.calls == []
    r = _image(client, selectedStrategies=["macd", "sma_crossover"], context={"range": "1y"})
    assert r.status_code == 200 and r.json()["analysis"] == "analysis text"
    assert "macd, sma_crossover" in _FakeGroq.calls[0]["prompt"]


SECRET = "gsk_SECRET_provider_key_123 rate limit for org-77"


class _FailingGroq:
    def generate_response(self, **kw):
        return "Error: " + SECRET

    def generate_vision_response(self, **kw):
        return "Error: " + SECRET


def test_interpret_provider_errors_are_generic_and_logged(client, monkeypatch, caplog):
    monkeypatch.setattr(bt_main, "GroqAgent", _FailingGroq)
    caplog.set_level("WARNING", logger=bt_main.logger.name)
    r = _image(client, imageModel="llama-3.2-11b-vision-preview")
    assert r.status_code == 502
    assert "SECRET" not in r.text and "org-77" not in r.text and "Last model" not in r.text
    assert "SECRET" in caplog.text  # kept server-side
    r = client.post("/api/backtest/interpret", json={
        "symbol": "AAPL", "selectedStrategies": ["macd"], "summary": {"range": "1y"}})
    assert r.status_code == 502, r.text
    assert "SECRET" not in r.text and "org-77" not in r.text


# ---------------------------------------------------------------------------
# 5. /quantstats-report
# ---------------------------------------------------------------------------

def test_quantstats_symbol_must_be_a_string(client, candles):
    for symbol in (["AAPL"], 5, {"a": 1}):
        r = client.post("/api/backtest/quantstats-report", json={"symbol": symbol, "strategy": "sma_crossover"})
        assert r.status_code == 400, (symbol, r.text)
    r = client.post("/api/backtest/quantstats-report", json={
        "symbol": "T", "strategy": "sma_crossover", "benchmark": ["SPY"]})
    assert r.status_code == 400


def test_quantstats_benchmark_provider_failure_is_a_generic_502(client, long_candles, monkeypatch, backtest_reports):
    def fetch(symbol, *a, **k):
        if symbol == "SPY":
            raise service.MarketDataError("boom: secret provider detail")
        return [dict(c) for c in long_candles]

    monkeypatch.setattr(bt_main, "fetch_candles", fetch)
    _fake_qs(monkeypatch)
    r = client.post("/api/backtest/quantstats-report", json={"symbol": "T", "strategy": "sma_crossover"})
    assert r.status_code == 502, r.text
    assert r.json()["detail"] == bt_main.MARKET_DATA_UNAVAILABLE and "secret" not in r.text
    assert list(backtest_reports.iterdir()) == []


def test_quantstats_report_passes_the_fetched_benchmark_and_a_clean_title(client, candles, monkeypatch, backtest_reports):
    calls = []
    _fake_qs(monkeypatch, calls)
    r = client.post("/api/backtest/quantstats-report", json={
        "symbol": XSS, "strategy": "sma_crossover", "benchmark": "^GSPC", "params": {"fast": 5, "slow": 20}})
    assert r.status_code == 200, r.text
    name = r.json()["filename"]
    assert service.REPORT_FILENAME_RE.match(name) and "<" not in name and ".." not in name
    assert "<" not in calls[0]["title"] and ">" not in calls[0]["title"]
    assert isinstance(calls[0]["benchmark"], pd.Series) and len(calls[0]["benchmark"]) > 100
    assert client.get("/api" + r.json()["downloadUrl"]).status_code == 200


# ---------------------------------------------------------------------------
# 6. downloads (backtest + research)
# ---------------------------------------------------------------------------

BAD_NAMES = ["..", ".", "..\\x", "a" * 5000, ".hidden.html", "a..b.html", "a b.html", "a%00.html", "x" * 121 + ".html"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_backtest_download_rejects_unsafe_names(client, backtest_reports, name):
    (backtest_reports.parent / "secret.html").write_text("secret")
    r = client.get("/api/backtest/report/download/" + name.replace("\\", "%5C"))
    assert r.status_code != 200 and "secret" not in r.text
    with pytest.raises(Exception) as exc:
        bt_main.download_report(name)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.parametrize("name", BAD_NAMES)
def test_research_download_rejects_unsafe_names(client, research_reports, name):
    (research_reports.parent / "secret.html").write_text("secret")
    r = client.get("/api/research/report/download/" + name.replace("\\", "%5C"))
    assert "secret" not in r.text and r.status_code != 200
    with pytest.raises(Exception) as exc:
        rs_main.download_research_report(name)
    assert getattr(exc.value, "status_code", None) == 404


def test_encoded_traversal_is_404(client, backtest_reports, research_reports):
    (backtest_reports.parent / "secret.html").write_text("secret")
    (research_reports.parent / "secret.html").write_text("secret")
    assert client.get("/api/backtest/report/download/%2e%2e%2fsecret.html").status_code == 404
    assert client.get("/api/research/report/download/%2e%2e%2fsecret.html").status_code == 404


def test_download_requires_a_regular_file_inside_the_reports_dir(client, backtest_reports, research_reports, tmp_path):
    outside = tmp_path / "outside.html"
    outside.write_text("secret")
    for reports, prefix in ((backtest_reports, "backtest"), (research_reports, "research")):
        (reports / "link.html").symlink_to(outside)
        (reports / "folder.html").mkdir()
        assert client.get(f"/api/{prefix}/report/download/link.html").status_code == 404
        assert client.get(f"/api/{prefix}/report/download/folder.html").status_code == 404
        assert client.get(f"/api/{prefix}/report/download/missing.html").status_code == 404


def test_valid_downloads_and_security_headers(client, backtest_reports, research_reports):
    (backtest_reports / "ok_1.html").write_text("<p>hi</p>")
    (backtest_reports / "ok_1.csv").write_text("a,b\n")
    (research_reports / "ok_2.html").write_text("<p>hi</p>")
    for url in ("/api/backtest/report/download/ok_1.html", "/api/research/report/download/ok_2.html"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["content-security-policy"] == CSP
        assert r.headers["x-content-type-options"] == "nosniff"
    r = client.get("/api/backtest/report/download/ok_1.csv")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")


# ---------------------------------------------------------------------------
# 6b. sanitised research symbol, 7. research input types, sweep
# ---------------------------------------------------------------------------

def _research_prices():
    idx = pd.bdate_range("2024-01-02", periods=60)
    return pd.DataFrame({"Close": np.linspace(100, 130, 60)}, index=idx)


def test_research_report_input_types_are_400(client, research_reports, monkeypatch):
    monkeypatch.setattr(rs_main.market_service, "get_history", lambda *a, **k: _research_prices())
    _fake_qs(monkeypatch)
    for extra in ({"symbol": 5}, {"symbol": ["A"]}, {"symbol": "A", "market": 5}, {"symbol": "A", "market": ["in"]},
                  {"symbol": "A", "benchmark": 5}, {"symbol": "A", "range": 5}, {"symbol": "  "}):
        r = client.post("/api/research/report", json=extra)
        assert r.status_code == 400, (extra, r.text)
    assert list(research_reports.iterdir()) == []
    assert client.post("/api/research/report", json={"symbol": "A", "market": "india"}).status_code == 200


def test_research_report_symbol_is_sanitised(client, research_reports, monkeypatch):
    monkeypatch.setattr(rs_main.market_service, "get_history", lambda *a, **k: _research_prices())
    calls = []
    _fake_qs(monkeypatch, calls)
    r = client.post("/api/research/report", json={"symbol": XSS})
    assert r.status_code == 200, r.text
    name = r.json()["filename"]
    assert rs_main.REPORT_FILENAME_RE.match(name) and ".." not in name
    assert "<" not in calls[0]["title"] and ">" not in calls[0]["title"]
    assert client.get(r.json()["downloadUrl"].replace("/research", "/api/research", 1)).status_code == 200


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_service_sweep_deletes_old_and_beyond_count(tmp_path):
    old = tmp_path / "old.html"
    old.write_text("x")
    _age(old, 25 * 3600)
    keep_me = tmp_path / ".gitkeep"
    keep_me.write_text("")
    _age(keep_me, 99 * 3600)
    other = tmp_path / "notes.txt"
    other.write_text("x")
    _age(other, 99 * 3600)
    for i in range(205):
        p = tmp_path / f"r{i:03d}.csv"
        p.write_text("x")
        _age(p, 1000 - i)  # r000 oldest ... r204 newest
    removed = service.sweep_reports(tmp_path)
    left = sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".csv")
    assert removed == 6 and len(left) == 200
    assert left[0] == "r005.csv" and left[-1] == "r204.csv"  # the 5 oldest went
    assert not old.exists() and keep_me.exists() and other.exists()
    assert service.sweep_reports(tmp_path / "does-not-exist") == 0  # never raises


def test_report_generation_sweeps_the_reports_dir(client, backtest_reports, research_reports, monkeypatch):
    stale = backtest_reports / "stale.html"
    stale.write_text("x")
    _age(stale, 30 * 3600)
    fresh = backtest_reports / "fresh.html"
    fresh.write_text("x")
    r = _report(client, symbol="T", results={}, format="html")
    assert r.status_code == 200
    assert not stale.exists() and fresh.exists() and (backtest_reports / r.json()["filename"]).exists()

    stale = research_reports / "stale.html"
    stale.write_text("x")
    _age(stale, 30 * 3600)
    for i in range(205):
        p = research_reports / f"r{i:03d}.html"
        p.write_text("x")
        _age(p, 1000 - i)
    monkeypatch.setattr(rs_main.market_service, "get_history", lambda *a, **k: _research_prices())
    _fake_qs(monkeypatch)
    r = client.post("/api/research/report", json={"symbol": "AAPL"})
    assert r.status_code == 200
    files = list(research_reports.iterdir())
    assert not stale.exists() and len(files) == 200
    assert (research_reports / r.json()["filename"]).exists()


# ---------------------------------------------------------------------------
# 8. _sanitize_floats
# ---------------------------------------------------------------------------

def test_sanitize_floats_keeps_bools_as_bools():
    out = bt_main._sanitize_floats({"a": True, "b": False, "c": np.bool_(True), "d": [True, 1, 1.5], "e": float("nan")})
    assert out["a"] is True and out["b"] is False and out["c"] is True
    assert out["d"][0] is True and out["d"][1] == 1 and type(out["d"][1]) is int and out["d"][2] == 1.5
    assert out["e"] is None
