"""Offline regression tests for FRED routes: input validation, auth on writes, malformed caches."""
import inspect
import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from backend.auth import create_access_token
from backend.main import app
from backend.markets import fred_routes
from backend.markets.fred_service import FredDataService


@pytest.fixture
def api():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth():
    return {"Authorization": "Bearer " + create_access_token("fred-repairs-user")[0]}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect the routes' cache directory (parents[1]/cache) into tmp_path."""
    fake = tmp_path / "markets" / "fred_routes.py"
    fake.parent.mkdir()
    monkeypatch.setattr(fred_routes, "__file__", str(fake))
    d = tmp_path / "cache"
    d.mkdir()
    return d


# ---- sync writes require auth ----

@pytest.mark.parametrize("path,body", [
    ("/api/fred/sync/series", {"series_id": "GDP"}),
    ("/api/fred/sync/indices", {}),
    ("/api/fred/sync/rates", {}),
    ("/api/fred/sync/all", {}),
])
def test_sync_requires_auth_and_never_reaches_service(api, monkeypatch, path, body):
    def boom(self, *a, **k):
        raise AssertionError("unauthenticated request reached the provider/DB")
    for name in ("fetch_and_store_series", "sync_all_indices", "sync_all_rates", "sync_all"):
        monkeypatch.setattr(FredDataService, name, boom)
    assert api.post(path, json=body).status_code == 401
    assert api.post(path, json=body, headers={"Authorization": "Bearer junk"}).status_code == 401


def test_sync_days_are_bounded_with_400(api, auth, monkeypatch):
    monkeypatch.setattr(FredDataService, "sync_all", lambda self, days=365: {"indices": [], "rates": []})
    for days in (0, -5, 3651, 10 ** 15):
        for path in ("/api/fred/sync/indices", "/api/fred/sync/rates", "/api/fred/sync/all"):
            r = api.post(path, json={"days": days}, headers=auth)
            assert r.status_code == 400, (path, days, r.status_code, r.text)
        r = api.post("/api/fred/sync/series", json={"series_id": "GDP", "days": days}, headers=auth)
        assert r.status_code == 400, (days, r.status_code)
    assert api.post("/api/fred/sync/all", json={"days": 3650}, headers=auth).status_code == 200


def test_sync_series_validates_id_and_type(api, auth, monkeypatch):
    monkeypatch.setattr(FredDataService, "fetch_and_store_series", lambda self, *a, **k: {"status": "success"})
    assert api.post("/api/fred/sync/series", json={"series_id": "../x"}, headers=auth).status_code == 422
    assert api.post("/api/fred/sync/series", json={"series_id": "GDP", "series_type": "junk"}, headers=auth).status_code == 400
    assert api.post("/api/fred/sync/series", json={"series_id": "GDP", "series_type": "economic"}, headers=auth).status_code == 200


# ---- read validation ----

def test_series_bad_dates_are_400(api):
    assert api.get("/api/fred/series/GDP?start_date=abc").status_code == 400
    assert api.get("/api/fred/series/GDP?end_date=2024-13-45").status_code == 400
    assert api.get("/api/fred/series/GDP?start_date=2024-02-01&end_date=2024-01-01").status_code == 400
    assert api.get("/api/fred/series/GDP?start_date=2024-01-01&end_date=2024-02-01").status_code == 200


def test_series_limit_must_be_positive_and_does_not_drop_last_row(api):
    from backend.database.connection import get_db_session
    from backend.database.fred_repository import FredRepository
    with get_db_session() as db:
        repo = FredRepository(db)
        for i in (1, 2, 3):
            repo.upsert_data("REPAIR_LIM", "economic", date(2024, i, 1), i)
        db.commit()
    for bad in (-1, 0, 10 ** 12):
        assert api.get(f"/api/fred/series/REPAIR_LIM?limit={bad}").status_code == 422, bad
    assert api.get("/api/fred/series/REPAIR_LIM").json()["count"] == 3
    assert api.get("/api/fred/series/REPAIR_LIM?limit=2").json()["count"] == 2


def test_series_id_path_params_are_validated(api):
    for path in ("/api/fred/series/bad%20id", "/api/fred/series/bad%20id/latest", "/api/fred/smart/bad%20id",
                 "/api/fred/series/" + "A" * 65):
        assert api.get(path).status_code == 422, path


@pytest.mark.parametrize("path", ["/api/fred/latest", "/api/fred/latest-live", "/api/fred/latest-cached"])
def test_series_id_lists_are_validated_and_capped(api, monkeypatch, path):
    monkeypatch.setattr(FredDataService, "fetch_series", lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider called")))
    too_many = ",".join(f"S{i}" for i in range(26))
    assert api.get(f"{path}?series_ids={too_many}").status_code == 422
    assert api.get(f"{path}?series_ids=GDP,../etc").status_code == 422
    assert api.get(f"{path}?series_ids=" + "A" * 65).status_code == 422


def test_series_id_list_at_cap_is_accepted(api):
    ok = ",".join(f"S{i}" for i in range(25))
    assert api.get(f"/api/fred/latest?series_ids={ok}").status_code == 200


def test_huge_max_age_hours_is_rejected_not_overflow(api):
    assert api.get("/api/fred/latest-cached?series_ids=GDP&max_age_hours=99999999999999999999").status_code == 422
    assert api.get("/api/fred/smart/GDP?max_age_hours=99999999999999999999").status_code == 422
    assert api.get("/api/fred/trending-news?max_age_hours=99999999999999999999").status_code == 422
    assert api.get("/api/fred/index-news?max_age_hours=99999999999999999999").status_code == 422
    assert api.get("/api/fred/trending-news?limit=0").status_code == 422


# ---- malformed cache files ----

@pytest.mark.parametrize("content", ["[]", "[1,2]", '"text"', "123", "null", "{not json", '{"cached_at": 5, "payload": []}',
                                     '{"cached_at": "nope", "payload": {}}', '{"cached_at": "2024-01-01T00:00:00", "payload": [1]}'])
def test_index_news_malformed_cache_is_treated_as_no_cache(api, cache_dir, monkeypatch, content):
    from backend.news.service import NewsService
    monkeypatch.setattr(NewsService, "search_news", lambda self, q: [{"title": q, "href": "https://example.com/n"}])
    (cache_dir / "fred_index_news_SP500.json").write_text(content)
    r = api.get("/api/fred/index-news?series_ids=SP500")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["SP500"]["articles"][0]["url"] == "https://example.com/n"


def test_index_news_malformed_cache_with_provider_failure_is_unavailable_not_500(api, cache_dir, monkeypatch):
    from backend.news.service import NewsService
    monkeypatch.setattr(NewsService, "search_news", lambda self, q: (_ for _ in ()).throw(RuntimeError("down")))
    (cache_dir / "fred_index_news_SP500.json").write_text("[]")
    r = api.get("/api/fred/index-news?series_ids=SP500&refresh=true")
    assert r.status_code == 200 and r.json()["data"]["SP500"]["status"] == "unavailable"


@pytest.mark.parametrize("content", ["[]", '"x"', "7", "{oops", '{"cached_at": "2999-01-01T00:00:00", "payload": [1]}'])
def test_trending_news_malformed_cache_is_not_a_500(api, cache_dir, monkeypatch, content):
    from backend.news.service import NewsService
    monkeypatch.setattr(NewsService, "search_news", lambda self, q: [])
    (cache_dir / "fred_trending_news.json").write_text(content)
    r = api.get("/api/fred/trending-news")
    assert r.status_code == 200, r.text  # no cached series data -> a clean "error" payload, not AttributeError
    assert r.json()["articles"] == []


def test_trending_news_valid_cache_still_served(api, cache_dir):
    (cache_dir / "fred_trending_news.json").write_text(json.dumps(
        {"cached_at": datetime.utcnow().isoformat(), "payload": {"status": "success", "articles": [{"title": "t"}]}}))
    r = api.get("/api/fred/trending-news")
    assert r.status_code == 200 and r.json()["cached"] is True and r.json()["articles"][0]["title"] == "t"


# ---- sync defs / honest 503 ----

def test_blocking_fred_routes_are_sync_defs():
    for name in ("sync_single_series", "sync_all_indices", "sync_all_rates", "sync_all_series", "get_series_data",
                 "get_series_latest", "get_all_latest", "get_latest_live", "get_latest_cached", "get_trending_news",
                 "get_index_news", "get_index_dashboard", "get_series_smart"):
        assert not inspect.iscoroutinefunction(getattr(fred_routes, name)), name


def test_keyless_live_requests_are_503_and_cache_reads_still_work(api, monkeypatch, auth):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert api.get("/api/fred/latest-live?series_ids=GDP").status_code == 503
    assert api.post("/api/fred/sync/series", json={"series_id": "GDP"}, headers=auth).status_code == 503
    assert api.get("/api/fred/latest?series_ids=GDP").status_code == 200
