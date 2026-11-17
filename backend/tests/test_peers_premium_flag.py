"""PEERS_PREMIUM is read from the environment at call time and defaults to disabled."""
import pytest

from backend.peers import comparison_service as cs


def test_premium_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PEERS_PREMIUM", raising=False)
    assert cs.peers_premium_enabled() is False


@pytest.mark.parametrize("value", ["false", "0", "", "no", "yes"])
def test_premium_only_enabled_by_true(monkeypatch, value):
    monkeypatch.setenv("PEERS_PREMIUM", value)
    assert cs.peers_premium_enabled() is False


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_premium_enabled_by_true(monkeypatch, value):
    monkeypatch.setenv("PEERS_PREMIUM", value)
    assert cs.peers_premium_enabled() is True


def test_premium_requires_provider_key_and_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(cs, "FMP_API_KEY", "")
    monkeypatch.setattr(cs, "FINNHUB_API_KEY", "")
    monkeypatch.setenv("PEERS_PREMIUM", "true")
    with pytest.raises(RuntimeError):
        cs.fetch_peer_comparison("AAPL")
