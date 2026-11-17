"""Guard the canonical API surface and route resolution after legacy removal."""
import pytest
from fastapi.routing import APIRoute
from starlette.routing import Match
from backend.main import app

RETIRED_PREFIXES = (
    '/api/portfolio/api/investor-profile',
    '/api/portfolio/api/reports',
    '/api/chat/api/research',
    '/api/markets/fred',
    '/api/technical/peers',
    '/api/fundamentals',
)
RETIRED_PATHS = (
    '/api/markets', '/api/markets/macro/overview',
    '/api/chat/status', '/api/portfolio/overview', '/api/sectors/{index_id}',
)


def test_legacy_routes_are_not_registered():
    paths = [r.path for r in app.routes]
    assert not [p for p in paths if p in RETIRED_PATHS or p.startswith(RETIRED_PREFIXES)]


def test_no_handler_is_mounted_under_multiple_paths():
    handlers = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            handlers.setdefault(route.endpoint, set()).add(route.path)
    assert not {handler.__name__: paths for handler, paths in handlers.items() if len(paths) > 1}


def test_sector_performance_is_reachable_without_index_alias_shadowing():
    scope = {'type': 'http', 'method': 'GET', 'path': '/api/sectors/performance'}
    route = next(r for r in app.routes if r.matches(scope)[0] == Match.FULL)
    assert route.path == '/api/sectors/performance'


@pytest.mark.parametrize('path', [
    '/api/portfolio/api/investor-profile/load',
    '/api/markets/fred/available-series',
    '/api/chat/status', '/api/portfolio/overview',
    '/api/markets/macro/overview', '/api/fundamentals/summary/AAPL',
    '/api/sectors/nifty_50',
])
async def test_retired_urls_return_404(client, path):
    assert (await client.get(path)).status_code == 404
