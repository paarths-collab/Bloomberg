# Investing workspace UI

Next.js App Router, React, TypeScript and Tailwind CSS. This checkout is being simplified for people who want to start investing without following markets every day.

## Current pages

- `/`: simple entry point explaining the current practice experience.
- `/portfolio`: authenticated guest paper portfolio; missing valuations remain unavailable.
- `/help`: session behavior, simulation limits and available tools.
- Advanced tools: `/dashboard`, `/markets`, `/sectors`, `/technical`, `/backtest`, `/peers`, `/news`, `/research`, `/chat`. These retain their existing functionality and may need configured external providers.

Goal planning, guided onboarding, real brokerage execution and account recovery are not implemented. The UI does not advertise them as working features.

Removed: placeholder `/profile` and `/settings`, obsolete `/blog`, `/ecosystem` and `/network`, marketing fixture data, unsupported account/subscription claims, fake operational metrics, and the global screenshot analyzer.

## Development

```sh
npm ci
npm run dev
```

Frontend runs on port 3000. The default API proxy points to `http://127.0.0.1:8001`; override with `BACKEND_URL` when needed. Run the backend separately as documented in the root README.

```sh
npm test
npx tsc --noEmit
npm run lint
npm run build
```

`lib/navigation.ts` is the app navigation source. `lib/api-routes.json` records the shared API client's contract; backend contract tests verify registration, method, route resolution and authentication. Profile calls now use `/api/profile/*`; fundamentals use `/api/technical/fundamentals/summary/{symbol}`. Removed legacy aliases return 404.
