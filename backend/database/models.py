from sqlalchemy import (
    Column,
    String,
    Date,
    Float,
    DateTime,
    Integer,
    Text,
    JSON,
    UniqueConstraint,
    func,
    Index,
    CheckConstraint
)

from .connection import Base   # Import Base from connection.py


# =====================================================
# FRED DATA (TIME SERIES)
# =====================================================

class FredData(Base):
    """
    FRED time-series data.
    One row = one observation.
    """
    __tablename__ = "fred_data"

    series_id = Column(String(50), primary_key=True, nullable=False)
    date = Column(Date, primary_key=True, nullable=False)

    series_type = Column(String(30), nullable=False)
    value = Column(Float, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    __table_args__ = (
        # Fast lookups for charts & latest values
        Index("idx_fred_series_date_desc", "series_id", "date"),

        # Optional sanity check (safe)
        CheckConstraint(
            "series_id <> ''",
            name="ck_fred_series_id_not_empty"
        ),
    )

    def __repr__(self):
        return (
            f"<FredData(series_id='{self.series_id}', "
            f"date='{self.date}', value={self.value})>"
        )

    def to_dict(self):
        return {
            "series_id": self.series_id,
            "series_type": self.series_type,
            "date": self.date.isoformat(),
            "value": self.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# =====================================================
# FRED SERIES METADATA
# =====================================================

class FredSeriesMetadata(Base):
    """
    Metadata describing a FRED series.
    One row per series_id.
    """
    __tablename__ = "fred_series_metadata"

    series_id = Column(String(50), primary_key=True, nullable=False)
    series_type = Column(String(30), nullable=False)

    title = Column(String(200), nullable=True)
    frequency = Column(String(20), nullable=True)
    units = Column(String(100), nullable=True)

    last_updated = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    __table_args__ = (
        Index("idx_fred_metadata_series_type", "series_type"),
    )

    def __repr__(self):
        return (
            f"<FredSeriesMetadata(series_id='{self.series_id}', "
            f"title='{self.title}')>"
        )

    def to_dict(self):
        return {
            "series_id": self.series_id,
            "series_type": self.series_type,
            "title": self.title,
            "frequency": self.frequency,
            "units": self.units,
            "last_updated": self.last_updated.isoformat(),
        }


# =====================================================
# SECTOR INTELLIGENCE
# =====================================================

class SectorNewsItem(Base):
    """
    Raw news items collected per sector.
    """
    __tablename__ = "sector_news_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector = Column(String(120), nullable=False)
    market = Column(String(10), nullable=False)

    title = Column(String(600), nullable=False)
    url = Column(String(1200), nullable=True)
    source = Column(String(200), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    snippet = Column(Text, nullable=True)

    hash = Column(String(64), nullable=False)

    ingested_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    __table_args__ = (
        Index("idx_sector_news_market_sector_date", "market", "sector", "published_at"),
        UniqueConstraint("market", "sector", "hash", name="uq_sector_news_hash"),
    )


class SectorSnapshot(Base):
    """
    LLM-generated sector snapshot based on recent news + signals.
    """
    __tablename__ = "sector_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector = Column(String(120), nullable=False)
    market = Column(String(10), nullable=False)

    as_of = Column(DateTime(timezone=True), nullable=False)
    news_item_ids = Column(JSON, nullable=True)

    sector_summary = Column(Text, nullable=True)
    momentum = Column(String(40), nullable=True)
    risk_notes = Column(Text, nullable=True)
    who_should_invest = Column(Text, nullable=True)
    suitable_profiles = Column(JSON, nullable=True)
    top_stocks = Column(JSON, nullable=True)

    score = Column(Float, nullable=True)
    llm_model = Column(String(80), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    __table_args__ = (
        Index("idx_sector_snapshot_market_sector_asof", "market", "sector", "as_of"),
    )


class SectorScore(Base):
    """
    Numeric sector score with suitability profile.
    """
    __tablename__ = "sector_score"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sector = Column(String(120), nullable=False)
    market = Column(String(10), nullable=False)

    as_of = Column(DateTime(timezone=True), nullable=False)
    score = Column(Float, nullable=True)
    suitable_profiles = Column(JSON, nullable=True)
    rationale = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    __table_args__ = (
        Index("idx_sector_score_market_sector_asof", "market", "sector", "as_of"),
    )


# =====================================================
# EXPERIMENT TRIALS (reproducible backtest runs)
# =====================================================

class ExperimentQuota(Base):
    """Durable allocated slots: recorded trials plus in-flight runs.

    Reservations survive a process crash conservatively; administrators can reconcile
    abandoned slots after confirming that no runs for that user remain active.
    """
    __tablename__ = "experiment_quotas"
    user_id = Column(String(128), primary_key=True)
    allocated = Column(Integer, nullable=False, default=0)


class DatasetVersion(Base):
    """
    Immutable, content-addressed snapshot of the OHLCV bars a trial ran on.
    The primary key hashes canonical rows and their provenance/interpretation metadata, so a
    trial can be reopened (and its ledger reproduced) offline.
    """
    __tablename__ = "dataset_versions"

    content_hash = Column(String(64), primary_key=True, nullable=False)

    source = Column(String(80), nullable=False)          # "synthetic:<name>" | "provider:yfinance"
    symbol = Column(String(40), nullable=True)
    interval = Column(String(10), nullable=False)
    timezone = Column(String(60), nullable=False)
    start = Column(String(32), nullable=True)            # first / last bar timestamp as stored
    end = Column(String(32), nullable=True)
    row_count = Column(Integer, nullable=False)
    missing_rows = Column(Integer, nullable=False, default=0)  # rows with NaN/None in OHLC
    adjustment = Column(String(40), nullable=False)
    rights_note = Column(String(200), nullable=False)
    rows_json = Column(Text, nullable=False)             # [[date, open, high, low, close, volume], ...]

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExperimentTrial(Base):
    """
    One recorded run of (spec, dataset version, engine version). Failed trials are kept and carry
    status="failed" + an error_code, so they never look like a zero-return completed run.
    Rows are never updated after insert.
    """
    __tablename__ = "experiment_trials"

    id = Column(String(32), primary_key=True, nullable=False)           # uuid4 hex
    user_id = Column(String(128), nullable=False)
    label = Column(String(200), nullable=True)
    parent_trial_id = Column(String(32), nullable=True)

    spec_json = Column(Text, nullable=False)                            # canonical normalised spec
    spec_hash = Column(String(64), nullable=False)
    dataset_hash = Column(String(64), nullable=True)                    # NULL if dataset resolution failed
    dataset_request_json = Column(Text, nullable=True)                  # what the client asked for
    engine_version = Column(String(20), nullable=False)
    environment_json = Column(Text, nullable=True)                      # python / pandas / numpy versions
    seed = Column(Integer, nullable=False)

    status = Column(String(12), nullable=False)                         # completed | failed
    error_code = Column(String(40), nullable=True)
    error_message = Column(String(300), nullable=True)                  # generic, client-safe

    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    result_json = Column(Text, nullable=True)                           # completed only
    headline_json = Column(Text, nullable=True)                         # list-view metrics
    ledger_hash = Column(String(64), nullable=True)
    result_hash = Column(String(64), nullable=True)                     # trades/equity/metrics/assumptions/ledger
    monte_carlo_hash = Column(String(64), nullable=True)

    __table_args__ = (
        Index("idx_experiment_trials_user_started", "user_id", "started_at"),
        Index("idx_experiment_trials_parent", "parent_trial_id"),
        CheckConstraint("status IN ('completed', 'failed')", name="ck_experiment_trials_status"),
    )
