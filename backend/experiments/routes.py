"""
Experiment-trial API: record, list, reopen, reproduce and fork backtest runs.

Every route except GET /datasets/fixtures requires a bearer token; the owner is always the token's
subject (never a client-supplied id) and other users' trials answer 404. Runs are synchronous.

Failure policy:
  * a request that cannot become a trial (bad body, unknown spec key / strategy / fixture, bad provider
    fields) -> 422 and nothing is recorded;
  * once the body and spec validate, a trial row is ALWAYS recorded: dataset or engine failures give HTTP 201
    with status "failed" + error_code, so they are never confused with a completed zero-return run;
  * unexpected errors fall through to the app's generic 500 (no exception text).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from backend.auth.security import require_user
from backend.database.connection import get_db
from backend.database.models import ExperimentTrial
from backend.experiments import datasets as ds
from backend.experiments import store
from backend.common.json_routes import StrictJSONRoute

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experiments", tags=["Experiments"], route_class=StrictJSONRoute)

TRIAL_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_LIST = 200


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DatasetRef(BaseModel):
    """Exactly one of: fixture | dataset_hash | provider fields (symbol [+ interval, range | start+end, market])."""
    model_config = ConfigDict(extra="forbid")

    fixture: Optional[str] = Field(default=None, max_length=80)
    dataset_hash: Optional[str] = Field(default=None, max_length=64)
    symbol: Optional[str] = Field(default=None, max_length=40)
    interval: Optional[str] = Field(default=None, max_length=10)
    range: Optional[str] = Field(default=None, max_length=10)
    start: Optional[str] = Field(default=None, max_length=32)
    end: Optional[str] = Field(default=None, max_length=32)
    market: Optional[str] = Field(default=None, max_length=10)

    def resolve_ref(self) -> Dict[str, Any]:
        """-> the internal dataset ref. Raises ValueError (-> 422)."""
        provider_fields = (self.symbol, self.interval, self.range, self.start, self.end, self.market)
        modes = [self.fixture is not None, self.dataset_hash is not None, any(f is not None for f in provider_fields)]
        if sum(modes) != 1:
            raise ValueError("dataset must be exactly one of: {fixture}, {dataset_hash}, or provider fields")
        if self.fixture is not None:
            if self.fixture not in ds.FIXTURES:
                raise ValueError(f"Unknown fixture '{self.fixture}'. Available: {', '.join(ds.FIXTURES)}")
            return {"fixture": self.fixture}
        if self.dataset_hash is not None:
            if not ds.HASH_RE.match(self.dataset_hash):
                raise ValueError("dataset_hash must be a 64-character lowercase hex sha256")
            return {"dataset_hash": self.dataset_hash}
        if self.symbol is None:
            raise ValueError("provider datasets require dataset.symbol")
        return {"provider": ds.validate_provider_request(
            self.symbol, self.interval, self.range, self.start, self.end, self.market)}


def _clean_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CreateTrialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: Dict[str, Any]
    dataset: DatasetRef
    label: Optional[str] = Field(default=None, max_length=200)

    @field_validator("label")
    @classmethod
    def _label(cls, v):
        return _clean_label(v)


class VariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: Dict[str, Any]
    label: Optional[str] = Field(default=None, max_length=200)

    @field_validator("label")
    @classmethod
    def _label(cls, v):
        return _clean_label(v)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _get_owned(db: Session, trial_id: str, user: str) -> ExperimentTrial:
    trial = None
    if TRIAL_ID_RE.match(trial_id):
        trial = db.query(ExperimentTrial).filter(
            ExperimentTrial.id == trial_id, ExperimentTrial.user_id == user
        ).first()
    if trial is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    return trial


def _record(db: Session, user: str, spec, spec_json, spec_hash, dataset_ref, label, parent=None, known_hash=None):
    try:
        trial = store.run_and_record_trial(
            db, user, spec, spec_json, spec_hash, dataset_ref, label,
            parent_trial_id=parent, known_dataset_hash=known_hash,
        )
    except store.TrialLimitError:
        raise HTTPException(status_code=429, detail=f"Trial limit reached ({store.MAX_TRIALS_PER_USER} per user)")
    return JSONResponse(status_code=201, content=store.trial_summary(trial))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/datasets/fixtures")
def list_fixtures() -> List[Dict[str, Any]]:
    """Built-in deterministic synthetic datasets (public)."""
    return ds.list_fixtures()


@router.post("/trials", status_code=201)
def create_trial(body: CreateTrialRequest, user: str = Depends(require_user), db: Session = Depends(get_db)):
    try:
        dataset_ref = body.dataset.resolve_ref()
        spec, spec_json, spec_hash = store.validate_spec(body.spec)
    except ValueError as exc:  # SpecError is a ValueError; all messages are client-safe
        raise _unprocessable(str(exc))
    return _record(db, user, spec, spec_json, spec_hash, dataset_ref, body.label)


@router.get("/trials")
def list_trials(user: str = Depends(require_user), db: Session = Depends(get_db)):
    """The caller's trials, newest first (headline metrics only for completed trials)."""
    rows = (
        db.query(ExperimentTrial)
        .filter(ExperimentTrial.user_id == user)
        .order_by(ExperimentTrial.started_at.desc(), ExperimentTrial.id.desc())
        .limit(MAX_LIST)
        .all()
    )
    return [store.trial_summary(t) for t in rows]


@router.get("/trials/{trial_id}")
def get_trial(trial_id: str, user: str = Depends(require_user), db: Session = Depends(get_db)):
    return store.trial_detail(db, _get_owned(db, trial_id, user))


@router.post("/trials/{trial_id}/reproduce")
def reproduce(trial_id: str, user: str = Depends(require_user), db: Session = Depends(get_db)):
    """Re-run the stored spec on the stored dataset version. Does not create or modify any trial."""
    trial = _get_owned(db, trial_id, user)
    try:
        return store.reproduce_trial(db, trial)
    except store.ReproduceError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error_code": exc.error_code, "message": exc.message, "trial_id": trial.id},
        )


@router.post("/trials/{trial_id}/variants", status_code=201)
def create_variant(trial_id: str, body: VariantRequest, user: str = Depends(require_user),
                   db: Session = Depends(get_db)):
    """New trial = parent's spec with `changes` merged over it (top-level keys replace), same dataset version."""
    parent = _get_owned(db, trial_id, user)
    if not parent.dataset_hash:
        return JSONResponse(status_code=409, content={
            "error_code": "dataset_missing", "trial_id": parent.id,
            "message": "The parent trial never resolved a dataset, so it cannot be forked.",
        })
    try:
        merged = store.merge_variant_spec(json.loads(parent.spec_json), body.changes)
        spec, spec_json, spec_hash = store.validate_spec(merged)
    except ValueError as exc:
        raise _unprocessable(str(exc))
    if spec_hash == parent.spec_hash:
        raise _unprocessable("changes do not alter the spec; a variant must differ from its parent")
    return _record(db, user, spec, spec_json, spec_hash, {"dataset_hash": parent.dataset_hash},
                   body.label, parent=parent.id, known_hash=parent.dataset_hash)
