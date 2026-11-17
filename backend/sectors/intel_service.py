import os
import json
import math
import re
import ast
import logging
import time
import hashlib
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func

try:
    from groq import Groq
except ImportError:
    Groq = None

from backend.database.models import SectorNewsItem, SectorSnapshot, SectorScore

# Unified services
from backend.services.market_data import market_service


SECTOR_INTEL_NEWS_LIMIT = int(os.getenv("SECTOR_INTEL_NEWS_LIMIT", "10"))
SECTOR_INTEL_STOCKS_LIMIT = int(os.getenv("SECTOR_INTEL_STOCKS_LIMIT", "12"))
SECTOR_INTEL_PRICE_PERIOD = os.getenv("SECTOR_INTEL_PRICE_PERIOD", "3mo")
SECTOR_INTEL_REFRESH_MINUTES = int(os.getenv("SECTOR_INTEL_REFRESH_MINUTES", "60"))
SECTOR_INTEL_SECTOR_GAP_SECONDS = int(os.getenv("SECTOR_INTEL_SECTOR_GAP_SECONDS", "60"))
SECTOR_INTEL_MARKETS = os.getenv("SECTOR_INTEL_MARKETS", "US,IN")
SECTOR_INTEL_LLM_MODEL = os.getenv("SECTOR_INTEL_LLM_MODEL", os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


SECTOR_INTEL_HTTP_TIMEOUT_SECONDS = _float_env("SECTOR_INTEL_HTTP_TIMEOUT_SECONDS", 20.0)
SECTOR_INTEL_LLM_TIMEOUT_SECONDS = _float_env("SECTOR_INTEL_LLM_TIMEOUT_SECONDS", 30.0)
SECTOR_INTEL_LLM_MIN_INTERVAL_SECONDS = _float_env("SECTOR_INTEL_LLM_MIN_INTERVAL_SECONDS", 0.0)
SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS = _float_env("SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS", 0.0)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = str(raw).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


SECTOR_INTEL_LLM_ENABLED = _bool_env("SECTOR_INTEL_LLM_ENABLED", True)
SECTOR_INTEL_LLM_MAX_RETRIES = _int_env("SECTOR_INTEL_LLM_MAX_RETRIES", 0)
SECTOR_INTEL_LLM_MAX_COMPLETION_TOKENS = _int_env("SECTOR_INTEL_LLM_MAX_COMPLETION_TOKENS", 700)
SECTOR_INTEL_LLM_429_RETRIES = _int_env("SECTOR_INTEL_LLM_429_RETRIES", 2)
SECTOR_INTEL_LLM_429_BACKOFF_SECONDS = _float_env("SECTOR_INTEL_LLM_429_BACKOFF_SECONDS", 6.0)
SECTOR_INTEL_LLM_429_MAX_SLEEP_SECONDS = _float_env("SECTOR_INTEL_LLM_429_MAX_SLEEP_SECONDS", 60.0)
SECTOR_INTEL_LLM_429_COOLDOWN_SECONDS = _float_env("SECTOR_INTEL_LLM_429_COOLDOWN_SECONDS", 60.0)
SECTOR_INTEL_LLM_429_COOLDOWN_MAX = _int_env("SECTOR_INTEL_LLM_429_COOLDOWN_MAX", 1)

_last_llm_call_monotonic = 0.0
_llm_disabled_until_monotonic = 0.0

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    try:
        return value.astimezone(timezone.utc)
    except Exception:
        return value


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def _load_universe(market: str) -> List[Dict[str, Any]]:
    market_code = (market or "IN").upper()
    file_path = _data_dir() / ("us_stocks.json" if market_code in ["US", "USA"] else "nifty500.json")
    if not file_path.exists():
        return []
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _get_sector_key(records: List[Dict[str, Any]]) -> str:
    if not records:
        return "Industry"
    sample = records[0]
    if "Industry" in sample:
        return "Industry"
    if "Sector" in sample:
        return "Sector"
    for rec in records:
        if "Industry" in rec:
            return "Industry"
        if "Sector" in rec:
            return "Sector"
    return "Industry"


def _normalize_sector(value: Any) -> str:
    return str(value).strip()


def _format_symbol(symbol: str, market: str) -> str:
    market_code = (market or "IN").upper()
    sym = str(symbol).strip()
    if market_code in ["IN", "INDIA"] and sym and not sym.endswith(".NS"):
        return f"{sym}.NS"
    return sym


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        logger.debug("ISO datetime parse failed for value=%r", raw)
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _hash_news_item(title: str, url: str) -> str:
    base = f"{title}|{url}".encode("utf-8", errors="ignore")
    return hashlib.sha1(base).hexdigest()


def _normalize_news_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": item.get("title") or item.get("heading") or "",
        "snippet": item.get("body") or item.get("snippet") or item.get("description") or "",
        "url": item.get("url") or item.get("href") or "",
        "source": item.get("source") or "",
        "date": item.get("date") or item.get("published") or "",
    }


def _fetch_ddg_news(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Use the maintained news provider chain rather than an undefined DDGS client."""
    if max_results <= 0:
        return []
    from backend.news.service import NewsService
    return [_normalize_news_item(item) for item in NewsService().search_news(query)[:max_results]]


def _safe_json_loads(content: str) -> Any:
    try:
        return json.loads(content)
    except Exception:
        content2 = re.sub(r",\s*([}\]])", r"\1", content)
        try:
            return json.loads(content2)
        except Exception:
            try:
                content3 = (
                    content2.replace("null", "None")
                    .replace("true", "True")
                    .replace("false", "False")
                )
                return ast.literal_eval(content3)
            except Exception:
                return {}


def _is_valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _fetch_yf_price_metrics(symbols: List[str], period: str) -> Dict[str, Dict[str, Any]]:
    """
    [REFACTORED] Uses unified MarketDataService for robust fetching.
    """
    if not symbols:
        return {}
    
    # Bulk fetch using unified service
    quotes = market_service.fetch_multiple_quotes(symbols)
    
    metrics: Dict[str, Dict[str, Any]] = {}
    for symbol, quote in quotes.items():
        metrics[symbol] = {
            "current_price": quote.get("price"),
            "return_percent": quote.get("change_percent"), # Compatibility
            "change_percent": quote.get("change_percent"),
            "momentum_1m_pct": None, # Daily quotes do not establish monthly momentum.
            "volatility_annualized_pct": None # Requires historical returns.
        }
    
    return metrics


def _risk_label_from_score(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    if score <= 3:
        return "conservative"
    if score <= 6:
        return "moderate"
    return "aggressive"


class GroqLLM:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, temperature: float = 0.2):
        if Groq is None:
            raise RuntimeError("Groq SDK not installed. Install `groq` to use Groq LLM.")
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is missing.")
        self.client = Groq(
            api_key=api_key,
            timeout=SECTOR_INTEL_LLM_TIMEOUT_SECONDS,
            max_retries=SECTOR_INTEL_LLM_MAX_RETRIES,
        )
        self.model = model or SECTOR_INTEL_LLM_MODEL
        self.temperature = temperature

    def invoke(self, prompt: str) -> str:
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_completion_tokens=max(128, SECTOR_INTEL_LLM_MAX_COMPLETION_TOKENS),
            top_p=1,
            stream=False,
        )
        return completion.choices[0].message.content if completion.choices else ""


def get_markets() -> List[str]:
    raw = SECTOR_INTEL_MARKETS
    markets = [m.strip().upper() for m in raw.split(",") if m.strip()]
    return markets or ["US", "IN"]


_MARKET_ALIASES = {"USA": "US", "INDIA": "IN"}


def normalize_market(market: Any) -> Optional[str]:
    """Canonical (upper-case, alias-resolved) market code, or None if not a supported market."""
    if not isinstance(market, str):
        return None
    code = market.strip().upper()
    code = _MARKET_ALIASES.get(code, code)
    return code if code in get_markets() else None


def resolve_sector(market: str, sector: Any) -> Optional[str]:
    """Canonical sector name (case-insensitive match against the market's sector list), else None."""
    if not isinstance(sector, str) or not sector.strip():
        return None
    wanted = sector.strip().lower()
    for name in get_sector_list(market):
        if name.lower() == wanted:
            return name
    return None


def get_sector_list(market: str) -> List[str]:
    records = _load_universe(market)
    if not records:
        return []
    sector_key = _get_sector_key(records)
    sectors = sorted({ _normalize_sector(record.get(sector_key, "")) for record in records if record.get(sector_key) })
    return [sector_name for sector_name in sectors if sector_name]


def get_sector_constituents(market: str, sector: str, limit: int = 20) -> List[Dict[str, Any]]:
    records = _load_universe(market)
    if not records:
        return []
    sector_key = _get_sector_key(records)
    target = _normalize_sector(sector).lower()
    matches = []
    for rec in records:
        sec = _normalize_sector(rec.get(sector_key, "")).lower()
        if sec != target:
            continue
        sym = rec.get("Symbol") or rec.get("Ticker") or rec.get("symbol")
        if not sym:
            continue
        symbol = _format_symbol(sym, market)
        name = rec.get("Company Name") or rec.get("name") or rec.get("Company") or symbol
        matches.append({"symbol": symbol, "name": name, "sector": sector})
        if limit and len(matches) >= limit:
            break
    return matches


def _sector_news_query(sector: str, market: str) -> str:
    market_code = (market or "IN").upper()
    if market_code in ["US", "USA"]:
        return f"US {sector} sector stocks news"
    return f"India NSE {sector} sector stocks news"


def fetch_sector_news(sector: str, market: str, limit: int = SECTOR_INTEL_NEWS_LIMIT) -> List[Dict[str, Any]]:
    query = _sector_news_query(sector, market)
    return _fetch_ddg_news(query, max_results=limit)


def analyze_sector_with_llm(
    sector: str,
    market: str,
    news_items: List[Dict[str, Any]],
    stock_payload: List[Dict[str, Any]],
) -> Dict[str, Any]:
    global _last_llm_call_monotonic
    global _llm_disabled_until_monotonic

    if not SECTOR_INTEL_LLM_ENABLED:
        return {}
    if Groq is None or not os.getenv("GROQ_API_KEY"):
        return {}
    now_monotonic = time.monotonic()
    if _llm_disabled_until_monotonic and now_monotonic < _llm_disabled_until_monotonic:
        return {}
    if SECTOR_INTEL_LLM_MIN_INTERVAL_SECONDS and SECTOR_INTEL_LLM_MIN_INTERVAL_SECONDS > 0:
        wait = (_last_llm_call_monotonic + SECTOR_INTEL_LLM_MIN_INTERVAL_SECONDS) - now_monotonic
        if wait > 0:
            time.sleep(wait)

    market_code = (market or "IN").upper()
    market_label = "United States" if market_code in ["US", "USA"] else "India"
    news_titles = [n.get("title", "") for n in news_items if isinstance(n, dict)]

    prompt = f"""You are a market analyst.

Analyze the sector using recent news and stock performance metrics.

MARKET: {market_label}
SECTOR: {sector}

NEWS TITLES:
{json.dumps(news_titles[:10], ensure_ascii=False)}

STOCK METRICS (JSON):
{json.dumps(stock_payload, ensure_ascii=False)}

Return ONLY JSON in this exact shape:
{{
  "sector_summary": "Short summary (2-4 sentences)",
  "momentum": "bullish|neutral|bearish",
  "risk_notes": "Key risks and volatility notes",
  "who_should_invest": "Who this sector fits",
  "suitable_profiles": {{
    "risk": ["conservative","moderate","aggressive"],
    "horizon_years_min": 0,
    "horizon_years_max": 0,
    "goals": ["growth","income","capital_preservation"]
  }},
  "top_stocks": [
    {{"symbol":"SYM","name":"Company","signal":"outperform|neutral|avoid","reason":"short reason"}}
  ],
  "score": 0
}}

Rules:
- Use only stocks from the STOCK METRICS list.
- score must be 0-100.
- No markdown, no code fences, no bullet symbols, no asterisks.
"""

    attempts = 0
    cooldowns_taken = 0
    while True:
        try:
            _last_llm_call_monotonic = time.monotonic()
            llm = GroqLLM()
            content = llm.invoke(prompt).strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = _safe_json_loads(content) or {}
            if not isinstance(data, dict):
                return {}
            return data
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            msg = str(exc)
            is_429 = status_code == 429 or " 429 " in msg or "429" in msg or "too many requests" in msg.lower()
            if is_429 and attempts < max(0, SECTOR_INTEL_LLM_429_RETRIES):
                suggested = None
                try:
                    match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
                    if match:
                        suggested = float(match.group(1))
                except Exception:
                    suggested = None

                sleep_s = suggested if suggested is not None else (SECTOR_INTEL_LLM_429_BACKOFF_SECONDS * (2 ** attempts))
                sleep_s = min(sleep_s, SECTOR_INTEL_LLM_429_MAX_SLEEP_SECONDS)
                sleep_s = max(0.0, sleep_s + random.uniform(0.0, 1.0))
                attempts += 1
                logger.warning("Groq 429 rate limit; backing off %.1fs (attempt %d/%d).", sleep_s, attempts, SECTOR_INTEL_LLM_429_RETRIES)
                time.sleep(sleep_s)
                continue

            # If we still hit 429 after quick retries, do a longer cooldown (e.g. 60s)
            # to let the tokens-per-minute window reset, then try again.
            if is_429 and cooldowns_taken < max(0, SECTOR_INTEL_LLM_429_COOLDOWN_MAX):
                cooldown_s = max(0.0, SECTOR_INTEL_LLM_429_COOLDOWN_SECONDS)
                cooldowns_taken += 1
                attempts = 0
                logger.warning(
                    "Groq 429 rate limit; cooling down %.1fs then retrying (cooldown %d/%d).",
                    cooldown_s,
                    cooldowns_taken,
                    SECTOR_INTEL_LLM_429_COOLDOWN_MAX,
                )
                time.sleep(cooldown_s)
                continue

            if is_429 and SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS and SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS > 0:
                _llm_disabled_until_monotonic = max(
                    _llm_disabled_until_monotonic,
                    time.monotonic() + SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS,
                )
                logger.warning(
                    "Groq 429; disabling LLM for %.1fs (set SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS=0 to keep trying).",
                    SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS,
                )
            return {}


def _build_stock_payload(market: str, sector: str) -> List[Dict[str, Any]]:
    constituents = get_sector_constituents(market, sector, limit=SECTOR_INTEL_STOCKS_LIMIT)
    symbols = [c["symbol"] for c in constituents]
    metrics = _fetch_yf_price_metrics(symbols, SECTOR_INTEL_PRICE_PERIOD)
    payload = []
    for stock in constituents:
        symbol = stock["symbol"]
        metric = metrics.get(symbol, {})
        payload.append({
            "symbol": symbol,
            "name": stock.get("name"),
            "sector": sector,
            "price_metrics": {
                "current_price": metric.get("current_price"),
                "momentum_1m_pct": metric.get("momentum_1m_pct"),
                "return_period_pct": metric.get("return_period_pct"),
                "volatility_annualized_pct": metric.get("volatility_annualized_pct"),
            }
        })
    return payload


def _default_sector_analysis(sector: str, stock_payload: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "sector_summary": f"{sector}: source data collected; AI analysis unavailable.",
        "momentum": "unavailable", "risk_notes": "Risk analysis unavailable.",
        "who_should_invest": None, "suitable_profiles": {},
        "top_stocks": stock_payload[:5], "score": None,
    }


def _latest_snapshot(db, sector: str, market: str) -> Optional[SectorSnapshot]:
    return (
        db.query(SectorSnapshot)
        .filter(SectorSnapshot.market == market, SectorSnapshot.sector == sector)
        .order_by(SectorSnapshot.as_of.desc())
        .first()
    )


def is_snapshot_stale(snapshot: Optional[SectorSnapshot], max_age_minutes: int) -> bool:
    if not snapshot or not snapshot.as_of:
        return True
    as_of = _to_utc_aware(snapshot.as_of)
    age_minutes = (_utcnow() - as_of).total_seconds() / 60.0
    return age_minutes > max_age_minutes


def refresh_sector(
    db,
    sector: str,
    market: str,
    force: bool = False
) -> Dict[str, Any]:
    latest = _latest_snapshot(db, sector, market)
    if not force and not is_snapshot_stale(latest, SECTOR_INTEL_REFRESH_MINUTES):
        return {"sector": sector, "market": market, "status": "fresh", "snapshot_id": latest.id if latest else None}

    news_items = fetch_sector_news(sector, market, limit=SECTOR_INTEL_NEWS_LIMIT)
    news_items = news_items[:SECTOR_INTEL_NEWS_LIMIT]

    hashes = []
    for item in news_items:
        item_hash = _hash_news_item(item.get("title", ""), item.get("url", ""))
        hashes.append(item_hash)

    existing_hashes = set()
    if hashes:
        rows = (
            db.query(SectorNewsItem.hash)
            .filter(SectorNewsItem.market == market, SectorNewsItem.sector == sector)
            .filter(SectorNewsItem.hash.in_(hashes))
            .all()
        )
        existing_hashes = {row[0] for row in rows}

    for item, item_hash in zip(news_items, hashes):
        if item_hash in existing_hashes:
            continue
        db.add(SectorNewsItem(
            sector=sector,
            market=market,
            title=item.get("title") or "",
            url=item.get("url") or "",
            source=item.get("source"),
            published_at=_parse_dt(item.get("date")),
            snippet=item.get("snippet"),
            hash=item_hash,
        ))

    db.flush()

    news_id_rows = []
    if hashes:
        news_id_rows = (
            db.query(SectorNewsItem.id, SectorNewsItem.hash)
            .filter(SectorNewsItem.market == market, SectorNewsItem.sector == sector)
            .filter(SectorNewsItem.hash.in_(hashes))
            .all()
        )
    news_item_ids = [row[0] for row in news_id_rows]

    stock_payload = _build_stock_payload(market, sector)
    analysis = analyze_sector_with_llm(sector, market, news_items, stock_payload)
    used_fallback = not bool(analysis)
    if used_fallback:
        analysis = _default_sector_analysis(sector, stock_payload)

    suitable_profiles = analysis.get("suitable_profiles") or {}
    score = analysis.get("score")
    if not _is_valid_number(score):
        score = None

    snapshot = SectorSnapshot(
        sector=sector,
        market=market,
        as_of=_utcnow(),
        news_item_ids=news_item_ids,
        sector_summary=analysis.get("sector_summary"),
        momentum=analysis.get("momentum"),
        risk_notes=analysis.get("risk_notes"),
        who_should_invest=analysis.get("who_should_invest"),
        suitable_profiles=suitable_profiles,
        top_stocks=analysis.get("top_stocks"),
        score=score,
        llm_model="unavailable" if used_fallback else SECTOR_INTEL_LLM_MODEL,
    )
    db.add(snapshot)

    db.add(SectorScore(
        sector=sector,
        market=market,
        as_of=snapshot.as_of,
        score=score,
        suitable_profiles=suitable_profiles,
        rationale=analysis.get("sector_summary"),
    ))

    return {
        "sector": sector,
        "market": market,
        "status": "refreshed",
        "news_count": len(news_items),
        "analysis_status": "unavailable" if used_fallback else "model",
        "snapshot_as_of": snapshot.as_of.isoformat(),
    }


def refresh_all_sectors(
    db,
    markets: Optional[List[str]] = None,
    force: bool = False,
    sectors: Optional[List[str]] = None,
    max_sectors: int = 0,
) -> Dict[str, Any]:
    markets = markets or get_markets()
    sector_filter = {str(s).strip().lower() for s in (sectors or []) if str(s).strip()} or None
    results = []
    logger.info("sector_intel refresh start markets=%s force=%s", markets, force)
    for market in markets:
        market_sectors = get_sector_list(market)
        if sector_filter:
            market_sectors = [s for s in market_sectors if str(s).strip().lower() in sector_filter]
        if max_sectors and max_sectors > 0:
            market_sectors = market_sectors[: int(max_sectors)]

        logger.info("sector_intel market=%s sectors=%d", market, len(market_sectors))
        for idx, sector in enumerate(market_sectors, start=1):
            start = time.monotonic()
            logger.info("sector_intel market=%s sector=%d/%d name=%s", market, idx, len(market_sectors), sector)
            try:
                res = refresh_sector(db, sector, market, force=force)
            except Exception as exc:
                logger.exception("sector_intel error market=%s sector=%s", market, sector)
                res = {"sector": sector, "market": market, "status": "error", "error": "Sector refresh failed"}
            elapsed = time.monotonic() - start
            res["elapsed_seconds"] = round(elapsed, 3)
            results.append(res)
            logger.info(
                "sector_intel done market=%s sector=%s status=%s elapsed_seconds=%s",
                market,
                sector,
                res.get("status"),
                res.get("elapsed_seconds"),
            )
            if SECTOR_INTEL_SECTOR_GAP_SECONDS > 0:
                time.sleep(SECTOR_INTEL_SECTOR_GAP_SECONDS)
    logger.info("sector_intel refresh complete results=%d", len(results))
    return {"status": "ok", "results": results}


def list_latest_snapshots(db, market: Optional[str] = None) -> List[SectorSnapshot]:
    if market:
        # Stored rows use canonical upper-case codes; match case-insensitively on input.
        market = normalize_market(market) or str(market).strip().upper()
        subq = (
            db.query(
                SectorSnapshot.sector,
                func.max(SectorSnapshot.as_of).label("max_as_of"),
            )
            .filter(SectorSnapshot.market == market)
            .group_by(SectorSnapshot.sector)
            .subquery()
        )
        rows = (
            db.query(SectorSnapshot)
            .join(
                subq,
                and_(
                    SectorSnapshot.sector == subq.c.sector,
                    SectorSnapshot.as_of == subq.c.max_as_of,
                    SectorSnapshot.market == market,
                ),
            )
            .all()
        )
        return rows

    markets = get_markets()
    snapshots: List[SectorSnapshot] = []
    for market_code in markets:
        snapshots.extend(list_latest_snapshots(db, market_code))
    return snapshots


def recommend_sectors_for_user(
    db,
    market: str,
    risk_score: Optional[int] = None,
    risk_tolerance: Optional[str] = None,
    time_horizon_years: Optional[int] = None,
    goal: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    snapshots = list_latest_snapshots(db, market)
    if not snapshots:
        return []

    if not risk_tolerance and risk_score is not None:
        risk_tolerance = _risk_label_from_score(risk_score)

    def _score_snapshot(snapshot: SectorSnapshot) -> Tuple[float, Dict[str, Any]]:
        base = float(snapshot.score)
        suitability = snapshot.suitable_profiles or {}
        bonus = 0.0

        risks = [risk_tag.lower() for risk_tag in (suitability.get("risk") or []) if isinstance(risk_tag, str)]
        if risk_tolerance and risk_tolerance.lower() in risks:
            bonus += 8

        min_h = suitability.get("horizon_years_min")
        max_h = suitability.get("horizon_years_max")
        if time_horizon_years is not None and isinstance(min_h, (int, float)):
            if time_horizon_years >= int(min_h):
                bonus += 4
        if time_horizon_years is not None and isinstance(max_h, (int, float)) and max_h > 0:
            if time_horizon_years <= int(max_h):
                bonus += 4

        goals = [goal_tag.lower() for goal_tag in (suitability.get("goals") or []) if isinstance(goal_tag, str)]
        if goal and goal.lower() in goals:
            bonus += 6

        return base + bonus, {
            "sector": snapshot.sector,
            "market": snapshot.market,
            "score": round(base + bonus, 2),
            "summary": snapshot.sector_summary,
            "momentum": snapshot.momentum,
            "who_should_invest": snapshot.who_should_invest,
            "top_stocks": snapshot.top_stocks,
            "as_of": snapshot.as_of.isoformat() if snapshot.as_of else None,
        }

    ranked = sorted([_score_snapshot(snapshot_item) for snapshot_item in snapshots if _is_valid_number(snapshot_item.score)], key=lambda x: x[0], reverse=True)
    return [row[1] for row in ranked[:limit]]
