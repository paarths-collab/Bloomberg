"""Invalid strategy params (offline).

Our own validation text is returned as a 400 unchanged. Arbitrary constructor errors get a fixed
400 that lists the accepted parameter names, and their text is never echoed.
"""
import logging

import pytest

from backend.technical import main as technical_main
from backend.technical.core import strategy_service

URL = "/api/technical/analyze"
SECRET = "secret-token-XYZ"


def _get(client, strategy, params):
    return client.get(URL, params={"symbol": "TEST", "strategy": strategy, "params": params})


def test_accepted_parameter_names_come_from_defaults():
    assert strategy_service.get_strategy_parameter_names("sma_crossover") == ["fast_period", "slow_period"]
    assert strategy_service.get_strategy_parameter_names("rsi_momentum") == ["period", "oversold", "overbought"]
    assert strategy_service.get_strategy_parameter_names("no_such_strategy") == []


def test_validation_error_keeps_specific_message(tclient, fetch_calls):
    r = _get(tclient, "sma_crossover", '{"fast_period": 5.7}')
    assert r.status_code == 400
    assert r.json() == {"detail": "'fast_period' must be a positive integer"}
    assert fetch_calls == []


def test_negative_window_keeps_specific_message(tclient, fetch_calls):
    r = _get(tclient, "sma_crossover", '{"fast_period": -3}')
    assert r.status_code == 400
    assert r.json() == {"detail": "'fast_period' must be an integer between 1 and 100000"}
    assert fetch_calls == []


def test_rsi_threshold_order_keeps_specific_message(tclient):
    r = _get(tclient, "rsi_momentum", '{"oversold": 80, "overbought": 20}')
    assert r.status_code == 400
    assert r.json() == {"detail": "'oversold' must be less than 'overbought'"}


def test_unknown_constructor_kwarg_is_400_with_accepted_names(tclient, caplog):
    caplog.set_level(logging.WARNING, logger=technical_main.logger.name)
    r = _get(tclient, "sma_crossover", '{"bogus": 1}')
    assert r.status_code == 400
    assert r.json() == {
        "detail": "Invalid params for strategy 'sma_crossover'. Accepted parameters: fast_period, slow_period"
    }
    assert any(rec.levelno == logging.WARNING and "Invalid params" in rec.getMessage() for rec in caplog.records)


@pytest.mark.parametrize("params", ['{"fast_period": "abc"}', '{"fast_period": 1e400}', '{"fast_period": null}'])
def test_constructor_value_error_is_generic(tclient, params):
    r = _get(tclient, "sma_crossover", params)
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid params for strategy 'sma_crossover'. Accepted parameters: fast_period, slow_period"


def test_constructor_exception_text_is_not_echoed(tclient, monkeypatch):
    def _boom(name, **params):
        raise TypeError(SECRET)

    monkeypatch.setattr(technical_main, "get_strategy", _boom)
    r = _get(tclient, "breakout", '{"lookback": 5}')
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid params for strategy 'breakout'. Accepted parameters: lookback"
    assert SECRET not in r.text


def test_validator_exception_text_is_not_echoed(tclient, monkeypatch):
    def _boom(instance, raw):
        raise TypeError(SECRET)

    monkeypatch.setattr(technical_main, "validate_params", _boom)
    r = _get(tclient, "breakout", '{"lookback": 5}')
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid params for strategy 'breakout'. Accepted parameters: lookback"
    assert SECRET not in r.text
