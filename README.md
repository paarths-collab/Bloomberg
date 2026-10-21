# Bloomberg Agentic Investment Platform

From market chaos to investment clarity.

Bloomberg Agentic Investment Platform is built for modern investors who want conviction, not noise. It combines real-time market context, deep stock intelligence, strategy simulation, and AI-guided decision support in one experience.

## Why This Platform

Most investment workflows are fragmented. One app for charts, another for news, another for screening, another for portfolio checks.

This platform brings those decisions into a single loop:

1. Understand the market regime.
2. Evaluate a stock from multiple angles.
3. Test strategy behavior before acting.
4. Compare peers and sector context.
5. Validate impact on your portfolio.
6. Summarize the final call with AI.

## What You Get

### Market Awareness
Read the market faster with live index direction, macro indicators, and broad risk signals. Start each day with context before selecting names.

### Stock Conviction Engine
Analyze a stock through trend, momentum, valuation, sentiment, and risk layers so your decision is based on evidence, not a single chart or headline.

### Strategy Confidence Before Capital
Run backtests across multiple approaches to see how ideas might behave under real market conditions. Compare outcomes and reduce guesswork.

### Sector and Relative Strength View
Identify where money is flowing. Spot strong sectors early, then drill into leaders and laggards.

### Portfolio Clarity
Track holdings, allocation, and P&L in one place to avoid hidden concentration and keep risk aligned with your goals.

### AI-Guided Decision Support
Use natural language to ask questions, request summaries, and get structured viewpoints before you act.

## Page Guide: What Each Page Is For

### Home
Your launchpad. Understand the product quickly and jump into analysis, strategy, or AI workflow.

### Dashboard
Daily command center for investors. A quick read of market pulse, macro context, watchlist movement, and account-level signals.

### Markets
Big-picture page for cross-asset and macro awareness. Use this first when deciding whether market conditions support your idea.

### Technical
Chart-focused decision page for timing. Understand structure, momentum, and actionable levels before entering or exiting.

### Backtest
Your strategy lab. Simulate, compare, and review model behavior so you can choose approaches with higher confidence.

### Research
Deep-dive page for company intelligence and sentiment context. Converts scattered information into a coherent investment narrative.

### Sectors
Theme-first intelligence. Discover which sectors are strengthening or weakening and where opportunity is shifting.

### News
Live market headlines in a clean stream, designed for quick scanning of what can move price.

### Peers
Relative comparison page. Benchmark a company against similar businesses to find valuation and performance edges.

### Portfolio
Capital view. See your holdings, allocation mix, and performance contribution at a glance.

### Profile
Personal account and usage snapshot.

### Settings
Customize market defaults, display behavior, and experience preferences.

### Chat
Interactive AI workspace for analysis requests, strategy prompts, and decision summaries.

### Network, Ecosystem, Blog
Context and narrative pages for platform storytelling, exploration, and updates.

## Recommended Investor Workflow

1. Open Dashboard for market tone.
2. Check Markets for macro confirmation.
3. Validate setup on Technical or thesis on Research.
4. Pressure-test in Backtest.
5. Benchmark against competitors in Peers.
6. Confirm exposure in Portfolio.
7. Use Chat for final summary and action framing.

## Who This Is Built For

- Active investors seeking faster, clearer decisions
- Analysts who need multi-dimensional stock understanding
- Strategy-driven users who test before deployment
- Learners who want institutional-style thinking in an accessible format

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
npm run dev      # development server
npm run build    # production build
```

Environment variables a deploy needs (set in the hosting dashboard, not in the repo):

- `DATABASE_URL`: persistent database connection string.
- `AUTH_SECRET_KEY`: signing key for guest tokens, at least 32 characters.
- `CORS_ORIGINS`: comma-separated frontend origins.
- `DB_FALLBACK_TO_SQLITE`: keep `false` in production.

See DEPLOY_VERCEL_RENDER.md for the full list and deployment steps.

## Deployment

Production deployment instructions are available in DEPLOY_VERCEL_RENDER.md.
