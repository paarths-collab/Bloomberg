"""Peer discovery with a labelled local sector-comparable fallback."""
import json
import logging
import os
from pathlib import Path
from typing import List, Dict
import requests

logger = logging.getLogger(__name__)
FMP_API_KEY = os.getenv("FMP_API_KEY", "")


_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_UNIVERSE_FILES = {"IN": "nifty500.json", "US": "us_stocks.json"}
# Parsed universe files, loaded once per process (treat as read-only). A missing or invalid
# file is cached as an empty list so we neither re-read nor raise on every call.
_UNIVERSE_CACHE: Dict[str, List[Dict]] = {}


def _load_universe(market: str) -> List[Dict]:
    cached = _UNIVERSE_CACHE.get(market)
    if cached is not None:
        return cached
    path = _DATA_DIR / _UNIVERSE_FILES[market]
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        records = [r for r in parsed if isinstance(r, dict)] if isinstance(parsed, list) else []
        if not records:
            logger.warning("Local peer universe %s is empty or not a list of records", path.name)
    except (OSError, ValueError):
        logger.warning("Local peer universe %s is missing or invalid", path.name)
        records = []
    _UNIVERSE_CACHE[market] = records
    return records


def local_sector_peers(symbol: str, limit: int = 10) -> List[Dict]:
    """Same-industry names from the bundled universe ("sector comparables", not a similarity
    model). Returns an empty list when the file is missing/invalid or the symbol is unknown."""
    symbol = symbol.upper()
    india = symbol.endswith((".NS", ".BO"))
    base = symbol.rsplit(".", 1)[0] if india else symbol
    records = _load_universe("IN" if india else "US")
    own = next((r for r in records if r.get("Symbol") == base), None)
    if not own or not own.get("Industry"):
        return []
    suffix = symbol[-3:] if india else ""
    return [{"symbol": r["Symbol"] + suffix, "companyName": r.get("Company Name"),
             "sector": r["Industry"], "source": "local_sector_universe"}
            for r in records if r.get("Industry") == own["Industry"] and r.get("Symbol") != base
            and r.get("Symbol")][:limit]


def fetch_stock_peers(symbol: str) -> List[Dict]:
    symbol = symbol.upper()
    key = os.getenv("FMP_API_KEY") or FMP_API_KEY
    if key:
        try:
            response = requests.get("https://financialmodelingprep.com/api/v4/stock_peers",
                                    params={"symbol": symbol, "apikey": key}, timeout=10)
            response.raise_for_status()
            data = response.json()
            peers = []
            for item in data if isinstance(data, list) else [data]:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("peersList"), list):
                    peers.extend({"symbol": s, "source": "fmp"} for s in item["peersList"] if isinstance(s, str) and s != symbol)
                elif item.get("symbol") and item["symbol"] != symbol:
                    peers.append({"symbol": item["symbol"], "companyName": item.get("companyName"), "source": "fmp"})
            if peers:
                return list({p["symbol"]: p for p in peers}.values())
        except (requests.RequestException, ValueError):
            logger.warning("Peer provider unavailable; using local sector comparables")
    return local_sector_peers(symbol)
