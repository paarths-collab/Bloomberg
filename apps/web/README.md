# Bloomberg Terminal V2

A clean frontend migration target for the existing Bloomberg repository.

## Stack

- Next.js 16 + React 19
- TanStack Query for server state
- react-resizable-panels for terminal workspaces
- TradingView Lightweight Charts for market visualization
- Lucide icons
- CSS design tokens

## Run

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev
```

The app connects to the existing FastAPI backend through `NEXT_PUBLIC_API_URL`. The first slice uses `/api/markets/overview` and clearly marks fallback data as DEMO when the backend is unavailable.

## Migration order

1. Replace the legacy dashboard shell.
2. Port Markets + Technical using shared query keys and typed adapters.
3. Port Research + AI surfaces.
4. Port Portfolio + Backtest.
5. Delete the legacy `frontend/` only after route parity and build verification.
