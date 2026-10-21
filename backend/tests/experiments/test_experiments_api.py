"""Experiment-trial API: create / list / detail / reproduce / variants, failures, isolation (offline)."""
import json

import pytest
from exp_helpers import FLAT, GBM, create, spec

from backend.backtest import service as bt
from backend.database.models import DatasetVersion, ExperimentTrial
from backend.experiments import datasets as ds
from backend.experiments import store

BASE = "/api/experiments"


def provider_candles(tag=1):
    """GBM-shaped bars that differ from the fixture (dataset rows are content-addressed, so provider data
    byte-identical to a fixture would share its row and its synthetic labels)."""
    candles = ds.FIXTURES["synthetic-gbm-504"]["generator"]()
    candles[0]["volume"] += tag
    return candles


async def _detail(client, headers, trial_id):
    r = await client.get(f"{BASE}/trials/{trial_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r


async def test_fixtures_list_is_public_and_matches_hashes(client):
    r = await client.get(f"{BASE}/datasets/fixtures")
    assert r.status_code == 200
    by_name = {f["name"]: f for f in r.json()}
    assert by_name["synthetic-gbm-504"]["rows"] == 504 and by_name["synthetic-flat-60"]["rows"] == 60
    assert by_name["synthetic-gbm-504"]["content_hash"] == ds.get_fixture("synthetic-gbm-504").content_hash
    assert all(f["description"] for f in by_name.values())


async def test_create_completed_trial_detail_and_reproduce(client, user):
    created = await create(client, user, label="  baseline  ")
    assert created["status"] == "completed" and created["error_code"] is None
    assert created["label"] == "baseline" and created["parent_trial_id"] is None
    assert created["engine_version"] == bt.ENGINE_VERSION
    assert created["metrics"]["totalTrades"] > 0  # the GBM fixture really trades under sma_crossover

    detail = (await _detail(client, user, created["id"])).json()
    assert detail["ledger_hash"] == created["ledger_hash"] and len(detail["ledger_hash"]) == 64
    assert len(detail["monte_carlo_hash"]) == 64 and len(detail["spec_hash"]) == 64
    assert detail["dataset_hash"] == ds.get_fixture("synthetic-gbm-504").content_hash
    result = detail["result"]
    assert result["ledger"] and result["ledger"][0]["kind"] == "fill"
    for key in ("equity_curve", "metrics", "trades", "assumptions", "monteCarlo", "spec"):
        assert key in result
    assert result["monteCarlo"]["seed"] == 42 and result["monteCarlo"]["simulationPathsOmitted"] is True
    assert "simulationPaths" not in result["monteCarlo"]
    assert result["assumptions"]["engineVersion"] == bt.ENGINE_VERSION
    assert detail["dataset"]["row_count"] == 504 and detail["dataset"]["source"] == "synthetic:synthetic-gbm-504"
    assert "rows" not in detail["dataset"] and "rows_json" not in detail["dataset"]
    assert detail["dataset"]["rights_note"] == "synthetic data, free to redistribute"
    assert set(detail["dependency_versions"]) == {"python", "pandas", "numpy"}
    json.dumps(detail, allow_nan=False)

    rep = await client.post(f"{BASE}/trials/{created['id']}/reproduce", headers=user)
    assert rep.status_code == 200, rep.text
    body = rep.json()
    assert body["reproduced"] is True and body["trial_id"] == created["id"]
    assert body["ledger_identical"] and body["monte_carlo_identical"] and body["metrics_identical"]
    assert body["ledger_hash_original"] == body["ledger_hash_now"] == created["ledger_hash"]
    assert body["monte_carlo_hash_original"] == body["monte_carlo_hash_now"] == created["monte_carlo_hash"]
    assert body["original_engine_version"] == body["current_engine_version"] == bt.ENGINE_VERSION
    assert body["engine_version_changed"] is False and body["dependency_versions_changed"] is False

    # reproduce is read-only: no new trial, the stored detail is untouched
    assert len((await client.get(f"{BASE}/trials", headers=user)).json()) == 1
    assert (await _detail(client, user, created["id"])).json() == detail


async def test_same_spec_and_data_give_same_hashes_in_two_trials(client, user):
    a, b = await create(client, user), await create(client, user)
    assert a["id"] != b["id"]
    assert (a["spec_hash"], a["dataset_hash"], a["ledger_hash"], a["monte_carlo_hash"]) == \
           (b["spec_hash"], b["dataset_hash"], b["ledger_hash"], b["monte_carlo_hash"])


async def test_seed_changes_monte_carlo_hash_but_not_ledger_hash(client, user):
    a = await create(client, user, spec_=spec(seed=1))
    b = await create(client, user, spec_=spec(seed=2))
    assert a["ledger_hash"] == b["ledger_hash"] and a["monte_carlo_hash"] != b["monte_carlo_hash"]
    assert a["spec_hash"] != b["spec_hash"]


async def test_variant_is_new_distinct_trial_and_leaves_original_untouched(client, user):
    original = await create(client, user)
    before = (await _detail(client, user, original["id"])).content

    r = await client.post(f"{BASE}/trials/{original['id']}/variants",
                          json={"changes": {"fee_per_fill": 1}, "label": "with fees"}, headers=user)
    assert r.status_code == 201, r.text
    variant = r.json()
    assert variant["id"] != original["id"] and variant["parent_trial_id"] == original["id"]
    assert variant["status"] == "completed" and variant["label"] == "with fees"
    assert variant["spec_hash"] != original["spec_hash"]
    assert variant["dataset_hash"] == original["dataset_hash"]
    assert variant["metrics"]["finalEquity"] != original["metrics"]["finalEquity"]
    assert variant["metrics"]["totalReturn"] != original["metrics"]["totalReturn"]
    assert variant["ledger_hash"] != original["ledger_hash"]
    vd = (await _detail(client, user, variant["id"])).json()
    assert vd["spec"]["fee_per_fill"] == 1 and vd["spec"]["params"] == {"fast_period": 10, "slow_period": 30}

    assert (await _detail(client, user, original["id"])).content == before  # byte-identical
    listed = (await client.get(f"{BASE}/trials", headers=user)).json()
    assert [t["id"] for t in listed] == [variant["id"], original["id"]]  # newest first, both visible

    # commission variant (spec allows either) and a no-op change are handled
    r = await client.post(f"{BASE}/trials/{original['id']}/variants", json={"changes": {"commission_bps": 10}}, headers=user)
    assert r.status_code == 201 and r.json()["spec_hash"] not in (original["spec_hash"], variant["spec_hash"])
    for bad in ({}, {"fee_per_fill": 0}, {"bogus": 1}, {"fee_per_fill": -1}, {"strategy": "nope"}):
        r = await client.post(f"{BASE}/trials/{original['id']}/variants", json={"changes": bad}, headers=user)
        assert r.status_code == 422, (bad, r.text)
    assert len((await client.get(f"{BASE}/trials", headers=user)).json()) == 3  # rejected variants recorded nothing


async def test_variant_params_replace_wholesale(client, user):
    original = await create(client, user)
    r = await client.post(f"{BASE}/trials/{original['id']}/variants",
                          json={"changes": {"params": {"fast_period": 5, "slow_period": 20}}}, headers=user)
    assert r.status_code == 201
    assert (await _detail(client, user, r.json()["id"])).json()["spec"]["params"] == {"fast_period": 5, "slow_period": 20}


async def test_provider_failure_is_a_visible_failed_trial(client, user, patch_fetch):
    patch_fetch(exc=bt.MarketDataError("socket exploded: secret-host.internal"))
    failed = await create(client, user, dataset={"symbol": "aapl", "range": "1y"})
    assert failed["status"] == "failed" and failed["error_code"] == "data_unavailable"
    assert failed["metrics"] is None and failed["ledger_hash"] is None and failed["dataset_hash"] is None
    assert "secret-host" not in json.dumps(failed) and "exploded" not in json.dumps(failed)
    detail = (await _detail(client, user, failed["id"])).json()
    assert detail["result"] is None and detail["dataset"] is None
    assert detail["dataset_request"] == {"provider": {
        "symbol": "AAPL", "interval": "1d", "market": "us", "range": "1y", "start": None, "end": None}}
    assert detail["spec"]["strategy"] == "sma_crossover"
    listed = (await client.get(f"{BASE}/trials", headers=user)).json()
    assert [(t["id"], t["status"], t["error_code"], t["metrics"]) for t in listed] == \
           [(failed["id"], "failed", "data_unavailable", None)]

    rep = await client.post(f"{BASE}/trials/{failed['id']}/reproduce", headers=user)
    assert rep.status_code == 409 and rep.json()["error_code"] == "trial_failed"
    var = await client.post(f"{BASE}/trials/{failed['id']}/variants", json={"changes": {"fee_per_fill": 1}}, headers=user)
    assert var.status_code == 409 and var.json()["error_code"] == "dataset_missing"


async def test_unexpected_fetch_exception_is_also_data_unavailable(client, user, patch_fetch):
    patch_fetch(exc=RuntimeError("boom with details"))
    failed = await create(client, user, dataset={"symbol": "MSFT", "start": "2023-01-02", "end": "2023-06-30"})
    assert failed["error_code"] == "data_unavailable" and "boom" not in json.dumps(failed)


async def test_empty_provider_result_is_failed_no_data(client, user, patch_fetch):
    patch_fetch(candles=[])
    failed = await create(client, user, dataset={"symbol": "ZZZZ", "market": "india"})
    assert failed["status"] == "failed" and failed["error_code"] == "no_data" and failed["metrics"] is None


async def test_provider_snapshot_is_stored_and_reproducible_offline(client, user, patch_fetch, db):
    patch_fetch(candles=provider_candles())
    trial = await create(client, user, dataset={"symbol": "aapl", "range": "2y"})
    assert trial["status"] == "completed"
    detail = (await _detail(client, user, trial["id"])).json()
    meta = detail["dataset"]
    assert meta["source"] == "provider:yfinance" and meta["adjustment"] == "provider default"
    assert meta["rights_note"] == "provider data; redistribution rights not established"
    assert meta["symbol"] == "AAPL" and meta["row_count"] == 504 and meta["missing_rows"] == 0
    # the provider now fails / changes: reproduction still uses the stored snapshot
    patch_fetch(exc=bt.MarketDataError("down"))
    rep = (await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)).json()
    assert rep["reproduced"] is True
    # and a variant forks from the snapshot (it never re-fetches)
    var = await client.post(f"{BASE}/trials/{trial['id']}/variants", json={"changes": {"slippage_bps": 5}}, headers=user)
    assert var.status_code == 201 and var.json()["status"] == "completed"


async def test_provider_dataset_hash_is_not_shared_with_other_users(client, new_user, patch_fetch):
    a, b = await new_user(), await new_user()
    patch_fetch(candles=provider_candles(7))
    owned = await create(client, a, dataset={"symbol": "AAPL"})
    # same hash, owner: fine
    again = await create(client, a, dataset={"dataset_hash": owned["dataset_hash"]})
    assert again["status"] == "completed" and again["dataset_hash"] == owned["dataset_hash"]
    # other user referencing the provider snapshot by hash: indistinguishable from "missing"
    stolen = await create(client, b, dataset={"dataset_hash": owned["dataset_hash"]})
    assert stolen["status"] == "failed" and stolen["error_code"] == "dataset_missing" and stolen["dataset_hash"] is None
    # unknown hash behaves the same
    unknown = await create(client, b, dataset={"dataset_hash": "0" * 64})
    assert unknown["error_code"] == "dataset_missing"


async def test_oversized_provider_dataset_is_failed_invalid_dataset(client, user, patch_fetch):
    """Decision: the bar count is only known after the fetch, so >5000 bars is a recorded failed trial
    (invalid_dataset), not a 422."""
    big = [{"date": f"{i:06d}", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1} for i in range(ds.MAX_BARS + 1)]
    patch_fetch(candles=big)
    failed = await create(client, user, dataset={"symbol": "BIG"})
    assert failed["status"] == "failed" and failed["error_code"] == "invalid_dataset" and failed["metrics"] is None
    patch_fetch(candles=big[: ds.MAX_BARS])  # exactly the cap is accepted
    assert (await create(client, user, dataset={"symbol": "BIG"}))["status"] == "completed"


async def test_zero_return_completed_trial_is_distinct_from_failed(client, user, patch_fetch):
    patch_fetch(candles=[])
    failed = await create(client, user, dataset={"symbol": "NONE"})
    flat = await create(client, user, dataset=FLAT)
    assert flat["status"] == "completed" and flat["error_code"] is None
    assert flat["metrics"]["totalReturn"] == 0 and flat["metrics"]["totalTrades"] == 0
    assert flat["metrics"]["finalEquity"] == 100000.0 and flat["ledger_hash"] and flat["dataset_hash"]
    listed = {t["id"]: t for t in (await client.get(f"{BASE}/trials", headers=user)).json()}
    assert listed[flat["id"]]["status"] == "completed" and listed[flat["id"]]["metrics"]["totalReturn"] == 0
    assert listed[failed["id"]]["status"] == "failed" and listed[failed["id"]]["metrics"] is None
    assert listed[failed["id"]]["error_code"] == "no_data" and listed[flat["id"]]["error_code"] is None
    detail = (await _detail(client, user, flat["id"])).json()
    assert detail["result"]["ledger"] == [] and detail["result"]["trades"] == []
    rep = (await client.post(f"{BASE}/trials/{flat['id']}/reproduce", headers=user)).json()
    assert rep["reproduced"] is True


async def test_dataset_interval_mismatch_is_a_failed_trial(client, user):
    failed = await create(client, user, spec_=spec(interval="1wk"))
    assert failed["status"] == "failed" and failed["error_code"] == "invalid_dataset"
    assert "1wk" in failed["error_message"] and failed["dataset_hash"] == ds.get_fixture("synthetic-gbm-504").content_hash


async def test_engine_failure_is_a_failed_trial_with_generic_message(client, user, monkeypatch):
    def broken(df, spec_):
        raise RuntimeError("internal path /srv/secret/engine.py exploded")

    monkeypatch.setattr(bt, "run_spec", broken)
    failed = await create(client, user)
    assert failed["status"] == "failed" and failed["error_code"] == "engine_error"
    assert "secret" not in json.dumps(failed) and failed["metrics"] is None
    assert failed["dataset_hash"] == ds.get_fixture("synthetic-gbm-504").content_hash  # data resolved, engine failed


async def test_reproduce_after_dataset_row_deleted_is_409_dataset_missing(client, user, db):
    trial = await create(client, user)
    db.query(DatasetVersion).filter(DatasetVersion.content_hash == trial["dataset_hash"]).delete()
    db.commit()
    rep = await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)
    assert rep.status_code == 409
    assert rep.json()["error_code"] == "dataset_missing" and rep.json()["trial_id"] == trial["id"]
    detail = (await _detail(client, user, trial["id"])).json()
    assert detail["dataset"] == {"content_hash": trial["dataset_hash"], "available": False}
    assert detail["result"]["ledger"]  # the recorded result stays readable


async def test_tampered_dataset_row_is_detected(client, user, db):
    trial = await create(client, user)
    row = db.get(DatasetVersion, trial["dataset_hash"])
    rows = json.loads(row.rows_json)
    rows[10][4] += 1.0
    row.rows_json = json.dumps(rows)
    db.commit()
    rep = await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)
    assert rep.status_code == 409 and rep.json()["error_code"] == "invalid_dataset"
    row.rows_json = ds.canonical_json(ds.get_fixture("synthetic-gbm-504").rows)  # restore for other tests
    db.commit()


async def test_engine_version_mismatch_is_reported(client, user, db):
    trial = await create(client, user)
    row = db.get(ExperimentTrial, trial["id"])
    row.engine_version = "1.0.0"
    db.commit()
    rep = (await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)).json()
    assert rep["original_engine_version"] == "1.0.0" and rep["current_engine_version"] == bt.ENGINE_VERSION
    assert rep["engine_version_changed"] is True
    assert rep["reproduced"] is True  # same outputs; the version difference is reported, not hidden
    assert (await _detail(client, user, trial["id"])).json()["engine_version"] == "1.0.0"


async def test_changed_engine_output_is_reported_as_not_reproduced(client, user, monkeypatch):
    trial = await create(client, user)
    real = bt.run_spec

    def drifted(df, spec_, **kw):
        out = real(df, spec_, **kw)
        out["ledger"] = [dict(e, price=e["price"] + 0.01) for e in out["ledger"]]
        return out

    monkeypatch.setattr(bt, "run_spec", drifted)
    monkeypatch.setattr(bt, "ENGINE_VERSION", "9.9.9")
    body = (await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)).json()
    assert body["reproduced"] is False and body["ledger_identical"] is False
    assert body["monte_carlo_identical"] is True and body["ledger_hash_original"] != body["ledger_hash_now"]
    assert body["current_engine_version"] == "9.9.9" and body["engine_version_changed"] is True


async def test_dependency_version_difference_is_reported(client, user, monkeypatch):
    trial = await create(client, user)
    monkeypatch.setattr(store, "dependency_versions", lambda: {"python": "0.0", "pandas": "0.0", "numpy": "0.0"})
    body = (await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)).json()
    assert body["dependency_versions_changed"] is True and body["dependency_versions_now"]["pandas"] == "0.0"
    assert body["dependency_versions_original"]["pandas"] != "0.0" and body["reproduced"] is True


async def test_isolation_between_users_and_auth(client, new_user):
    a, b = await new_user(), await new_user()
    trial = await create(client, a)
    tid = trial["id"]
    assert (await client.get(f"{BASE}/trials/{tid}", headers=b)).status_code == 404
    assert (await client.post(f"{BASE}/trials/{tid}/reproduce", headers=b)).status_code == 404
    assert (await client.post(f"{BASE}/trials/{tid}/variants", json={"changes": {"fee_per_fill": 1}}, headers=b)).status_code == 404
    assert (await client.get(f"{BASE}/trials", headers=b)).json() == []
    assert [t["id"] for t in (await client.get(f"{BASE}/trials", headers=a)).json()] == [tid]
    assert (await client.get(f"{BASE}/trials/{'0' * 32}", headers=a)).status_code == 404
    assert (await client.get(f"{BASE}/trials/not-an-id", headers=a)).status_code == 404
    # B's failed variant attempts created nothing for either user
    assert len((await client.get(f"{BASE}/trials", headers=a)).json()) == 1

    body = {"spec": spec(), "dataset": GBM}
    for method, path, kw in [
        ("get", "/trials", {}), ("get", f"/trials/{tid}", {}), ("post", "/trials", {"json": body}),
        ("post", f"/trials/{tid}/reproduce", {}), ("post", f"/trials/{tid}/variants", {"json": {"changes": {"fee_per_fill": 1}}}),
    ]:
        assert (await getattr(client, method)(BASE + path, **kw)).status_code == 401, path
    bad = {"Authorization": "Bearer nonsense"}
    assert (await client.get(f"{BASE}/trials", headers=bad)).status_code == 401


async def test_client_cannot_choose_owner(client, new_user):
    a, b = await new_user(), await new_user()
    r = await client.post(f"{BASE}/trials", json={"spec": spec(), "dataset": GBM, "user_id": "someone-else"}, headers=a)
    assert r.status_code == 422  # unknown body field
    assert (await client.get(f"{BASE}/trials", headers=b)).json() == []


async def test_invalid_requests_are_422_and_record_nothing(client, user):
    cases = [
        {"spec": spec(bogus_key=1), "dataset": GBM},                     # unknown spec key
        {"spec": spec(strategy="no_such_strategy"), "dataset": GBM},
        {"spec": spec(params={"nope": 1}), "dataset": GBM},
        {"spec": spec(commission_bps=-1), "dataset": GBM},
        {"spec": {"params": {}}, "dataset": GBM},                        # no strategy
        {"spec": spec(), "dataset": {"fixture": "does-not-exist"}},
        {"spec": spec(), "dataset": {}},
        {"spec": spec(), "dataset": {"fixture": "synthetic-gbm-504", "symbol": "AAPL"}},
        {"spec": spec(), "dataset": {"symbol": "AAPL", "range": "7y"}},
        {"spec": spec(), "dataset": {"symbol": "AAPL", "interval": "2s"}},
        {"spec": spec(), "dataset": {"symbol": "AAPL", "start": "2023-01-01"}},
        {"spec": spec(), "dataset": {"symbol": "AAPL", "start": "2023-06-01", "end": "2023-01-01"}},
        {"spec": spec(), "dataset": {"symbol": "bad symbol!"}},
        {"spec": spec(), "dataset": {"dataset_hash": "xyz"}},
        {"spec": spec(), "dataset": {"interval": "1d"}},                 # provider field without a symbol
        {"spec": spec(), "dataset": GBM, "label": "x" * 201},
        {"spec": spec(params={"fast_period": 10, "slow_period": 30, "blob": "x" * 30000}), "dataset": GBM},
        {"dataset": GBM},
    ]
    for body in cases:
        r = await client.post(f"{BASE}/trials", json=body, headers=user)
        assert r.status_code == 422, (body, r.status_code, r.text[:200])
    assert (await client.get(f"{BASE}/trials", headers=user)).json() == []


async def test_non_finite_json_body_is_rejected_cleanly(client, user):
    raw = '{"spec": {"strategy": "sma_crossover", "initial_capital": NaN}, "dataset": {"fixture": "synthetic-gbm-504"}}'
    r = await client.post(f"{BASE}/trials", content=raw, headers={**user, "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json() == {"detail": "There was an error parsing the body"}
    raw = '{"spec": {"strategy": "sma_crossover", "params": {"fast_period": 5, "x": Infinity}}, "dataset": {"fixture": "synthetic-gbm-504"}}'
    r = await client.post(f"{BASE}/trials", content=raw, headers={**user, "Content-Type": "application/json"})
    assert r.status_code == 400
    raw = '{"spec": {"strategy": "sma_crossover", "params": {"x": 1e999}}, "dataset": {"fixture": "synthetic-gbm-504"}}'
    r = await client.post(f"{BASE}/trials", content=raw, headers={**user, "Content-Type": "application/json"})
    assert r.status_code == 400
    assert (await client.get(f"{BASE}/trials", headers=user)).json() == []


async def test_trial_limit_per_user_is_429(client, new_user, monkeypatch):
    monkeypatch.setattr(store, "MAX_TRIALS_PER_USER", 2)
    a, b = await new_user(), await new_user()
    await create(client, a, dataset=FLAT)
    await create(client, a, dataset=FLAT)
    r = await client.post(f"{BASE}/trials", json={"spec": spec(), "dataset": FLAT}, headers=a)
    assert r.status_code == 429
    assert len((await client.get(f"{BASE}/trials", headers=a)).json()) == 2
    assert (await create(client, b, dataset=FLAT))["status"] == "completed"  # other users are unaffected


async def test_long_error_message_is_truncated_to_the_column_size(client, user, monkeypatch):
    def rejected(df, spec_, **kw):
        raise bt.BacktestInputError("x" * 1000)

    monkeypatch.setattr(bt, "run_spec", rejected)
    failed = await create(client, user)
    assert failed["error_code"] == "invalid_spec"
    assert len(failed["error_message"]) == store.MAX_ERROR_MESSAGE_CHARS == 300
    assert failed["error_message"].endswith("...") and failed["error_message"].startswith("xxx")
    assert store.clip_error_message("short") == "short"


async def test_provider_bars_must_be_sorted_with_unique_dates(client, user, patch_fetch):
    good = provider_candles(3)
    for bad in (list(reversed(good)), good[:10] + [good[9]] + good[10:], good[:5] + good[6:7] + good[5:6] + good[7:]):
        patch_fetch(candles=bad)
        failed = await create(client, user, dataset={"symbol": "SRT"})
        assert failed["status"] == "failed" and failed["error_code"] == "invalid_dataset"
        assert "sorted" in failed["error_message"] and failed["dataset_hash"] is None
    patch_fetch(candles=good)
    assert (await create(client, user, dataset={"symbol": "SRT"}))["status"] == "completed"


async def test_result_hash_is_reported_and_stored(client, user):
    trial = await create(client, user)
    assert len(trial["result_hash"]) == 64
    body = (await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)).json()
    assert body["result_identical"] is True and body["result_hash_original"] == body["result_hash_now"] == trial["result_hash"]
    other = await create(client, user, spec_=spec(fee_per_fill=1))
    assert other["result_hash"] != trial["result_hash"]


async def test_drift_outside_ledger_is_caught_by_result_hash(client, user, monkeypatch):
    """Only equity_curve changes: ledger, Monte Carlo and metrics hashes stay equal, result_hash does not."""
    trial = await create(client, user)
    real = bt.run_spec

    def drifted(df, spec_, **kw):
        out = real(df, spec_, **kw)
        out["equity_curve"] = [dict(p, benchmark=p["benchmark"] + 1) for p in out["equity_curve"]]
        return out

    monkeypatch.setattr(bt, "run_spec", drifted)
    body = (await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)).json()
    assert body["ledger_identical"] and body["monte_carlo_identical"] and body["metrics_identical"]
    assert body["result_identical"] is False and body["reproduced"] is False


async def test_monte_carlo_hash_covers_the_full_output_including_simulation_paths(client, user, monkeypatch):
    trial = await create(client, user)
    stored = (await _detail(client, user, trial["id"])).json()["result"]["monteCarlo"]
    assert "simulationPaths" not in stored  # the stored copy is trimmed ...
    real = bt.run_spec

    def drifted(df, spec_, **kw):
        out = real(df, spec_, **kw)
        out["monteCarlo"]["simulationPaths"][0][0] += 0.01  # ... so only the hash can notice this
        return out

    monkeypatch.setattr(bt, "run_spec", drifted)
    body = (await client.post(f"{BASE}/trials/{trial['id']}/reproduce", headers=user)).json()
    assert body["monte_carlo_identical"] is False and body["reproduced"] is False
    assert body["ledger_identical"] is True and body["metrics_identical"] is True and body["result_identical"] is True
    assert body["monte_carlo_hash_original"] != body["monte_carlo_hash_now"]


def test_save_dataset_survives_a_concurrent_insert_race(db, monkeypatch):
    from backend.database.connection import SessionLocal
    from backend.database.models import DatasetVersion

    fixture = ds.get_fixture("synthetic-flat-60")
    store.save_dataset(db, fixture)  # another request already stored this version
    SessionLocal.configure(bind=db.get_bind())
    racer = SessionLocal()  # a fresh session: it has not loaded the row
    try:
        real_get, calls = racer.get, []

        def get_once_missing(model, key, *a, **kw):
            calls.append(key)
            return None if len(calls) == 1 else real_get(model, key, *a, **kw)

        monkeypatch.setattr(racer, "get", get_once_missing)
        row = store.save_dataset(racer, fixture)  # insert hits the primary key -> IntegrityError -> re-read
        assert len(calls) == 2 and row is not None and row.content_hash == fixture.content_hash
        assert racer.query(DatasetVersion).filter_by(content_hash=fixture.content_hash).count() == 1
    finally:
        racer.close()
