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

Auth rate limiting (`POST /api/auth/guest` is unauthenticated, so it is throttled to stop anyone minting unlimited identities and bypassing per-user quotas; `POST /api/auth/refresh` has its own separate limiter so renewals never use guest-issuance quota). `render.yaml` sets all of these to non-secret values:

- `AUTH_GUEST_RATE_LIMIT`: tokens per client per window. Default `20`; `0` disables the per-client limit.
- `AUTH_GUEST_RATE_WINDOW_SECONDS`: window length. Default `3600`.
- `AUTH_GUEST_GLOBAL_LIMIT`: tokens across all clients per window. Default `2000`; `0` disables. Roughly 100 busy clients can exhaust it and block new guests. Existing token holders can still renew because `/api/auth/refresh` uses a separate limiter, but they cannot get a replacement guest identity while it is exhausted. Alert on 429 responses from both endpoints.
- `AUTH_REFRESH_RATE_LIMIT`: `/api/auth/refresh` calls per client per window, on a bucket separate from `/guest`. Default `120`; `0` disables the per-client limit. Every attempt counts, including ones rejected with 401, so spamming invalid tokens is not free.
- `AUTH_REFRESH_RATE_WINDOW_SECONDS`: window length for `/refresh`. Default `3600`.
- `AUTH_REFRESH_GLOBAL_LIMIT`: `/refresh` calls across all clients per window. Default `20000`; `0` disables.
- `AUTH_TRUST_PROXY`: set to `1` so the client IP is read from `X-Forwarded-For`. Behind Render's proxy the socket peer is the proxy for every user, so without this the whole site shares one 20-tokens-per-hour bucket. Leave it unset if the app is directly reachable by clients (they could forge the header).
- `AUTH_TRUST_PROXY_HOPS`: number of trusted proxies in front of the app; the client key is the Nth `X-Forwarded-For` entry counted from the right. Default `1`. `render.yaml` sets `2`, which assumes the browser -> Vercel (Next rewrite adds the client IP) -> Render proxy topology described here. **This value is unverified until the first deployment**: check what `X-Forwarded-For` actually contains for a request through Vercel, and use `1` if clients call Render directly. A value that is too high lets a client spoof its key; too low makes all users share one key.

Both limiters share the same proxy-aware client key (`AUTH_TRUST_PROXY`, `AUTH_TRUST_PROXY_HOPS`) and are read at request time. Each is in memory and per process: with several instances or workers each one counts separately and counters reset on restart. A multi-instance deployment needs a shared store or an edge limit.

Heavy-route abuse protection (the unauthenticated backtest, research, chat/LLM, sector-refresh and trial-creation routes cost real CPU or money). A single middleware applies, using the same proxy-aware client key as above:

- `MAX_REQUEST_BODY_BYTES` (default `1000000`) and `MAX_IMAGE_BODY_BYTES` (default `6000000`, for `/interpret-image` paths): larger bodies get 413, enforced on `Content-Length` and on streamed size. `0` disables.
- `HEAVY_RATE_LIMIT` (default `30`) per `HEAVY_RATE_WINDOW_SECONDS` (default `3600`) per client across all heavy routes: 429 with `Retry-After`. `0` disables. The same values cap `/ws/live` messages per client.
- `HEAVY_MAX_CONCURRENCY` (default `4`): heavy requests in flight per process; excess requests get 503 "busy, try again". `0` disables.
- `WS_MAX_CONNECTIONS` (default `20`): concurrent `/ws/live` connections per process (close code 1013 when full). `0` disables.

`render.yaml` lists them with the defaults. All are in memory and per process, like the auth limiters. The proxy settings above must be correct or every user shares one heavy-route bucket.

`/health` returns only `status`, `version`, `database_connected`, and `database_fallback_active`.

Guest credentials include a durable `refresh_token`. POST it to `/api/auth/refresh` to renew access for the same identity. Keep it private and retain a stable `AUTH_SECRET_KEY`; rotating that key revokes both access and recovery credentials. Pre-renewal legacy tokens can recover their identity even after expiry; current access-only tokens have a 30-day fallback after expiry if their durable refresh credential was lost.

If `/api/auth/refresh` answers 401 (for example `AUTH_SECRET_KEY` was rotated, unset or changed by a restart, so the saved credential no longer verifies), the web client treats it as permanent: it discards the saved credential and requests exactly one new guest identity, which starts with an empty profile and portfolio. Network errors, 5xx and 429 responses are treated as transient: the saved credential is kept, nothing new is issued, and the error is shown so the user can retry.

Paper-portfolio routes require `Authorization: Bearer <token>`. Obtain the token from `POST /api/auth/guest`.

## 2) Deploy Frontend on Vercel

1. In Vercel: Add New -> Project.
2. Import the same repo.
3. Set **Root Directory** to `frontend`.
4. Build settings:
   - Framework: Next.js
   - Build Command: `npm run build`
   - Output: default
5. Add environment variables in Vercel project:
   - `BACKEND_URL=https://<your-render-domain>`
   - `NEXT_PUBLIC_BACKEND_URL=https://<your-render-domain>` (REST goes through the `/api/*` rewrite; the browser derives the WebSocket URL, e.g. `wss://<your-render-domain>/ws/live`, from this same variable because Vercel rewrites do not proxy WebSocket upgrades)
6. Deploy.

## 3) Validate

1. Open frontend Vercel URL.
2. Check API proxy path:
   - `https://<your-vercel-domain>/api/peers/compare/AAPL?limit=5`
3. Check backend directly:
   - `https://<your-render-domain>/health`
4. Test WebSocket-dependent features in UI.

## Notes

- Frontend uses Next rewrites in `frontend/next.config.js` to proxy `/api/*` and `/ws/*` to backend.
- If you change the backend domain, update `BACKEND_URL` and `NEXT_PUBLIC_BACKEND_URL` in Vercel and redeploy.
- Render free/starter plans may cold start after inactivity.
