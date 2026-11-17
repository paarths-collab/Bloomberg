# Investing workspace

A local investing UI being simplified for people who want to invest without following the stock market every day.

## Current experience

The primary navigation contains Home, Practice portfolio, and Help. Existing market dashboards, charts, backtests, company comparisons, news, research and AI chat are grouped under Advanced tools.

The portfolio uses guest-authenticated simulated holdings. It does not place real orders or connect to a broker. Live data and AI features depend on configured providers; passing offline tests does not verify those providers.

Guided onboarding, goal planning and progress check-ins are planned, not implemented. The interface shows only real data: it has no placeholder account statistics, inert settings controls or invented status badges.

## Canonical API routes

- Investor profile and paper holdings: `/api/profile/*`.
- Company fundamentals: `/api/technical/fundamentals/summary/{symbol}`.
- Company comparisons: `/api/peers/*`.
- Research: `/api/research/*`.
- Macro series: `/api/fred/*`.
- Index constituents: `/api/sectors/treemap/index/{index_id}`.
- Market overview: `/api/markets/overview`.

Each resource is served from exactly one route. Alternative paths (nested profile, FRED and research mounts, technical peer aliases, a top-level fundamentals alias, a short sector alias, a macro overview, static chat/portfolio status routes and portfolio report routes) are not served and return 404.

See [frontend/README.md](frontend/README.md) for the current page map and frontend checks.

## Provider availability

Cached FRED reads work without a FRED key; live fetch/sync requires `FRED_API_KEY` and returns 503 when absent. Stale cached values are marked in the latest-cached response. US market overview falls back to Yahoo index history when FRED is unavailable. Missing index quotes remain unavailable; constituent prices never substitute for index prices.

Peer discovery can use the bundled sector universe when premium providers are unavailable. Responses identify these as sector comparables, not verified direct competitors. Sector refresh stores collected news and quote data without inventing model scores or recommendations when the AI provider is missing.

AI analysis failures return explicit errors. Sentiment heuristics are labelled and have no fabricated model confidence. EIA and the optional personalized-advice workflow still require their own configuration/integration. Provider outages and empty databases are distinct from code failures; successful HTTP responses with empty data do not prove a complete live feature.

## Running Locally and Tests

Backend (run from the repository root; the app is imported as `backend.main:app`):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt   # Windows: .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
./start.sh                                                    # or: .venv/bin/python run_server.py
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001  # backend only
```

Windows: `start.bat` (backend and frontend), `start_backend.bat` or `go.bat` (backend only). The backend listens on port 8001 by default; set `PORT` to change it. API docs are at `/docs`, health at `/health`.

Backend tests (offline; outbound HTTP is routed to a closed port):

```bash
DATABASE_URL=sqlite:///./ci_test.db AUTH_SECRET_KEY=<at-least-32-characters> \
HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 \
python -m pytest backend/tests -q -p no:cacheprovider
```

Frontend (in `frontend/`, Node 22 LTS):

```bash
npm ci
npm run dev      # development server on http://localhost:3000
npm test         # client identity/transport regressions
npm run build    # production build (downloads Google Fonts)
```

Environment variables a deploy needs (set in the hosting dashboard, not in the repo; the full list is in [Configuration](#configuration)):

- `DATABASE_URL`: persistent database connection string.
- `AUTH_SECRET_KEY`: signing key for guest tokens, at least 32 characters.
- `CORS_ORIGINS`: comma-separated frontend origins.
- `DB_FALLBACK_TO_SQLITE`: keep `false` in production.

Guest access tokens renew through `/api/auth/refresh` using a durable private `refresh_token`, preserving profiles, portfolios and trials. Legacy tokens issued before renewal support can migrate even after expiry. Current access-only credentials have a 30-day fallback after expiry if the durable refresh token was lost. Transient renewal errors (network, 5xx, 429) preserve the stored identity. A definitive 401/403 from `/api/auth/refresh` (for example after `AUTH_SECRET_KEY` changed) makes the web client discard the unusable credential and request one new guest identity, so users are not locked out; the old profile and portfolio are not recoverable. Keep `AUTH_SECRET_KEY` stable; changing it revokes access and recovery credentials. Renewals are rate limited separately from guest creation (`AUTH_REFRESH_RATE_LIMIT`, `AUTH_REFRESH_RATE_WINDOW_SECONDS`, `AUTH_REFRESH_GLOBAL_LIMIT`; see `DEPLOY_VERCEL_RENDER.md`).

Experiment snapshots hash the bars together with provenance and interval metadata; snapshots recorded with bars-only hashes remain readable. Trials record the backtest engine version (currently 2.2.0). Reproducing a trial recorded under an older engine version can report different results, because RSI reversal position holding, monetary profit factor and Monte Carlo drawdown (measured from starting capital) are computed differently in 2.2.0.

Backtest and research report routes validate their input and return 400 for bad types: `/api/backtest/run` de-duplicates `strategies` and accepts at most 5 distinct ones; `/api/backtest/heatmap` accepts at most 100 grid cells of finite numbers; `/api/backtest/report` supports `html` and `csv` only (CSV text cells are neutralised against spreadsheet formula injection). Generated report files live in `backend/backtest/reports` and `backend/research/reports`, are served only by plain filename with a restrictive Content-Security-Policy, and files older than 24 hours (or beyond the newest 200 per directory) are deleted whenever a new report is written.

Trial slots are reserved atomically in `experiment_quotas` before execution. Recorded failures consume slots; unexpected errors release them. A process crash conservatively retains an abandoned reservation. Reconcile allocated slots against recorded trials only after confirming that no runs for that user remain active.

Personalized recommendations return 503 until the optional wealth workflow is installed; multi-POV analysis remains a separate endpoint.

See DEPLOY_VERCEL_RENDER.md for deployment steps.

## Configuration

Every environment variable the application reads. Set them in the process environment or in `backend/.env` (loaded at startup; with `APP_ENV=<name>`, `backend/.env.<name>` is preferred when it exists). Never commit real values. "Required" means the service is unsafe or non-functional in production without it; every variable has a working development default or degrades gracefully when missing. Boolean flags are enabled only by the literal value `true` unless noted.

### Core (backend)

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `PORT` | Port used by `run_server.py` and `start.sh`. On Render use `$PORT` in the start command. | `8001` | No |
| `APP_ENV` | Selects `backend/.env.<APP_ENV>` instead of `backend/.env`. | unset | No |
| `CORS_ORIGINS` | Comma-separated frontend origins, merged with the localhost defaults. `*` is ignored. | localhost defaults | Yes (production) |
| `PEERS_PREMIUM` | Enables premium peer discovery in `/api/peers/*`; needs `FINNHUB_API_KEY` or `FMP_API_KEY`. Read at request time. | `false` | No |

### Database

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string. The default local SQLite file is ephemeral on most hosts. | `sqlite:///./boomerang.db` | Yes (production) |
| `DB_FALLBACK_TO_SQLITE` | If the configured database is unreachable, fall back to local SQLite. Keep `false` in production. | `false` | No |
| `SQLITE_FALLBACK_URL` | Database URL used when the fallback is enabled. | `sqlite:///./boomerang.db` | No |
| `DB_POOL_SIZE` | Connection pool size (non-SQLite databases only). | `5` | No |
| `DB_MAX_OVERFLOW` | Extra connections beyond the pool size (non-SQLite only). | `10` | No |
| `SQL_ECHO` | Log every SQL statement. | `false` | No |

### Authentication and rate limits

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `AUTH_SECRET_KEY` | Signs guest tokens; at least 32 random characters, identical on every instance. If unset, a per-process key is used and tokens stop working after a restart. | random per process | Yes (production) |
| `AUTH_TOKEN_TTL_HOURS` | Access-token lifetime in hours. | `720` | No |
| `AUTH_TRUST_PROXY` | Set to `1` to read the client IP from `X-Forwarded-For` (only behind a trusted proxy). | unset | No |
| `AUTH_TRUST_PROXY_HOPS` | Trusted proxies in front of the app; the client key is the Nth `X-Forwarded-For` entry from the right. | `1` | No |
| `AUTH_GUEST_RATE_LIMIT` | `POST /api/auth/guest` tokens per client per window; `0` disables. | `20` | No |
| `AUTH_GUEST_RATE_WINDOW_SECONDS` | Window length for the guest limiter. | `3600` | No |
| `AUTH_GUEST_GLOBAL_LIMIT` | Guest tokens across all clients per window; `0` disables. | `2000` | No |
| `AUTH_REFRESH_RATE_LIMIT` | `POST /api/auth/refresh` calls per client per window; `0` disables. | `120` | No |
| `AUTH_REFRESH_RATE_WINDOW_SECONDS` | Window length for the refresh limiter. | `3600` | No |
| `AUTH_REFRESH_GLOBAL_LIMIT` | Refresh calls across all clients per window; `0` disables. | `20000` | No |

### Abuse protection (heavy routes, request size, live socket)

One middleware throttles the unauthenticated heavy / LLM routes (`/api/backtest/(run|heatmap|report|quantstats-report|interpret|interpret-image)`, `/api/research/(analyze|report|interpret-image)`, `/api/chat/(super-agent|stock-advisor/*|sentiment/*)`, `/api/dashboard/(sentiment|crowd-insight)`, `POST /api/sectors/intel/refresh`, `POST /api/experiments/trials`). It uses the same proxy-aware client key as the auth limiters (`AUTH_TRUST_PROXY`, `AUTH_TRUST_PROXY_HOPS`). Values are read per request; state is in memory and per process.

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `MAX_REQUEST_BODY_BYTES` | Largest accepted request body (checked on Content-Length and on the streamed size); larger requests get 413. `0` disables. Also the largest `/ws/live` message. | `1000000` | No |
| `MAX_IMAGE_BODY_BYTES` | Body cap for paths ending in `/interpret-image`. `0` disables. | `6000000` | No |
| `HEAVY_RATE_LIMIT` | Heavy-route requests per client per window (one bucket across all heavy routes); over it: 429 + `Retry-After`. `0` disables. Also the per-client `/ws/live` message limit (separate bucket). | `30` | No |
| `HEAVY_RATE_WINDOW_SECONDS` | Window length for `HEAVY_RATE_LIMIT`. | `3600` | No |
| `HEAVY_MAX_CONCURRENCY` | Heavy requests running at once in this process; over it: 503 "busy" + `Retry-After`. `0` disables. | `4` | No |
| `WS_MAX_CONNECTIONS` | Concurrent `/ws/live` connections in this process; over it the socket gets an error message and close code 1013. `0` disables. | `20` | No |

### Market, news and macro data providers

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `FMP_API_KEY` | Financial Modeling Prep: peers and company data. | unset | No (recommended) |
| `FMP_BASE_URL` | Financial Modeling Prep API base URL for peer comparison. | `https://financialmodelingprep.com/api/v4` | No |
| `FINNHUB_API_KEY` | Finnhub: peers, insider activity, company news. | unset | No (recommended) |
| `FRED_API_KEY` | FRED live fetch/sync. Cached reads work without it; live fetch returns 503. | unset | No |
| `EIA_API_KEY` | EIA energy data. | unset | No |
| `TAVILY_API_KEY` | Tavily web search for news and research. | unset | No |
| `NEWSDATAIO_API_KEY` | NewsData.io headlines for the research agent. | unset | No |
| `RAPIDAPI_KEY` | RapidAPI-backed sentiment sources in the dashboard crowd-insight endpoint. | unset | No |
| `REDDIT_CLIENT_ID` | Reddit API client id for sentiment. | unset | No |
| `REDDIT_CLIENT_SECRET` | Reddit API client secret for sentiment. | unset | No |
| `REDDIT_USER_AGENT` | User agent sent to Reddit (default differs by module: unset in research, `stock-sentiment-bot` in sector sentiment). | see purpose | No |

### AI providers

AI features are optional; when a provider is missing the affected endpoint returns an explicit error or an unscored result.

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `GROQ_API_KEY` | Groq LLM calls (chat, research, backtest explanations, sector intel). | unset | No |
| `GROQ_MODEL` | Groq text model for the stock advisor and sector intel. | `llama-3.1-8b-instant` | No |
| `GROQ_VISION_MODEL` | Groq model for backtest chart-image analysis (a request may override it). | `meta-llama/llama-4-scout-17b-16e-instruct` | No |
| `GEMINI_API_KEY` | Google Gemini LLM calls. | unset | No |
| `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, ... | Additional Gemini keys rotated by the research LLM manager (numbered consecutively from 1). | unset | No |
| `GOOGLE_API_KEY` | Fallback for `GEMINI_API_KEY` in the chat agent setup. | unset | No |
| `GEMINI_MODEL` | Gemini model name. | `gemini-1.5-flash` (`gemini-2.0-flash` in the stock advisor) | No |
| `OPENAI_API_KEY` | OpenAI model option for the chat agent setup. | unset | No |
| `LLM_CACHE_ENABLED` | Cache LLM responses in the research LLM manager. | `true` | No |
| `LLM_CACHE_TTL` | LLM cache lifetime in seconds. | `300` | No |
| `LLM_CACHE_MAX` | Maximum cached LLM responses. | `128` | No |
| `WEALTH_TIMEOUT_SEC` | Timeout in seconds for the personalized-advice workflow. | `240` | No |

### Sector intelligence (optional tuning)

Used by the sector refresh job in `backend/sectors/intel_service.py`.

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `SECTOR_INTEL_MARKETS` | Markets refreshed. | `US,IN` | No |
| `SECTOR_INTEL_NEWS_LIMIT` | News items collected per sector. | `10` | No |
| `SECTOR_INTEL_STOCKS_LIMIT` | Constituent stocks considered per sector. | `12` | No |
| `SECTOR_INTEL_PRICE_PERIOD` | Price history period. | `3mo` | No |
| `SECTOR_INTEL_REFRESH_MINUTES` | Minutes a stored snapshot stays fresh before a non-forced refresh recomputes it. | `60` | No |
| `SECTOR_INTEL_SECTOR_GAP_SECONDS` | Pause between sectors during a refresh. | `60` | No |
| `SECTOR_INTEL_HTTP_TIMEOUT_SECONDS` | HTTP timeout for data collection. | `20` | No |
| `SECTOR_INTEL_LLM_ENABLED` | Use the LLM for sector summaries (accepts `1/true/yes/on`). | `true` | No |
| `SECTOR_INTEL_LLM_MODEL` | LLM model for sector summaries. | `GROQ_MODEL`, else `llama-3.1-8b-instant` | No |
| `SECTOR_INTEL_LLM_TIMEOUT_SECONDS` | LLM request timeout. | `30` | No |
| `SECTOR_INTEL_LLM_MIN_INTERVAL_SECONDS` | Minimum spacing between LLM calls. | `0` | No |
| `SECTOR_INTEL_LLM_MAX_RETRIES` | Retries for failed LLM calls. | `0` | No |
| `SECTOR_INTEL_LLM_MAX_COMPLETION_TOKENS` | Completion token cap. | `700` | No |
| `SECTOR_INTEL_LLM_DISABLE_ON_429_SECONDS` | Pause LLM use for this long after a rate-limit response (`0` = no pause). | `0` | No |
| `SECTOR_INTEL_LLM_429_RETRIES` | Retries after a rate-limit response. | `2` | No |
| `SECTOR_INTEL_LLM_429_BACKOFF_SECONDS` | Base back-off after a rate-limit response. | `6` | No |
| `SECTOR_INTEL_LLM_429_MAX_SLEEP_SECONDS` | Longest single back-off sleep. | `60` | No |
| `SECTOR_INTEL_LLM_429_COOLDOWN_SECONDS` | Pause length when a rate-limit response triggers a cooldown. | `60` | No |
| `SECTOR_INTEL_LLM_429_COOLDOWN_MAX` | Maximum number of rate-limit cooldowns taken per LLM call. | `1` | No |

### Frontend (Next.js)

| Name | Purpose | Default | Required |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_BACKEND_URL` | Backend origin. Used by the `/api/*` and `/ws/*` rewrites and by the browser to build WebSocket URLs (`http(s)` becomes `ws(s)`). Must be set on serverless hosts such as Vercel, which do not proxy WebSocket upgrades. | `http://127.0.0.1:8001` (rewrites); page origin (WebSockets) | Yes (production) |
| `BACKEND_URL` | Backend origin for the rewrites when `NEXT_PUBLIC_BACKEND_URL` is unset. | `http://127.0.0.1:8001` | Yes (production) |
| `NEXT_PUBLIC_API_BASE` | Absolute base URL for REST calls, bypassing the `/api` rewrite. | `/api` | No |

## Deployment

Production deployment instructions are available in DEPLOY_VERCEL_RENDER.md.
