"""Offline regression tests for auth, rate limiting and data handling; no private fixtures."""
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.auth import security
from backend.backtest import service as bt
from backend.database.connection import SessionLocal, get_engine
from backend.database.models import DatasetVersion, ExperimentQuota, ExperimentTrial
from backend.experiments import datasets as ds, store
from backend.main import app
from backend.news import public_fetch as pf


async def test_refresh_preserves_profile_after_access_expiry(client):
    credentials = (await client.post('/api/auth/guest')).json()
    headers = {'Authorization': 'Bearer ' + credentials['access_token']}
    assert (await client.post('/api/profile/save', headers=headers, json={'name': 'Test investor'})).status_code == 200
    expired, _ = security.create_access_token(credentials['user_id'], ttl=timedelta(days=-1))
    assert (await client.get('/api/profile/load', headers={'Authorization': 'Bearer ' + expired})).status_code == 401
    # Both durable recovery and the access-only migration preserve the subject.
    for token in [credentials['refresh_token'], expired]:
        response = await client.post('/api/auth/refresh', json={'refresh_token': token})
        assert response.status_code == 200
        renewed = response.json()
        assert renewed['user_id'] == credentials['user_id']
        profile = await client.get('/api/profile/load', headers={'Authorization': 'Bearer ' + renewed['access_token']})
        assert profile.json()['profile']['name'] == 'Test investor'
    assert (await client.get('/api/profile/load', headers={'Authorization': 'Bearer ' + credentials['refresh_token']})).status_code == 401


async def test_refresh_rejects_forged_and_old_access_credentials(client):
    old, _ = security.create_access_token('guest_test', ttl=timedelta(days=-31))
    wrong_key = security.jwt.encode({'sub': 'guest_test', 'iat': 1, 'typ': 'guest_refresh'}, 'wrong-key' * 6, algorithm='HS256')
    for token in ['invalid', old, wrong_key]:
        assert (await client.post('/api/auth/refresh', json={'refresh_token': token})).status_code == 401


async def test_pre_renewal_access_tokens_recover_identity_after_long_absence(client):
    legacy = security.jwt.encode({'sub': 'guest_legacy_fixture', 'iat': 1, 'exp': 2,
                                  'typ': 'guest'}, security.get_secret(), algorithm='HS256')
    response = await client.post('/api/auth/refresh', json={'refresh_token': legacy})
    assert response.status_code == 200
    assert response.json()['user_id'] == 'guest_legacy_fixture'
    assert security.user_from_token(response.json()['access_token']) == 'guest_legacy_fixture'


@pytest.mark.parametrize('url', ['http://127.0.0.1/', 'http://[::1]/', 'http://169.254.169.254/',
                                 'http://[64:ff9b::7f00:1]/', 'http://[2002:7f00:1::]/',
                                 'http://224.0.0.1/',
                                 'file:///etc/passwd', 'https://user:password@example.com/',
                                 'https://example.com:9000/'])
def test_article_summary_rejects_private_and_invalid_urls(url):
    with TestClient(app) as client:
        response = client.get('/api/news/article-summary', params={'url': url})
    assert response.status_code == 400


def test_article_connection_pins_validated_dns_address(monkeypatch):
    connections = []
    resolutions = []
    def resolve(*args, **kwargs):
        resolutions.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
    class FakeSocket:
        def __init__(self, *a): pass
        def settimeout(self, timeout): pass
        def connect(self, address): connections.append(address)
        def close(self): pass
    monkeypatch.setattr(pf.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(pf.socket, 'socket', FakeSocket)
    pf._public_socket('article.example', 443, 10)
    assert len(resolutions) == 1 and connections == [('8.8.8.8', 443)]


def test_private_dns_and_redirect_are_rejected(monkeypatch):
    monkeypatch.setattr(pf.socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 80))])
    with pytest.raises(pf.UnsafeArticleURL):
        pf._public_socket('internal.example', 80, 10)
    class Redirect:
        status = 302
        def getheader(self, name): return 'http://127.0.0.1/private'
    class Connection:
        def __init__(self, *a, **kw): pass
        def request(self, *a, **kw): pass
        def getresponse(self): return Redirect()
        def close(self): pass
    monkeypatch.setattr(pf, '_PublicHTTPSConnection', Connection)
    with pytest.raises(pf.UnsafeArticleURL):
        pf.fetch_public_html('https://article.example/')


def test_article_body_and_redirect_count_are_bounded(monkeypatch):
    class Response:
        status = 200
        def read(self, count): return b'x' * count
    class Connection:
        calls = 0
        def __init__(self, *a, **kw): Connection.calls += 1
        def request(self, *a, **kw): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(pf, '_PublicHTTPSConnection', Connection)
    assert pf.fetch_public_html('https://article.example/') is None
    Response.status = 302
    Response.getheader = lambda self, name: '/again'
    Connection.calls = 0
    assert pf.fetch_public_html('https://article.example/') is None
    assert Connection.calls == 6


def test_rsi_reversal_holds_through_neutral_bars():
    prices = [10, 9, 8, 9, 10, 11, 10, 9, 8, 9, 10, 11]
    frame = bt.prepare_candles_df([{'date': str(d.date()), 'open': p, 'high': p + .1,
        'low': p - .1, 'close': p, 'volume': 100} for d, p in zip(pd.bdate_range('2024-01-01', periods=len(prices)), prices)])
    result = bt.run_spec(frame, {'strategy': 'rsi_reversal', 'params': {'window': 2}}, full=False)
    assert len(result['trades']) == 1
    assert result['ledger'][-1]['kind'] == 'close_at_end'
    assert result['trades'][0]['duration'] > 1


def test_profit_factor_and_first_period_drawdown():
    metrics = bt._compute_advanced_trade_metrics([{'pnl': 100, 'pnlPct': 100}, {'pnl': -100, 'pnlPct': -50}])
    assert metrics['profitFactor'] == 1
    assert bt._run_monte_carlo(pd.Series([-1.0]), simulations=10)['riskMetrics']['medianMaxDrawdown'] == -100


def test_dataset_identity_includes_metadata_and_retains_legacy_reads():
    fixture = ds.get_fixture('synthetic-flat-60')
    candles = ds.FIXTURES['synthetic-flat-60']['generator']()
    args = {k: getattr(fixture, k) for k in ds.IDENTITY_FIELDS}
    other = ds.build_dataset(candles, **{**args, 'source': 'provider:yfinance'})
    hourly = ds.build_dataset(candles, **{**args, 'interval': '1h'})
    alias = ds.build_dataset(candles, **{**args, 'interval': '60m'})
    assert fixture.content_hash != other.content_hash != hourly.content_hash
    assert hourly.content_hash == alias.content_hash and alias.interval == '1h'
    with SessionLocal(bind=get_engine()) as db:
        first = store.save_dataset(db, fixture)
        second = store.save_dataset(db, other)
        assert first.source != second.source
        legacy = DatasetVersion(**{c.name: getattr(first, c.name) for c in DatasetVersion.__table__.columns
                                   if c.name not in ('content_hash', 'created_at')}, content_hash=ds.rows_hash(fixture.rows))
        pd.testing.assert_frame_equal(store._frame_from_row(legacy), ds.rows_to_df(fixture.rows))
        second.symbol = 'TAMPERED'
        with pytest.raises(ds.DatasetError):
            store._frame_from_row(second)
        db.rollback()


def test_trial_quota_is_atomic_across_sessions(monkeypatch):
    user = 'quota_' + uuid.uuid4().hex
    monkeypatch.setattr(store, 'MAX_TRIALS_PER_USER', 1)
    barrier = Barrier(2)
    spec, spec_json, spec_hash = store.validate_spec({'strategy': 'sma_crossover'})
    def run(_):
        with SessionLocal(bind=get_engine()) as db:
            barrier.wait(timeout=10)
            try:
                store.run_and_record_trial(db, user, spec, spec_json, spec_hash,
                                          {'fixture': 'synthetic-flat-60'}, None)
                return 'completed'
            except store.TrialLimitError:
                return 'limited'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ['completed', 'limited']
    with SessionLocal(bind=get_engine()) as db:
        assert db.query(ExperimentTrial).filter_by(user_id=user).count() == 1


def test_unexpected_trial_error_releases_reservation(monkeypatch):
    user = 'quota_' + uuid.uuid4().hex
    def fail(*args): raise RuntimeError('synthetic engine failure')
    monkeypatch.setattr(store, 'resolve_dataset', fail)
    spec, encoded, hashed = store.validate_spec({'strategy': 'sma_crossover'})
    with SessionLocal(bind=get_engine()) as db:
        with pytest.raises(RuntimeError):
            store.run_and_record_trial(db, user, spec, encoded, hashed, {'fixture': 'synthetic-flat-60'}, None)
        assert db.get(ExperimentQuota, user).allocated == 0


def test_report_creation_and_download_share_directory(tmp_path, monkeypatch):
    from backend.backtest import main as routes
    monkeypatch.setattr(routes, 'REPORTS_DIR', tmp_path)
    monkeypatch.setattr(bt, '__file__', str(tmp_path.parent / 'service.py'))
    # The service uses <module directory>/reports; align its module with the temp layout.
    target = tmp_path.parent / 'reports'
    monkeypatch.setattr(routes, 'REPORTS_DIR', target)
    with TestClient(app) as client:
        created = client.post('/api/backtest/report', json={'symbol': 'TEST', 'format': 'csv'}).json()
        response = client.get(created['downloadUrl'])
        assert response.status_code == 200 and 'Backtest Report' in response.text
        created = client.post('/api/backtest/report', json={'symbol': 'TEST', 'format': 'html',
            'strategies': ['<script>alert(1)</script>']}).json()
        response = client.get(created['downloadUrl'])
        assert response.status_code == 200
        assert '<script>alert(1)</script>' not in response.text
        assert '&lt;script&gt;' in response.text
        assert "default-src 'none'" in response.headers['content-security-policy']


def test_missing_recommendation_workflow_is_explicitly_unavailable():
    with TestClient(app) as client:
        response = client.post('/api/chat/stock-advisor/recommend', json={'user_input': 'test request'})
    assert response.status_code == 503
    assert 'unavailable' in response.json()['detail']
