# Bloomberg modernization plan

## Audit summary

The repository carries multiple generations of the product at once. The highest-risk issues are structural, not visual:

- `frontend/` imports `@/lib/api` and `@/lib/data`, but `frontend/lib/` is not tracked.
- Root `.gitignore` contains a broad `lib/` rule, which can hide application source directories.
- UI responsibilities are concentrated in large client components and global CSS.
- `backend/main.py` still owns configuration, middleware, compatibility routes, database initialization, WebSocket orchestration, and router registration.
- Frontend data fetching is page-local and inconsistent.

## Target architecture

```text
apps/
  web/                 # Next.js terminal UI
    app/
    components/
    lib/
  api/                 # future FastAPI package boundary
packages/
  contracts/           # generated/hand-authored API types
  ui/                  # optional shared primitives
```

The existing `backend/` stays online while routes are migrated. Do not rewrite the data layer and UI simultaneously.

## UI direction

- charcoal/near-black canvas
- compact icon rail and command/search bar
- resizable information panes
- thin borders, restrained radii, dense typography, strong numeric hierarchy
- market workspace in the center, watchlist/context left, AI activity right
- one accent color for state/focus rather than decoration
- responsive stacked fallback

## Backend refactor sequence

1. Create a versioned `/api/v1` router and preserve compatibility aliases temporarily. Add Pydantic response models for market overview, candles, portfolio summary, research, and agent events.
2. Move environment parsing, CORS, logging, database lifecycle, and exception handlers out of `backend/main.py` into `core/`.
3. Keep routers thin: validate input and call services. Provider-specific code stays in services/adapters.
4. Normalize errors to a single typed envelope with `code`, `message`, and `retryable` fields.
5. Add response-schema/contract tests and generate frontend types from OpenAPI after shapes stabilize.

## Delivery phases

- **Phase 1:** V2 shell + market overview adapter + repo hygiene.
- **Phase 2:** Markets/Technical migration, real candle data, command palette.
- **Phase 3:** Research/Agents workspace with streaming and durable sessions.
- **Phase 4:** Portfolio/Backtest, auth, observability, deployment hardening.
- **Phase 5:** remove legacy frontend and compatibility endpoints after parity.

This first PR deliberately does not delete the legacy frontend or rewrite working backend services; it creates a safe migration target.
