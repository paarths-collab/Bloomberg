"""Offline coverage for provider fallbacks: cached FRED reads, sector news and sector intel."""
from datetime import date, datetime, timezone
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def api():
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_fred_cache_reads_without_key_and_latest_is_latest(api, monkeypatch):
    monkeypatch.delenv('FRED_API_KEY', raising=False)
    from backend.database.connection import get_db_session
    from backend.database.fred_repository import FredRepository
    with get_db_session() as db:
        repo = FredRepository(db)
        repo.upsert_data('AUDIT_GDP', 'economic', date(2024, 1, 1), 10)
        repo.upsert_data('AUDIT_GDP', 'economic', date(2024, 2, 1), 12)
        db.commit()
    latest = api.get('/api/fred/series/AUDIT_GDP/latest')
    assert latest.status_code == 200, latest.text
    assert latest.json()['value'] == 12
    assert api.get('/api/fred/series/AUDIT_GDP').json()['count'] == 2
    assert api.get('/api/fred/latest?series_ids=AUDIT_GDP').json()['data']['AUDIT_GDP']['value'] == 12
    cached = api.get('/api/fred/latest-cached?series_ids=AUDIT_GDP&max_age_hours=0')
    assert cached.status_code == 200
    assert cached.json()['data']['AUDIT_GDP']['value'] == 12
    assert api.get('/api/fred/series/NO_SUCH_SERIES/latest').status_code == 404
    assert api.get('/api/fred/latest-live?series_ids=GDP').status_code == 503
    # Sync endpoints write the DB / spend provider quota: authentication is required first.
    assert api.post('/api/fred/sync/series', json={'series_id':'GDP'}).status_code == 401
    from backend.auth import create_access_token
    auth = {'Authorization': 'Bearer ' + create_access_token('fred-sync-user')[0]}
    assert api.post('/api/fred/sync/series', json={'series_id':'GDP'}, headers=auth).status_code == 503


@pytest.mark.parametrize('ticker_first', [True, False])
def test_single_ticker_multiindex_quotes_keep_real_change(monkeypatch, ticker_first):
    from backend.core import safe_yfinance as yf
    yf.clear_cache()
    frame = pd.DataFrame({'Close':[100.0, 110.0]}, index=pd.date_range('2024-01-01', periods=2))
    frame.columns = pd.MultiIndex.from_tuples([('AAPL','Close') if ticker_first else ('Close','AAPL')])
    monkeypatch.setattr(yf.yf, 'download', lambda **kwargs: frame)
    quote = yf.safe_fetch_multiple_quotes(['AAPL'])['AAPL']
    assert (quote['price'],quote['change'],quote['change_percent']) == (110,10,10)
    yf.clear_cache()


def test_stock_detail_missing_change_stays_null(api, monkeypatch):
    from backend.services.market_data import market_service
    monkeypatch.setattr(market_service,'fetch_multiple_quotes',lambda *a: {'AAPL': {'price':110,'change':10,'change_percent':10}})
    monkeypatch.setattr(market_service,'get_fundamentals',lambda *a: {'shortName':'Apple'})
    assert api.get('/api/sectors/treemap/stock/AAPL?market=US').json()['price']['change_percent'] == 10
    monkeypatch.setattr(market_service,'fetch_multiple_quotes',lambda *a: {})
    assert api.get('/api/sectors/treemap/stock/AAPL?market=US').json()['price']['change_percent'] is None


def test_emotions_are_distinct_and_not_confidence_scores(api):
    panic=api.post('/api/dashboard/sentiment',json={'message':'I panic and fear a crash'}).json()
    fomo=api.post('/api/dashboard/sentiment',json={'message':'FOMO, all in, to the moon'}).json()
    assert panic['emotion']=='anxious' and fomo['emotion']=='excited'
    assert panic['dominant_bias']=='panic_selling'
    assert panic['confidence'] is None and panic['method']=='keyword_heuristic'


def test_crowd_without_sources_has_no_fabricated_signal(api):
    data=api.post('/api/dashboard/crowd-insight',json={'ticker':'AAPL','include_insider':False,'include_news':False}).json()
    assert data['signal']=={'score':None,'label':'unavailable','confidence':None,'confidence_status':'not_computed'}


def test_sector_news_handles_sqlite_timestamp_strings(api):
    from backend.database.connection import get_db_session
    from backend.database.models import SectorNewsItem
    with get_db_session() as db:
        db.add(SectorNewsItem(sector='Audit sector',market='US',title='Audit news',hash='provider-repair-news',published_at=datetime.now(timezone.utc)))
        db.commit()
    r=api.get('/api/dashboard/sector-news?market=US&sector=Audit%20sector')
    assert r.status_code==200, r.text
    assert r.json()['total_items']==1


def test_sector_refresh_fetcher_uses_existing_news_service(monkeypatch):
    from backend.news.service import NewsService
    from backend.sectors.intel_service import _fetch_ddg_news
    monkeypatch.setattr(NewsService,'search_news',lambda self,q:[{'title':'Headline','href':'https://example.com/news','body':'Text'}])
    assert _fetch_ddg_news('technology',1)[0]['url']=='https://example.com/news'


def test_index_news_returns_multiple_series_without_overwriting_results(api, monkeypatch, tmp_path):
    from backend.markets import fred_routes
    from backend.news.service import NewsService
    # Route's cache location remains under the temporary path, not the checkout.
    fake=tmp_path/'markets'/'fred_routes.py';fake.parent.mkdir()
    monkeypatch.setattr(fred_routes,'__file__',str(fake))
    monkeypatch.setattr(NewsService,'search_news',lambda self,q:[{'title':q,'href':'https://example.com/news','body':'Text'}])
    r=api.get('/api/fred/index-news?series_ids=SP500,DJIA&refresh=true')
    assert r.status_code==200, r.text
    assert set(r.json()['data'])=={'SP500','DJIA'}
    assert all(v['articles'][0]['url']=='https://example.com/news' for v in r.json()['data'].values())
    assert api.get('/api/fred/index-news?series_ids=../unsafe').status_code==422


def test_network_accepts_string_and_dictionary_peers(monkeypatch):
    from backend.network.core import graph_service
    monkeypatch.setattr(graph_service,'fetch_stock_peers',lambda s:['MSFT',{'symbol':'NVDA','source':'local_sector_universe'}])
    result=graph_service.get_network_graph('AAPL')
    assert len(result['nodes'])==3 and len(result['links'])==2
    assert result['comparison_basis']=='sector comparables'


def test_local_comparables_exclude_self_and_label_source(monkeypatch):
    from backend.peers import service
    monkeypatch.delenv('FMP_API_KEY',raising=False);monkeypatch.setattr(service,'FMP_API_KEY','')
    peers=service.fetch_stock_peers('AAPL')
    assert peers and all(p['symbol']!='AAPL' and p['source']=='local_sector_universe' for p in peers)


def test_eia_missing_key_is_service_unavailable(api, monkeypatch):
    monkeypatch.delenv('EIA_API_KEY',raising=False)
    assert api.get('/api/markets/eia/latest').status_code==503


def test_failed_ai_reports_do_not_return_success(api, monkeypatch):
    import types
    from backend.chat import super_agent, stock_advisor
    from backend.research import main as research
    async def failed(**kwargs):return {'report':'Error: missing key'}
    monkeypatch.setattr(super_agent,'_get_pipeline',lambda:types.SimpleNamespace(run=failed))
    assert api.post('/api/chat/super-agent',json={'query':'test'}).status_code==503
    monkeypatch.setattr(stock_advisor,'_run_multi_pov_langgraph',lambda **kw:{role:{'reasoning':'[Groq unavailable — no API key]'} for role in ['bull','bear','neutral']})
    assert api.post('/api/chat/stock-advisor/multi-pov',json={'symbol':'AAPL'}).status_code==503
    monkeypatch.setattr(research,'generate_research_report',lambda s:{'report':'AI report generation failed.'})
    assert api.post('/api/research/analyze',json={'symbol':'AAPL'}).status_code==503


def test_sector_refresh_persists_readable_data_without_fake_recommendations(api, monkeypatch):
    from backend.sectors import intel_service
    from backend.news.service import NewsService
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    monkeypatch.setattr(NewsService,'search_news',lambda self,q:[{'title':'Sector news','href':'https://example.com/sector'}])
    monkeypatch.setattr(intel_service,'_build_stock_payload',lambda *a:[{'symbol':'AAPL','name':'Apple'}])
    from backend.auth import create_access_token
    auth={'Authorization':'Bearer '+create_access_token('sector-refresh-user')[0]}
    sector=intel_service.get_sector_list('US')[0]  # refresh only accepts known sectors
    r=api.post('/api/sectors/intel/refresh',json={'market':'US','sector':sector,'force':True},headers=auth)
    assert r.status_code==200, r.text
    assert r.json()['news_count']==1 and r.json()['analysis_status']=='unavailable'
    data=api.get('/api/sectors/intel/latest?market=US',params={'sector':sector}).json()
    assert data['score'] is None and data['llm_model']=='unavailable'
    assert api.post('/api/sectors/intel/recommend',json={'market':'US'}).json()==[]
    assert api.get('/api/dashboard/sector-news',params={'market':'US','sector':sector}).json()['total_items']==1


def test_sector_fundamentals_flag_is_honored(api, monkeypatch):
    from backend.sectors import main
    monkeypatch.setattr(main,'get_sector_constituents',lambda *a,**k:[{'symbol':'AAPL'}])
    monkeypatch.setattr(main.market_service,'get_fundamentals',lambda s:{'shortName':'Apple'})
    data=api.get('/api/sectors/intel/stocks/Technology?include_fundamentals=true&include_technicals=false').json()
    assert data['stocks'][0]['fundamentals']['shortName']=='Apple'
    data=api.get('/api/sectors/intel/stocks/Technology?include_fundamentals=false&include_technicals=false').json()
    assert 'fundamentals' not in data['stocks'][0]


def test_fmp_peers_list_envelope_is_parsed(monkeypatch):
    from backend.peers import service
    import types
    monkeypatch.setenv('FMP_API_KEY','test-key')
    monkeypatch.setattr(service.requests,'get',lambda *a,**k:types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:[{'symbol':'AAPL','peersList':['AAPL','MSFT','NVDA']}]))
    assert [p['symbol'] for p in service.fetch_stock_peers('AAPL')]==['MSFT','NVDA']


def test_dividend_yield_uses_cash_dividends_and_price(monkeypatch):
    from backend.peers import comparison_service as service
    import types
    monkeypatch.setattr(service.yf,'Ticker',lambda s:types.SimpleNamespace(info={'currentPrice':200,'trailingAnnualDividendRate':2,'dividendYield':1.0},fast_info={}))
    assert service._yf_basic_metrics('TEST',None)['div_yield']==1.0


def test_ai_reasoning_can_discuss_errors_without_being_a_provider_error(api, monkeypatch):
    from backend.chat import stock_advisor
    monkeypatch.setattr(stock_advisor,'_run_multi_pov_langgraph',lambda **kw:{r:{'reasoning':'Consider measurement error and unavailable historical details.'} for r in ['bull','bear','neutral']})
    assert api.post('/api/chat/stock-advisor/multi-pov',json={'symbol':'AAPL'}).status_code==200


def test_missing_index_never_uses_constituent_or_expired_quote(monkeypatch):
    from backend.sectors.service import SectorsService
    from backend.services.market_data import market_service
    svc=SectorsService()
    svc._live_indices_cache['india']={'cached_at':0,'data':[{'id':'sample','price':999,'change_percent':8}]}
    monkeypatch.setattr(svc,'_get_market_indices',lambda market:[{'id':'sample','symbol':'^INDEX','constituents':[{'symbol':'AAPL'}]}])
    monkeypatch.setattr(market_service,'fetch_multiple_quotes',lambda *a,**kw:{'AAPL':{'price':100,'change_percent':2}})
    item=svc.get_indices_live('india')[0]
    assert item['price'] is None and item['change_percent'] is None
    assert item['price_status']=='unavailable'
