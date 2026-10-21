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
