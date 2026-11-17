"""Offline tests for peers.service.local_sector_peers: cached universe, missing/invalid file handling."""
import json

import pytest

from backend.peers import service


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(service, "_UNIVERSE_CACHE", {})


def _point_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_DATA_DIR", tmp_path)


def test_universe_file_is_parsed_once(monkeypatch, tmp_path):
    _point_data_dir(monkeypatch, tmp_path)
    (tmp_path / "us_stocks.json").write_text(json.dumps([
        {"Symbol": "AAA", "Industry": "Tech", "Company Name": "A"},
        {"Symbol": "BBB", "Industry": "Tech", "Company Name": "B"},
        {"Symbol": "CCC", "Industry": "Energy"},
    ]))
    reads = []
    real = service.Path.read_text
    monkeypatch.setattr(service.Path, "read_text", lambda self, *a, **k: (reads.append(self.name), real(self, *a, **k))[1])
    first = service.local_sector_peers("AAA")
    second = service.local_sector_peers("BBB")
    assert [p["symbol"] for p in first] == ["BBB"] and [p["symbol"] for p in second] == ["AAA"]
    assert first[0]["source"] == "local_sector_universe"
    assert reads.count("us_stocks.json") == 1


def test_missing_file_gives_empty_result_and_is_cached(monkeypatch, tmp_path):
    _point_data_dir(monkeypatch, tmp_path)
    assert service.local_sector_peers("AAPL") == []
    assert service.local_sector_peers("RELIANCE.NS") == []
    assert service._UNIVERSE_CACHE == {"US": [], "IN": []}


@pytest.mark.parametrize("content", ["{not json", '{"a": 1}', "null", '[1, "x", null]', ""])
def test_invalid_file_gives_empty_result(monkeypatch, tmp_path, content):
    _point_data_dir(monkeypatch, tmp_path)
    (tmp_path / "us_stocks.json").write_text(content)
    assert service.local_sector_peers("AAPL") == []


def test_fetch_stock_peers_falls_back_to_empty_without_key_or_file(monkeypatch, tmp_path):
    _point_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(service, "FMP_API_KEY", "")
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    assert service.fetch_stock_peers("AAPL") == []


def test_india_symbols_keep_suffix_and_exclude_self(monkeypatch, tmp_path):
    _point_data_dir(monkeypatch, tmp_path)
    (tmp_path / "nifty500.json").write_text(json.dumps([
        {"Symbol": "AAA", "Industry": "Banks"}, {"Symbol": "BBB", "Industry": "Banks"}, {"Symbol": "CCC", "Industry": "Auto"}]))
    assert [p["symbol"] for p in service.local_sector_peers("AAA.NS")] == ["BBB.NS"]


def test_real_bundled_universe_still_resolves_peers():
    peers = service.local_sector_peers("AAPL")
    assert peers and all(p["symbol"] != "AAPL" for p in peers) and len(peers) <= 10
