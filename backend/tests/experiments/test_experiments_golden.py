"""Golden values: pin fixture content and engine output so any change is deliberate."""
from backend.backtest import service as bt
from backend.experiments import datasets as ds
from backend.experiments import store

GOLDEN_ENGINE_VERSION = "2.1.0"
GOLDEN_FIXTURES = {  # name -> (fixture version, content_hash)
    "synthetic-gbm-504": (1, "dc4a9c5c3f93777bbf8fcc695c2816176854e1c48871f45dd5c9df8395f18ed0"),
    "synthetic-flat-60": (1, "9b53d191c4288ed893e8f2a84e02de657b3c498714596131765c86b96fdc322b"),
}
# synthetic-gbm-504, sma_crossover fast 10 / slow 30, commission_bps 5, slippage_bps 3, default seed (42)
GOLDEN_SPEC = {"strategy": "sma_crossover", "params": {"fast_period": 10, "slow_period": 30}, "symbol": "SYN",
               "commission_bps": 5, "slippage_bps": 3}
GOLDEN_LEDGER_HASH = "0a378d328e9c8278f681342ebb2b9f0fa81c93428255d9eb6977e8318a799217"
GOLDEN_MONTE_CARLO_HASH = "9237e9d272731404e7c337ce192624b02936388ebf101fbd955ba56f0241f32d"
GOLDEN_RESULT_HASH = "383d56dd0f0a4adf7cdca43a0c2e8cf2d5891beee0723dc9d5ba1cd957aa69d0"

CHANGED = "engine/fixture output changed — bump ENGINE_VERSION (and fixture version) deliberately and update the golden values"


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
