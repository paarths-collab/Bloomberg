# Deploy: Vercel (Frontend) + Render (Backend)

## 1) Deploy Backend on Render

1. Push this repo to GitHub.
2. In Render: New + -> Blueprint.
3. Select your repo. Render will detect `render.yaml`.
4. Create service.
5. In Render service -> Environment, set:
   - `CORS_ORIGINS=https://<your-vercel-domain>`
   - `FMP_API_KEY=...` (optional but recommended)
   - `FINNHUB_API_KEY=...` (optional but recommended)
   - Any other API keys you use.
6. Wait for deploy to finish and copy backend URL, e.g. `https://bloomberg-backend.onrender.com`.

Health URL:
- `https://<your-render-domain>/health`

### Backend environment

Set these in Render -> Environment (`render.yaml` declares the keys; secret values are entered in the dashboard only):

- `DATABASE_URL`: database connection string. Defaults to a local SQLite file, which is ephemeral on Render. Set this to a persistent database.
- `DB_FALLBACK_TO_SQLITE`: defaults to `false`. When `true`, a failing configured database silently switches to local SQLite. Not recommended in production.
- `CORS_ORIGINS`: comma-separated list of frontend origins, merged with the localhost defaults. Wildcard `*` is ignored.
- `AUTH_SECRET_KEY`: signs guest bearer tokens. Use a random value of at least 32 characters, and keep it the same across all instances. If unset, a per-process key is used and tokens stop working after a restart.
- `AUTH_TOKEN_TTL_HOURS`: optional token lifetime in hours. Defaults to `720`.

Guest-token rate limiting (`POST /api/auth/guest` is unauthenticated, so it is throttled to stop anyone minting unlimited identities and bypassing per-user quotas). `render.yaml` sets all of these to non-secret values:

- `AUTH_GUEST_RATE_LIMIT`: tokens per client per window. Default `20`; `0` disables the per-client limit.
- `AUTH_GUEST_RATE_WINDOW_SECONDS`: window length. Default `3600`.
- `AUTH_GUEST_GLOBAL_LIMIT`: tokens across all clients per window. Default `2000`; `0` disables. Roughly 100 busy clients can exhaust it and block new guests (existing token holders are unaffected), so alert on 429 responses from this endpoint.
- `AUTH_TRUST_PROXY`: set to `1` so the client IP is read from `X-Forwarded-For`. Behind Render's proxy the socket peer is the proxy for every user, so without this the whole site shares one 20-tokens-per-hour bucket. Leave it unset if the app is directly reachable by clients (they could forge the header).
- `AUTH_TRUST_PROXY_HOPS`: number of trusted proxies in front of the app; the client key is the Nth `X-Forwarded-For` entry counted from the right. Default `1`. `render.yaml` sets `2`, which assumes the browser -> Vercel (Next rewrite adds the client IP) -> Render proxy topology described here. **This value is unverified until the first deployment**: check what `X-Forwarded-For` actually contains for a request through Vercel, and use `1` if clients call Render directly. A value that is too high lets a client spoof its key; too low makes all users share one key.

The limiter is in memory and per process: with several instances or workers each one counts separately and counters reset on restart. A multi-instance deployment needs a shared store or an edge limit.

`/health` returns only `status`, `version`, `database_connected`, and `database_fallback_active`.

Paper-portfolio routes require `Authorization: Bearer <token>`. Obtain the token from `POST /api/auth/guest`.

## 2) Deploy Frontend on Vercel

1. In Vercel: Add New -> Project.
2. Import the same repo.
3. Set **Root Directory** to `ethena`.
4. Build settings:
   - Framework: Next.js
   - Build Command: `npm run build`
   - Output: default
5. Add environment variables in Vercel project:
   - `BACKEND_URL=https://<your-render-domain>`
   - `NEXT_PUBLIC_BACKEND_URL=https://<your-render-domain>`
   - `NEXT_PUBLIC_WS_URL=wss://<your-render-domain-without-https>/ws/live`
6. Deploy.

## 3) Validate

1. Open frontend Vercel URL.
2. Check API proxy path:
   - `https://<your-vercel-domain>/api/peers/compare/AAPL?limit=5`
3. Check backend directly:
   - `https://<your-render-domain>/health`
4. Test WebSocket-dependent features in UI.

## Notes

- Frontend uses Next rewrites in `ethena/next.config.js` to proxy `/api/*` and `/ws/*` to backend.
- If you change backend domain, update the 3 Vercel env vars and redeploy.
- Render free/starter plans may cold start after inactivity.
