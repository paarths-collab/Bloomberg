"""Machine-checked frontend -> API contract.

frontend/lib/api-routes.json is the single source of truth for every backend route the
Next.js client calls (frontend/lib/api.ts builds URLs only from it). These tests assert that
each entry:

  * exists on ``backend.main.app`` with the declared method and path template
    (path-parameter names are normalised, so "{symbol}" and "{ticker}" compare equal);
  * is actually *reached* by that concrete URL (an earlier, broader route cannot shadow it);
  * for investor-profile (paper-portfolio) routes, requires ``require_user``, while
    POST /api/auth/guest stays public so the client can obtain its token;
  * declares every query parameter that api.ts sends to it (see QUERY_PARAMS);

and that the route ids called from api.ts (request/buildUrl call sites) match the JSON.

Runs fully offline (no network, temp DB from backend/tests/conftest.py).
"""
import json
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Match

from backend.auth.security import require_user
from backend.main import app

FRONTEND_LIB = Path(__file__).resolve().parents[2] / "frontend" / "lib"
ROUTES_JSON = FRONTEND_LIB / "api-routes.json"
API_TS = FRONTEND_LIB / "api.ts"

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
WS_METHOD = "WS"
PARAM_RE = re.compile(r"\{[^}/]+\}")
INVESTOR_PROFILE_PREFIX = "investorProfile."

# A route id passed as the first argument of request(...) or buildUrl(...), with optional
# generic type args: request<T>('id', ...), request('id'), buildUrl('id', ...).
CALL_ID_RE = re.compile(r"\b(?:request|buildUrl)\s*(?:<[^<>()]*>)?\s*\(\s*'([a-z][A-Za-z]*\.[A-Za-z]+)'")

# Route ids that api.ts never passes to request()/buildUrl(). ws.live is opened through
# getWsUrl("/ws/live") with a path, and appears in api.ts only in the RestRouteId type.
NON_CALL_ROUTE_IDS = {"ws.live"}

# Query parameter names api.ts actually sends, per route id (derived from the call sites
# in api.ts). Each must be declared on the matched FastAPI route's dependant.query_params.
QUERY_PARAMS = {
    "chat.sentimentAnalyze": ["market"],
    "markets.candles": ["interval", "range", "market"],
    "fred.latestLive": ["series_ids"],
    "fred.latestCached": ["series_ids"],
    "sectors.treemapIndices": ["market"],
    "sectors.treemapIndicesLive": ["market"],
    "sectors.treemapIndex": ["market", "include_prices"],
    "sectors.treemapStock": ["market"],
    "peers.compare": ["limit"],
    "news.live": ["query", "limit", "cached_only"],
}


def _load_routes() -> dict:
    return json.loads(ROUTES_JSON.read_text(encoding="utf-8"))


ROUTES = _load_routes()


def _normalise(path: str) -> str:
    return PARAM_RE.sub("{}", path)


def _concrete(path: str) -> str:
    return PARAM_RE.sub("sample", path)


def _find_declared(method: str, path: str):
    """The app route declared with this method + normalised template, or None."""
    wanted = _normalise(path)
    for route in app.routes:
        if method == WS_METHOD:
            if isinstance(route, APIWebSocketRoute) and _normalise(route.path) == wanted:
                return route
        elif isinstance(route, APIRoute) and _normalise(route.path) == wanted and method in route.methods:
            return route
    return None


def _resolve(method: str, concrete_path: str):
    """First app route that fully matches the request, in registration order (Starlette's rule)."""
    if method == WS_METHOD:
        scope = {"type": "websocket", "path": concrete_path, "root_path": "", "headers": []}
    else:
        scope = {"type": "http", "method": method, "path": concrete_path, "root_path": "", "headers": []}
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route
    return None


def _depends_on(dependant, target) -> bool:
    return any(d.call is target or _depends_on(d, target) for d in dependant.dependencies)


def test_routes_file_is_well_formed():
    assert ROUTES, "api-routes.json is empty"
    for route_id, entry in ROUTES.items():
        assert set(entry) == {"method", "path"}, f"{route_id}: unexpected keys {sorted(entry)}"
        assert entry["method"] in HTTP_METHODS | {WS_METHOD}, f"{route_id}: bad method {entry['method']!r}"
        assert entry["path"].startswith("/"), f"{route_id}: path must start with '/'"
        if entry["method"] != WS_METHOD:
            assert entry["path"].startswith("/api/"), f"{route_id}: REST routes live under /api/"
        assert "?" not in entry["path"], f"{route_id}: query strings belong in api.ts, not the route"
    # Two ids for one (method, path) would just be drift waiting to happen.
    pairs = [(e["method"], _normalise(e["path"])) for e in ROUTES.values()]
    assert len(pairs) == len(set(pairs)), "duplicate (method, path) entries in api-routes.json"


@pytest.mark.parametrize("route_id", sorted(ROUTES))
def test_route_exists_on_backend(route_id):
    entry = ROUTES[route_id]
    declared = _find_declared(entry["method"], entry["path"])
    assert declared is not None, (
        f"{route_id}: backend.main.app has no {entry['method']} route matching {entry['path']}"
    )


@pytest.mark.parametrize("route_id", sorted(ROUTES))
def test_route_is_not_shadowed(route_id):
    entry = ROUTES[route_id]
    declared = _find_declared(entry["method"], entry["path"])
    assert declared is not None
    reached = _resolve(entry["method"], _concrete(entry["path"]))
    assert reached is declared, (
        f"{route_id}: {entry['method']} {_concrete(entry['path'])} is handled by "
        f"{getattr(reached, 'path', None)!r}, not by {declared.path!r}"
    )


def test_investor_profile_routes_require_auth():
    ids = [i for i in ROUTES if i.startswith(INVESTOR_PROFILE_PREFIX)]
    assert ids, "expected at least one investor-profile route in api-routes.json"
    for route_id in ids:
        entry = ROUTES[route_id]
        route = _find_declared(entry["method"], entry["path"])
        assert route is not None, route_id
        assert _depends_on(route.dependant, require_user), (
            f"{route_id}: {entry['path']} must depend on require_user (the client sends a bearer token)"
        )


def test_guest_token_route_is_public():
    entry = ROUTES["auth.guest"]
    assert entry["method"] == "POST"
    route = _find_declared(entry["method"], entry["path"])
    assert route is not None
    assert not _depends_on(route.dependant, require_user), "auth.guest cannot require a token"


def test_investor_profile_routes_reject_missing_token():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    for route_id, entry in ROUTES.items():
        if not route_id.startswith(INVESTOR_PROFILE_PREFIX):
            continue
        assert entry["method"] in HTTP_METHODS
        response = client.request(entry["method"], _concrete(entry["path"]))
        assert response.status_code == 401, f"{route_id}: expected 401 without a token, got {response.status_code}"


@pytest.mark.parametrize("route_id", sorted(QUERY_PARAMS))
def test_query_params_exist_on_backend_route(route_id):
    assert route_id in ROUTES, f"{route_id}: QUERY_PARAMS key is not in api-routes.json"
    entry = ROUTES[route_id]
    route = _find_declared(entry["method"], entry["path"])
    assert route is not None, route_id
    declared_names = {field.name for field in route.dependant.query_params}
    missing = [name for name in QUERY_PARAMS[route_id] if name not in declared_names]
    assert not missing, (
        f"{route_id}: api.ts sends query params {missing} that {entry['path']} does not declare "
        f"(declared: {sorted(declared_names)})"
    )


def test_api_ts_and_routes_json_reference_the_same_ids():
    source = API_TS.read_text(encoding="utf-8")
    # Only ids passed to request(...) or buildUrl(...) count as usages. A bare quoted
    # dotted string elsewhere (types, comments) does not.
    called = set(CALL_ID_RE.findall(source))
    declared = set(ROUTES)
    assert called, "found no request()/buildUrl() calls with a route id in api.ts"
    assert called - declared == set(), f"api.ts calls ids missing from api-routes.json: {sorted(called - declared)}"
    unused = declared - called
    assert unused == NON_CALL_ROUTE_IDS, f"api-routes.json ids never called by api.ts: {sorted(unused)}"
    for route_id in NON_CALL_ROUTE_IDS:
        assert f"'{route_id}'" in source, f"{route_id} is no longer referenced by api.ts at all"
