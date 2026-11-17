from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
import asyncio
import os
import json
import logging
import warnings
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from environment-specific file when APP_ENV is set.
app_env = os.getenv("APP_ENV", "").strip().lower()
env_dir = Path(__file__).parent
preferred_env_path = env_dir / f".env.{app_env}" if app_env else env_dir / ".env"
fallback_env_path = env_dir / ".env"

if preferred_env_path.exists():
    load_dotenv(dotenv_path=preferred_env_path)
elif fallback_env_path.exists():
    load_dotenv(dotenv_path=fallback_env_path)

# --- Isolated Page-specific Modules (Page Router Pattern) ---
from backend.sectors.main import router as sectors_app
from backend.markets.main import router as markets_app
from backend.technical.main import router as technical_app
from backend.chat.main import router as chat_app
from backend.portfolio.main import router as portfolio_app
from backend.backtest.main import router as backtest_app
from backend.experiments.routes import router as experiments_router

# --- New Isolated Modules ---
from backend.peers.main import router as peers_app
from backend.research.main import router as research_app
from backend.dashboard.main import router as dashboard_app
from backend.network.main import router as network_app
from backend.news.main import router as news_app
from backend.screener.main import router as screener_app
from backend.profile.main import router as profile_app
from backend.auth.routes import router as auth_app

# FRED routes registered at /api level so /api/fred/* matches frontend api.ts
from backend.markets.fred_routes import router as fred_router

from backend.chat.core.pipeline import InvestmentPipeline
from backend.common.abuse_protection import (
    AbuseProtectionMiddleware,
    ws_check_message,
    ws_disconnect,
    ws_max_message_bytes,
    ws_try_connect,
)
from backend.common.validation_errors import validation_exception_handler

# Suppress noise
warnings.filterwarnings("ignore", category=FutureWarning, module=r"yfinance\..*")
warnings.filterwarnings(
    "ignore",
    message=r".*Timestamp\.utcnow is deprecated.*",
    category=Warning,
    module=r"yfinance\..*",
)

app = FastAPI(title="Agentic Investment OS")
logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Global error at %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error"
        }
    )



# 422 without the echoed `input`: a NaN/Infinity sent into a wrongly typed field would otherwise make
# FastAPI's own error body unserialisable (500).
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# CORS Configuration
default_origins = [
    "http://localhost:5173", 
    "http://localhost:5174", 
    "http://localhost:5175",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]


def parse_cors_origins(raw, defaults=None):
    """Merge a comma-separated CORS_ORIGINS value with the default origins.

    Items are whitespace-trimmed; empty items are ignored. A literal "*" is
    ignored (with a warning) because credentialed CORS must use explicit origins.
    """
    origins = list(default_origins if defaults is None else defaults)
    for item in (raw or "").split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            logger.warning("Ignoring wildcard '*' in CORS_ORIGINS: credentials are enabled, list explicit origins instead.")
            continue
        if origin not in origins:
            origins.append(origin)
    return origins


cors_origins = parse_cors_origins(os.getenv("CORS_ORIGINS"))
# Added BEFORE CORS so CORS stays outermost and 413/429/503 rejections still carry CORS headers.
app.add_middleware(AbuseProtectionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Register Modular Apps ---
# Each module's router is registered with a unique prefix to prevent route collisions.
app.include_router(sectors_app,   prefix="/api/sectors",   tags=["Sectors"])
app.include_router(markets_app,   prefix="/api/markets",   tags=["Markets"])
app.include_router(technical_app, prefix="/api/technical", tags=["Technical"])
app.include_router(chat_app,      prefix="/api/chat",      tags=["Chat"])
app.include_router(portfolio_app, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(backtest_app,  prefix="/api/backtest",  tags=["Backtest"])
app.include_router(peers_app,     prefix="/api/peers",     tags=["Peers"])
app.include_router(research_app,  prefix="/api/research",  tags=["Research"])
app.include_router(dashboard_app, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(network_app,   prefix="/api/network",   tags=["Network"])
app.include_router(news_app,      prefix="/api/news",      tags=["News"])
app.include_router(screener_app,  prefix="/api/screener",  tags=["Screener"])
app.include_router(profile_app,   prefix="/api/profile",   tags=["Profile"])
app.include_router(auth_app)
app.include_router(experiments_router)  # carries its own /api/experiments prefix
# FRED at top-level /api so frontend /api/fred/* calls resolve correctly
app.include_router(fred_router,   prefix="/api",            tags=["FRED Data"])


# Database Initialization
from backend.database.connection import init_db, run_init_sql, get_database_status, redact_db_secrets
try:
    init_db()
    run_init_sql()
except Exception as e:
    # Keep starting so /health can report "degraded". The traceback is omitted on
    # purpose: driver errors can embed connection details.
    logger.error("Database init failed: %s: %s", type(e).__name__, redact_db_secrets(str(e)))

# Investment Pipeline
_pipeline = None
def _get_pipeline() -> InvestmentPipeline:
    global _pipeline
    if _pipeline is None: _pipeline = InvestmentPipeline()
    return _pipeline

@app.get("/health")
def health_check():
    db_status = get_database_status()
    return {
        "status": "ok" if db_status["database_connected"] else "degraded",
        "version": "2.2.0-modular",
        "database_connected": db_status["database_connected"],
        "database_fallback_active": db_status["database_fallback_active"],
    }


@app.get("/")
def root():
    return {"status": "ok", "service": "backend", "health": "/health"}

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if not ws_try_connect():
        await websocket.send_json({"status": "error", "message": "Too many live connections; try again later"})
        await websocket.close(code=1013)  # try again later
        return
    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > ws_max_message_bytes():
                await websocket.send_json({"status": "error", "message": "Message too large"})
                await websocket.close(code=1009)  # message too big
                return
            retry = ws_check_message(websocket)
            if retry is not None:
                await websocket.send_json({
                    "status": "error",
                    "message": "Too many requests. Please try again later.",
                    "retry_after": retry,
                })
                await websocket.close(code=1008)  # policy violation
                return
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"status": "error", "message": "Invalid JSON payload"})
                continue
            if not isinstance(msg, dict):
                await websocket.send_json({"status": "error", "message": "Invalid JSON payload"})
                continue

            pipeline = await asyncio.to_thread(_get_pipeline)
            result = await pipeline.run(
                query=msg.get("query"),
                ticker=msg.get("ticker"),
                market=msg.get("market", "us"),
            )
            if str(result.get("report", "")).lower().startswith("error"):
                await websocket.send_json({"status": "error", "message": "AI analysis unavailable; check provider configuration"})
            else:
                await websocket.send_json(result)
    except WebSocketDisconnect:
        logger.info("Live websocket disconnected")
    except Exception as e:
        logger.exception("Live websocket error: %s", e)
        try:
            await websocket.close()
        except Exception as close_error:
            logger.debug("Websocket close failed after error: %s", close_error)
    finally:
        ws_disconnect()
