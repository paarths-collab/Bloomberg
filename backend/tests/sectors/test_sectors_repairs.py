"""Offline regression tests for the sectors router (intel refresh/latest/recommend/stocks, treemap)."""
import inspect
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.auth import create_access_token
from backend.main import app
from backend.sectors import intel_service, main as sectors_main
from backend.sectors.service import sectors_service


@pytest.fixture
def api():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth():
    return {"Authorization": "Bearer " + create_access_token("sector-repairs-user")[0]}


@pytest.fixture
def us_sector():
    return intel_service.get_sector_list("US")[0]


# ---- 1. refresh: auth, single sector, whitelist, no sleeping ----

def test_refresh_requires_authentication(api, us_sector):
    r = api.post("/api/sectors/intel/refresh", json={"market": "US", "sector": us_sector})
    assert r.status_code == 401


@pytest.mark.parametrize("body", [
    {},                                                        # refresh-all is not allowed
    {"market": "US"},                                          # sector missing
    {"sector": "Technology"},                                  # market missing
    {"sector": 5, "market": "US"},                             # non-string sector
    {"sector": "", "market": "US"},
    {"sector": "Definitely Not A Sector", "market": "US"},     # not in whitelist
    {"sector": "Technology", "market": "ZZ"},                  # unknown market
    {"sector": "Technology", "market": 5},
    {"sector": ["a"], "market": "US"},
])
def test_refresh_rejects_invalid_requests_without_touching_db(api, auth, monkeypatch, body):
    def boom(*a, **k):
        raise AssertionError("refresh_sector must not run for an invalid request")
    monkeypatch.setattr(sectors_main, "refresh_sector", boom)
    r = api.post("/api/sectors/intel/refresh", json=body, headers=auth)
    assert r.status_code == 400, (body, r.status_code, r.text)


def test_refresh_force_must_be_boolean_and_whitelist_still_applies(api, auth, monkeypatch, us_sector):
    monkeypatch.setattr(sectors_main, "refresh_sector", lambda *a, **k: {"status": "ok"})
    assert api.post("/api/sectors/intel/refresh", json={"market": "US", "sector": us_sector, "force": "yes"}, headers=auth).status_code == 400
    # force does not bypass the whitelist
    r = api.post("/api/sectors/intel/refresh", json={"market": "US", "sector": "Nope", "force": True}, headers=auth)
    assert r.status_code == 400


def test_refresh_single_sector_uses_canonical_names_and_never_sleeps(api, auth, monkeypatch, us_sector):
    calls = []

    def fake_refresh(db, sector, market, force=False):
        calls.append((sector, market, force))
        return {"status": "ok", "sector": sector, "market": market}

    def no_sleep(*a, **k):
        raise AssertionError("no sleeping in the request path")

    monkeypatch.setattr(sectors_main, "refresh_sector", fake_refresh)
    monkeypatch.setattr(intel_service.time, "sleep", no_sleep)
    assert not hasattr(sectors_main, "refresh_all_sectors")
    r = api.post("/api/sectors/intel/refresh",
                 json={"market": "us", "sector": us_sector.upper(), "force": True}, headers=auth)
    assert r.status_code == 200, r.text
    assert calls == [(us_sector, "US", True)]


# ---- 3. market case handling ----

def _delete_snapshots(sector):
    from backend.database.connection import get_db_session
    from backend.database.models import SectorSnapshot
    with get_db_session() as db:
        db.query(SectorSnapshot).filter(SectorSnapshot.sector == sector).delete()
        db.commit()


def _add_snapshot(sector, market="US", score=50.0):
    from backend.database.connection import get_db_session
    from backend.database.models import SectorSnapshot
    _delete_snapshots(sector)
    with get_db_session() as db:
        db.add(SectorSnapshot(sector=sector, market=market, as_of=datetime.now(timezone.utc), score=score,
                              sector_summary="s", llm_model="test"))
        db.commit()


def test_latest_and_recommend_are_case_insensitive_on_market(api):
    sector = "Repairs Case Sector"
    _add_snapshot(sector, "US", 77.0)
    try:  # shared test DB: remove the row so other tests' empty-recommendation assertions hold
        upper = [r for r in api.get("/api/sectors/intel/latest?market=US").json() if r["sector"] == sector]
        lower = [r for r in api.get("/api/sectors/intel/latest?market=us").json() if r["sector"] == sector]
        assert len(upper) == 1 and lower == upper
        for market in ("US", "us", "Us"):
            rec = api.post("/api/sectors/intel/recommend", json={"market": market, "limit": 50}).json()
            assert any(r["sector"] == sector for r in rec), market
    finally:
        _delete_snapshots(sector)


def test_latest_unknown_market_is_400(api):
    assert api.get("/api/sectors/intel/latest?market=zz").status_code == 400


@pytest.mark.parametrize("body", [
    {"limit": "x"},
    {"market": 5},
    {"risk_score": "abc"},
    {"limit": 0},
    {"limit": 10 ** 12},
    {"limit": True},
    {"risk_score": 1000},
    {"market": "ZZ"},
])
def test_recommend_bad_payloads_are_400_not_500(api, body):
    r = api.post("/api/sectors/intel/recommend", json=body)
    assert r.status_code == 400, (body, r.status_code, r.text)


def test_recommend_accepts_valid_numeric_payload(api):
    r = api.post("/api/sectors/intel/recommend", json={"market": "US", "limit": "3", "risk_score": 40})
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_recommend_non_object_body_is_422(api):
    assert api.post("/api/sectors/intel/recommend", json=[1]).status_code == 422


# ---- stocks: bounded limit, sanitized info ----

@pytest.mark.parametrize("limit", [0, -1, 51, 10 ** 20])
def test_stocks_limit_is_bounded(api, limit):
    assert api.get(f"/api/sectors/intel/stocks/Technology?limit={limit}").status_code == 422


def test_stocks_unknown_market_is_400(api):
    assert api.get("/api/sectors/intel/stocks/Technology?market=ZZ").status_code == 400


def test_stocks_sanitizes_non_finite_values(api, monkeypatch):
    monkeypatch.setattr(sectors_main, "get_sector_constituents", lambda *a, **k: [{"symbol": "AAPL"}])
    monkeypatch.setattr(sectors_main.market_service, "get_fundamentals",
                        lambda s: {"trailingPE": float("nan"), "beta": float("inf"), "marketCap": 5, "nested": {"x": float("-inf")}})
    r = api.get("/api/sectors/intel/stocks/Technology?include_technicals=false")
    assert r.status_code == 200, r.text
    f = r.json()["stocks"][0]["fundamentals"]
    assert f["trailingPE"] is None and f["beta"] is None and f["nested"]["x"] is None and f["marketCap"] == 5


# ---- treemap market whitelist / cache bound ----

def test_treemap_unknown_market_is_400_and_lists_supported(api):
    for path in ("/api/sectors/treemap/indices?market=zz", "/api/sectors/treemap/indices/live?market=zz",
                 "/api/sectors/treemap/index/x?market=zz"):
        r = api.get(path)
        assert r.status_code == 400, path
        assert "india" in r.json()["detail"] and "us" in r.json()["detail"]


def test_treemap_supported_markets_still_work(api):
    for market in ("us", "US", "india"):
        r = api.get(f"/api/sectors/treemap/indices?market={market}")
        assert r.status_code == 200 and r.json()["count"] > 0, market


def test_market_indices_cache_keys_are_bounded():
    for junk in ("zz", "A" * 5000, "../x", "", "us "):
        sectors_service._get_market_indices(junk)
    assert set(sectors_service._market_indices_cache) <= {"india", "us"}
    assert sectors_service._get_market_indices("zz") == []


# ---- 2. blocking routes are not async ----

@pytest.mark.parametrize("name", ["get_indices", "get_indices_live", "get_index_stocks"])
def test_blocking_sector_routes_are_sync_defs(name):
    assert not inspect.iscoroutinefunction(getattr(sectors_main, name))
