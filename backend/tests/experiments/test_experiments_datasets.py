"""Dataset versions: deterministic fixtures, content hashing, snapshot round-trip (pure, no HTTP)."""
import json

import pandas as pd
import pytest

from backend.experiments import datasets as ds
from backend.experiments.store import save_dataset

NAMES = list(ds.FIXTURES)


def _fresh(name):
    spec = ds.FIXTURES[name]
    return ds.build_dataset(
        spec["generator"](), source=f"synthetic:{name}", symbol=spec["symbol"], interval="1d",
        timezone="UTC", adjustment="synthetic", rights_note=ds.SYNTHETIC_RIGHTS,
    )


@pytest.mark.parametrize("name", NAMES)
def test_hash_is_stable_across_two_generations(name):
    assert _fresh(name).content_hash == _fresh(name).content_hash == ds.get_fixture(name).content_hash
    assert ds.HASH_RE.match(ds.get_fixture(name).content_hash)


def test_fixture_shapes():
    gbm, flat = ds.get_fixture("synthetic-gbm-504"), ds.get_fixture("synthetic-flat-60")
    assert gbm.row_count == 504 and gbm.start == "2022-01-03" and gbm.missing_rows == 0
    gaps = sum(1 for prev, cur in zip(gbm.rows, gbm.rows[1:]) if cur[1] != prev[4])
    assert gaps > 400  # opens gap away from the previous close
    assert all(r[2] >= max(r[1], r[4]) and r[3] <= min(r[1], r[4]) for r in gbm.rows)
    assert flat.row_count == 60 and {tuple(r[1:5]) for r in flat.rows} == {(100.0, 100.0, 100.0, 100.0)}
    assert gbm.content_hash != flat.content_hash
    assert "free to redistribute" in gbm.rights_note


def test_hash_changes_when_one_close_changes():
    base = ds.get_fixture("synthetic-gbm-504")
    rows = json.loads(json.dumps(base.rows))
    rows[100][4] += 0.0001
    assert ds.rows_hash(rows) != base.content_hash
    rows[100][4] -= 0.0001
    assert ds.rows_hash(rows) == base.content_hash  # and it is reversible: the hash depends only on content


def test_hash_depends_on_row_order():
    rows = json.loads(json.dumps(ds.get_fixture("synthetic-flat-60").rows))
    # identical prices, so swap two dates to make order observable
    rows[0][0], rows[1][0] = rows[1][0], rows[0][0]
    assert ds.rows_hash(rows) != ds.get_fixture("synthetic-flat-60").content_hash


def test_stored_rows_round_trip_to_identical_frame(db):
    fixture = ds.get_fixture("synthetic-gbm-504")
    row = save_dataset(db, fixture)
    db.expire_all()
    stored = json.loads(db.get(type(row), fixture.content_hash).rows_json)
    assert stored == fixture.rows
    assert ds.rows_hash(stored) == fixture.content_hash
    pd.testing.assert_frame_equal(ds.rows_to_df(stored), ds.rows_to_df(fixture.rows))
    direct = pd.DataFrame(ds.FIXTURES["synthetic-gbm-504"]["generator"]())
    assert direct["close"].tolist() == ds.rows_to_df(stored)["Close"].tolist()


def test_nan_rows_are_counted_and_json_safe():
    candles = ds.FIXTURES["synthetic-flat-60"]["generator"]()
    candles[3]["open"] = float("nan")
    candles[4]["close"] = None
    candles[5]["volume"] = float("inf")
    built = ds.build_dataset(candles, source="provider:yfinance", symbol="X", interval="1d", timezone="UTC",
                             adjustment="provider default", rights_note=ds.PROVIDER_RIGHTS)
    assert built.missing_rows == 2  # NaN open + None close (volume is not an OHLC column)
    json.dumps(built.rows, allow_nan=False)
    assert ds.rows_to_df(built.rows)["Close"].notna().all()  # the engine frame drops the unusable bar


def test_json_safe_and_canonical_json():
    import numpy as np
    safe = ds.json_safe({"a": np.float64("nan"), "b": np.int64(3), "c": [float("inf"), np.float32(1.5)]})
    assert safe == {"a": None, "b": 3, "c": [None, 1.5]}
    assert ds.canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    with pytest.raises(ValueError):
        ds.canonical_json({"x": float("nan")})
