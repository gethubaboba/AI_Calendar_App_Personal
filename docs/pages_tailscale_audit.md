# Pages + Funnel deployment audit — 2026-11-22

## Result

- Frontend: https://gethubaboba.github.io/AI_Calendar_App_Personal/
- API: https://adm1.tail8308a5.ts.net (Tailscale Funnel to `127.0.0.1:8010`)
- Repository: `gethubaboba/AI_Calendar_App_Personal`, public, Pages source: GitHub Actions.
- Pages workflow run `45038592718` completed successfully. The site and `/auth/` returned HTTP 200; a browser opened the sign-in page after the root redirect.

## Checks

- Next.js static export completed with all application routes. Generated assets use `/AI_Calendar_App_Personal/` and the Funnel API origin; no `localhost:8000` URL was found in the generated JavaScript.
- Backend regression suite: 16 tests passed in Docker, including the proxy route, CORS preflight, and request-size tests.
- Public API: unauthenticated `/api/events` returned 401 with `Access-Control-Allow-Origin: https://gethubaboba.github.io`; browser preflight returned 200. `/metrics` and `/docs` returned 404 through Funnel.
- Local model startup script completed its model and backend connectivity checks. Agent chat was not exercised with a signed-in test user.

## Operating limits

- Calendar, notes, analytics, and agent requests depend on the project computer, Docker stack, local model, and Funnel staying online. Pages itself remains available when they stop.
- The repository and registration page are public. Use demo accounts for public trials. Rotate the fixed development PostgreSQL credential and review registration abuse protection before sustained public use.
- The current live Funnel and local services are running on the project computer. See [startup and shutdown](pages_tailscale.md) for repeatable commands.
