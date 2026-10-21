"""Shared constants/helpers for the experiment tests (own module name: several conftest.py files exist)."""

SPEC = {"strategy": "sma_crossover", "params": {"fast_period": 10, "slow_period": 30}, "symbol": "SYN"}


def spec(**overrides):
    return {**SPEC, **overrides}


GBM = {"fixture": "synthetic-gbm-504"}
FLAT = {"fixture": "synthetic-flat-60"}


async def create(client, headers, dataset=GBM, spec_=None, label=None, expect=201):
    body = {"spec": spec_ if spec_ is not None else spec(), "dataset": dataset}
    if label is not None:
        body["label"] = label
    r = await client.post("/api/experiments/trials", json=body, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()
