"""Golden values: pin fixture content and engine output so any change is deliberate."""
from backend.backtest import service as bt
from backend.experiments import datasets as ds
from backend.experiments import store

GOLDEN_ENGINE_VERSION = "2.2.0"
GOLDEN_FIXTURES = {  # name -> (fixture version, content_hash)
    "synthetic-gbm-504": (1, "91732abf19250dd6f03106234ea2033c7e7b664d6931b4b713e0fafef3f7e3bc"),
    "synthetic-flat-60": (1, "5cf3fd7e78097015afb1918b57ab6dc0e716eb0aa8fda2b212132440bc1aa007"),
}
# synthetic-gbm-504, sma_crossover fast 10 / slow 30, commission_bps 5, slippage_bps 3, default seed (42)
GOLDEN_SPEC = {"strategy": "sma_crossover", "params": {"fast_period": 10, "slow_period": 30}, "symbol": "SYN",
               "commission_bps": 5, "slippage_bps": 3}
GOLDEN_LEDGER_HASH = "0a378d328e9c8278f681342ebb2b9f0fa81c93428255d9eb6977e8318a799217"
GOLDEN_MONTE_CARLO_HASH = "ad53b598800c3bd20302206d9b275cb4e54c05f3b9e415453d003c442a5143e7"
GOLDEN_RESULT_HASH = "f09c142d40aa9c53e330276f720d64440e2cd191dc8654ddd0bf2b2253f0ec54"

CHANGED = "engine/fixture output changed — bump ENGINE_VERSION or the snapshot hash schema (fixture version only if its generator changes) deliberately and update the golden values"


def test_fixture_content_hashes_and_versions_are_pinned():
    actual = {name: (ds.FIXTURES[name]["version"], ds.get_fixture(name).content_hash) for name in ds.FIXTURES}
    assert actual == GOLDEN_FIXTURES, CHANGED


def test_engine_output_is_pinned():
    spec, _, _ = store.validate_spec(GOLDEN_SPEC)
    out = store.execute(ds.rows_to_df(ds.get_fixture("synthetic-gbm-504").rows), spec)
    assert out["result"]["metrics"]["totalTrades"] > 0
    assert (out["ledger_hash"], out["monte_carlo_hash"], out["result_hash"]) == \
           (GOLDEN_LEDGER_HASH, GOLDEN_MONTE_CARLO_HASH, GOLDEN_RESULT_HASH), CHANGED
    assert bt.ENGINE_VERSION == GOLDEN_ENGINE_VERSION, CHANGED
