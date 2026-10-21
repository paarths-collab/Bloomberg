"""
Trial persistence and execution. Synchronous, pure-engine runs only.

A trial is recorded once the spec validates: dataset or engine failures produce a row with
status="failed" and an error_code (never a 5xx), so failures stay visible next to zero-return runs.
Trial rows are insert-only.

Reproduction caveat: `reproduce_trial` can report a false negative (reproduced=false with no real change in the
code or data) across different CPUs / BLAS builds, because float summation order inside numpy/pandas can differ
by a few ulps. Library versions (python/pandas/numpy) are recorded and compared; hardware is not.
"""
from __future__ import annotations

import json
import logging
import platform
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.backtest import service as bt
from backend.database.models import DatasetVersion, ExperimentTrial
from backend.experiments import datasets as ds
from backend.experiments.datasets import DatasetError, canonical_json, json_safe, sha256_hex

logger = logging.getLogger(__name__)

MAX_TRIALS_PER_USER = 200
MAX_SPEC_JSON_CHARS = 20_000
MAX_ERROR_MESSAGE_CHARS = 300  # experiment_trials.error_message is String(300)
RESULT_HASH_KEYS = ("trades", "equity_curve", "metrics", "assumptions", "ledger")

ENGINE_FAILED_MESSAGE = "The backtest engine failed on this trial."
HEADLINE_KEYS = ("totalReturn", "finalEquity", "totalTrades", "maxDrawdown")


class SpecError(ValueError):
    """The spec is invalid (-> 422, no trial is recorded). The message is client-safe."""


class TrialLimitError(Exception):
    """The user already holds MAX_TRIALS_PER_USER trials (-> 429)."""


class EngineFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class ReproduceError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(message)
        self.status_code, self.error_code, self.message = status_code, error_code, message


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:  # SQLite drops tzinfo; everything is stored in UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def clip_error_message(message: str) -> str:
    """Keep the always-recorded guarantee on databases that enforce column length (Postgres)."""
    message = str(message)
    if len(message) <= MAX_ERROR_MESSAGE_CHARS:
        return message
    return message[: MAX_ERROR_MESSAGE_CHARS - 3] + "..."


def dependency_versions() -> Dict[str, str]:
    return {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__}


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------

def validate_spec(raw: Any) -> Tuple[Dict[str, Any], str, str]:
    """-> (normalised spec, canonical spec json, spec_hash). Raises SpecError."""
    try:
        spec = bt.normalize_spec(raw)
        bt.validate_strategy_params(spec["strategy"], spec["params"])
        bt.get_strategy(spec["strategy"], **spec["params"])
    except (ValueError, TypeError) as exc:  # BacktestInputError is a ValueError; messages are client-safe
        raise SpecError(str(exc))
    try:
        spec_json = canonical_json(spec)
    except (ValueError, TypeError):
        raise SpecError("spec must contain only finite JSON values")
    if len(spec_json) > MAX_SPEC_JSON_CHARS:
        raise SpecError(f"spec is too large (more than {MAX_SPEC_JSON_CHARS} characters)")
    return spec, spec_json, sha256_hex(spec_json)


def merge_variant_spec(parent_spec: Dict[str, Any], changes: Any) -> Dict[str, Any]:
    """Top-level key merge: a key in `changes` replaces the parent's value wholesale (incl. `params`)."""
    if not isinstance(changes, dict) or not changes:
        raise SpecError("changes must be a non-empty object of spec keys")
    return {**parent_spec, **changes}


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

def save_dataset(db: Session, dataset: ds.Dataset) -> DatasetVersion:
    """Insert the version if it is new (content-addressed, so an existing row is identical)."""
    row = db.get(DatasetVersion, dataset.content_hash)
    if row is not None:
        return row
    row = DatasetVersion(
        content_hash=dataset.content_hash, source=dataset.source, symbol=dataset.symbol,
        interval=dataset.interval, timezone=dataset.timezone, start=dataset.start, end=dataset.end,
        row_count=dataset.row_count, missing_rows=dataset.missing_rows, adjustment=dataset.adjustment,
        rights_note=dataset.rights_note, rows_json=canonical_json(dataset.rows),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # a concurrent request stored the same version first
        db.rollback()
        row = db.get(DatasetVersion, dataset.content_hash)
    return row


def dataset_meta(row: DatasetVersion) -> Dict[str, Any]:
    return {
        "content_hash": row.content_hash, "source": row.source, "symbol": row.symbol,
        "interval": row.interval, "timezone": row.timezone, "start": row.start, "end": row.end,
        "row_count": row.row_count, "missing_rows": row.missing_rows, "adjustment": row.adjustment,
        "rights_note": row.rights_note, "available": True,
    }


def _user_has_used(db: Session, user_id: str, content_hash: str) -> bool:
    return db.query(ExperimentTrial.id).filter(
        ExperimentTrial.user_id == user_id, ExperimentTrial.dataset_hash == content_hash
    ).first() is not None


def _frame_from_row(row: DatasetVersion) -> pd.DataFrame:
    """Integrity-checked stored rows -> engine frame. Raises DatasetError(invalid_dataset)."""
    try:
        rows = json.loads(row.rows_json)
    except ValueError:
        rows = None
    if not isinstance(rows, list) or ds.rows_hash(rows) != row.content_hash:
        logger.error("Stored dataset %s failed its integrity check", row.content_hash)
        raise DatasetError("invalid_dataset", "The stored dataset failed its integrity check.")
    return ds.rows_to_df(rows)


def resolve_dataset(db: Session, user_id: str, ref: Dict[str, Any]) -> Tuple[str, pd.DataFrame, str]:
    """
    ref is one of {"fixture": name} | {"dataset_hash": h} | {"provider": {normalised provider request}}.
    Returns (dataset_hash, frame, dataset interval); raises DatasetError. The frame always comes from the
    stored rows, so a first run and a later reproduction see exactly the same data.
    """
    if "fixture" in ref:
        row = save_dataset(db, ds.get_fixture(ref["fixture"]))
    elif "dataset_hash" in ref:
        h = ref["dataset_hash"]
        row = db.get(DatasetVersion, h)
        if row is not None and row.source.startswith("provider:") and not _user_has_used(db, user_id, h):
            row = None  # provider snapshots are only reachable by users who already hold the hash via a trial
        if row is None:
            fixture = ds.fixture_by_hash(h)
            if fixture is None:
                raise DatasetError("dataset_missing", "No stored dataset version matches that hash.")
            row = save_dataset(db, fixture)
    else:
        row = save_dataset(db, ds.fetch_provider_dataset(ref["provider"]))
    return row.content_hash, _frame_from_row(row), row.interval


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute(frame: pd.DataFrame, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Run the engine on a frame -> {"result", "ledger_hash", "result_hash", "monte_carlo_hash"}. May raise anything.
    result_hash covers the full (pre-trim) trades / equity_curve / metrics / assumptions / ledger; the Monte Carlo
    output, including every simulation path, is covered by monte_carlo_hash."""
    result = bt.run_spec(frame, spec)
    return {
        "result": result,
        "ledger_hash": sha256_hex(canonical_json(json_safe(result["ledger"]))),
        "result_hash": sha256_hex(canonical_json(json_safe({k: result[k] for k in RESULT_HASH_KEYS}))),
        "monte_carlo_hash": sha256_hex(canonical_json(json_safe(result["monteCarlo"]))),
    }


def _stored_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON kept on a completed trial. The 1000-path Monte Carlo cloud is omitted (it is covered by
    monte_carlo_hash and regenerated by /reproduce); percentiles, histogram and risk metrics are kept."""
    keys = ("ledger", "equity_curve", "metrics", "trades", "assumptions", "monteCarlo", "spec")
    safe = json_safe({k: result[k] for k in keys})
    mc = {k: v for k, v in safe["monteCarlo"].items() if k != "simulationPaths"}
    mc["simulationPathsOmitted"] = True
    safe["monteCarlo"] = mc
    return safe


def _run_engine(frame: pd.DataFrame, spec: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return execute(frame, spec)
    except bt.BacktestInputError as exc:
        raise EngineFailure("invalid_spec", str(exc))
    except Exception:
        logger.exception("Experiment engine run failed")
        raise EngineFailure("engine_error", ENGINE_FAILED_MESSAGE)


def check_trial_quota(db: Session, user_id: str) -> None:
    count = db.query(func.count(ExperimentTrial.id)).filter(ExperimentTrial.user_id == user_id).scalar()
    if count >= MAX_TRIALS_PER_USER:
        raise TrialLimitError()


def run_and_record_trial(
    db: Session, user_id: str, spec: Dict[str, Any], spec_json: str, spec_hash: str,
    dataset_ref: Dict[str, Any], label: Optional[str], parent_trial_id: Optional[str] = None,
    known_dataset_hash: Optional[str] = None,
) -> ExperimentTrial:
    """
    Resolve the dataset, run the engine and insert the trial (completed or failed). Raises TrialLimitError
    only; dataset / engine failures are recorded as failed trials. `known_dataset_hash` (variants) is kept on
    the row when that hash can no longer be resolved, so the trial still says which data it needed.
    """
    check_trial_quota(db, user_id)
    trial = ExperimentTrial(
        id=uuid.uuid4().hex, user_id=user_id, label=label, parent_trial_id=parent_trial_id,
        spec_json=spec_json, spec_hash=spec_hash, dataset_hash=None,
        dataset_request_json=canonical_json(dataset_ref), engine_version=bt.ENGINE_VERSION,
        environment_json=canonical_json(dependency_versions()), seed=spec["seed"],
        started_at=utcnow(), status="failed",
    )
    try:
        dataset_hash, frame, interval = resolve_dataset(db, user_id, dataset_ref)
        trial.dataset_hash = dataset_hash
        if interval != spec["interval"]:
            raise DatasetError(
                "invalid_dataset",
                f"The dataset interval '{interval}' does not match the spec interval '{spec['interval']}'.",
            )
        out = _run_engine(frame, spec)
        payload = _stored_payload(out["result"])
        trial.status = "completed"
        trial.result_json = canonical_json(payload)
        trial.headline_json = canonical_json({k: payload["metrics"].get(k) for k in HEADLINE_KEYS})
        trial.ledger_hash, trial.monte_carlo_hash = out["ledger_hash"], out["monte_carlo_hash"]
        trial.result_hash = out["result_hash"]
    except (DatasetError, EngineFailure) as exc:
        trial.error_code, trial.error_message = exc.code, clip_error_message(exc.message)
        if trial.dataset_hash is None and known_dataset_hash:
            trial.dataset_hash = known_dataset_hash
    trial.finished_at = utcnow()
    db.add(trial)
    db.commit()
    return trial


# ---------------------------------------------------------------------------
# Reproduction
# ---------------------------------------------------------------------------

def reproduce_trial(db: Session, trial: ExperimentTrial) -> Dict[str, Any]:
    """Re-run the stored spec on the stored dataset version with the current engine. Writes nothing."""
    if trial.status != "completed":
        raise ReproduceError(409, "trial_failed", "A failed trial has no result to reproduce.")
    row = db.get(DatasetVersion, trial.dataset_hash) if trial.dataset_hash else None
    if row is None:
        raise ReproduceError(409, "dataset_missing", "The dataset version this trial ran on is no longer stored.")
    try:
        frame = _frame_from_row(row)
    except DatasetError as exc:
        raise ReproduceError(409, exc.code, exc.message)
    try:
        out = execute(frame, json.loads(trial.spec_json))
    except Exception:
        logger.exception("Experiment reproduction failed for trial %s", trial.id)
        raise ReproduceError(409, "engine_error", "The current engine could not re-run this trial's spec.")

    stored = json.loads(trial.result_json)
    result_identical = out["result_hash"] == trial.result_hash
    ledger_identical = out["ledger_hash"] == trial.ledger_hash
    mc_identical = out["monte_carlo_hash"] == trial.monte_carlo_hash
    metrics_identical = canonical_json(json_safe(out["result"]["metrics"])) == canonical_json(stored["metrics"])
    original_env = json.loads(trial.environment_json) if trial.environment_json else None
    current_env = dependency_versions()
    return {
        "trial_id": trial.id,
        "reproduced": bool(ledger_identical and mc_identical and metrics_identical and result_identical),
        "ledger_identical": ledger_identical,
        "result_identical": result_identical,
        "monte_carlo_identical": mc_identical,
        "metrics_identical": metrics_identical,
        "original_engine_version": trial.engine_version,
        "current_engine_version": bt.ENGINE_VERSION,
        "engine_version_changed": trial.engine_version != bt.ENGINE_VERSION,
        "ledger_hash_original": trial.ledger_hash,
        "ledger_hash_now": out["ledger_hash"],
        "result_hash_original": trial.result_hash,
        "result_hash_now": out["result_hash"],
        "monte_carlo_hash_original": trial.monte_carlo_hash,
        "monte_carlo_hash_now": out["monte_carlo_hash"],
        "dependency_versions_original": original_env,
        "dependency_versions_now": current_env,
        "dependency_versions_changed": original_env != current_env,
        "spec_hash": trial.spec_hash,
        "dataset_hash": trial.dataset_hash,
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def trial_summary(t: ExperimentTrial) -> Dict[str, Any]:
    return {
        "id": t.id,
        "label": t.label,
        "status": t.status,
        "error_code": t.error_code,
        "error_message": t.error_message,
        "started_at": as_utc_iso(t.started_at),
        "finished_at": as_utc_iso(t.finished_at),
        "spec_hash": t.spec_hash,
        "dataset_hash": t.dataset_hash,
        "engine_version": t.engine_version,
        "parent_trial_id": t.parent_trial_id,
        "ledger_hash": t.ledger_hash,
        "result_hash": t.result_hash,
        "monte_carlo_hash": t.monte_carlo_hash,
        "metrics": json.loads(t.headline_json) if t.headline_json else None,
    }


def trial_detail(db: Session, t: ExperimentTrial) -> Dict[str, Any]:
    row = db.get(DatasetVersion, t.dataset_hash) if t.dataset_hash else None
    if row is not None:
        dataset: Optional[Dict[str, Any]] = dataset_meta(row)
    elif t.dataset_hash:
        dataset = {"content_hash": t.dataset_hash, "available": False}  # snapshot no longer stored
    else:
        dataset = None
    return {
        **trial_summary(t),
        "seed": t.seed,
        "spec": json.loads(t.spec_json),
        "dataset_request": json.loads(t.dataset_request_json) if t.dataset_request_json else None,
        "dataset": dataset,
        "dependency_versions": json.loads(t.environment_json) if t.environment_json else None,
        "result": json.loads(t.result_json) if t.result_json else None,
    }
