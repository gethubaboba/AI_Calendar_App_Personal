# GitHub Pages + Tailscale Funnel

GitHub Pages serves the static Next.js frontend at `https://gethubaboba.github.io/AI_Calendar_App_Personal/`. Tailscale Funnel gives the API on the project computer a public HTTPS origin such as `https://my-pc.my-tailnet.ts.net`. The browser calls that API directly. The database and local model remain on the project computer; application features depend on that computer, Docker, the model, the proxy, and Funnel being online.

## One-time setup

1. [Install Tailscale for Windows](https://tailscale.com/docs/install/windows), sign in, and [enable Funnel](https://tailscale.com/docs/features/tailscale-funnel) for the device. Funnel requires MagicDNS, HTTPS certificates, and permission in the tailnet policy. On Windows run its CLI in an Administrator PowerShell. After starting the API and `tailscale funnel 8010` as shown below, record the HTTPS `*.ts.net` origin (without a trailing slash).
2. In `backend/.env`, add the Pages **origin** to the existing `CORS_ORIGINS` list: `https://gethubaboba.github.io`. Do not include `/AI_Calendar_App_Personal` in a CORS origin. Preserve any local or Android web origins you still use. Restart the backend after changing this file.
   Before enabling public access, replace any human-readable `SECRET_KEY` and fixed PostgreSQL credentials with strong values. Coordinate password changes across Compose, the backend connection string, and any existing database volume; changing the Compose variable alone does not change an already initialized PostgreSQL password. Rotating `SECRET_KEY` invalidates existing sessions.
3. In the GitHub repository `gethubaboba/AI_Calendar_App_Personal`, set **Settings → Secrets and variables → Actions → Variables → New repository variable**: `PAGES_API_URL=https://<your-device>.<your-tailnet>.ts.net`. This URL is public browser configuration, so a repository variable is appropriate. The Pages workflow rejects an unset, non-HTTPS, or non-`ts.net` value. If the Funnel hostname changes, update the variable and rerun the workflow.
4. Under **Settings → Pages → Build and deployment**, select **GitHub Actions** as the source. The account needs permission to change repository Pages settings. GitHub Free for organizations requires a public repository for Pages. Push the workflow and frontend changes to `main`, or start **Actions → Publish web app to GitHub Pages → Run workflow**. The workflow builds `frontend/out` with `PAGES_BUILD=1`, uploads it, and deploys it. Publishing does not copy `.env` files, the database, or the model into Pages.

## Run the API on the project computer

From the project root in PowerShell:

```powershell
# Start Docker Desktop first. This starts PostgreSQL, FastAPI, and the local model.
.\calendar-dev.ps1

# Start only the restricted public proxy beside the already running stack.
docker compose -f docker-compose.yml -f compose.agent.yml -f compose.public.yml up -d --no-deps --build public-api

# In an Administrator PowerShell window, publish only the proxy port.
tailscale funnel 8010
```

The proxy container listens only on host `127.0.0.1:8010` and forwards `/api/*` to FastAPI over the Compose network. It does not publish `/docs`, `/openapi.json`, `/metrics`, the database, Grafana, Prometheus, or the model through Funnel. Do not aim Funnel directly at port 8000. Keep Docker and Funnel running while visitors use the site. Tailscale may take a few minutes to publish the hostname in DNS.

If the full local model is not needed for a particular check, `docker compose -f docker-compose.yml -f compose.public.yml up -d --build postgres backend public-api` can start the core API. Calendar agent requests still require its configured model service. For a working agent demonstration, use `calendar-dev.ps1`.

## Verify

1. Open the Pages URL in a browser **outside the local network**. Register or sign in with a demo account; create and reload a calendar entry.
2. In browser developer tools, confirm API requests use the HTTPS Funnel origin and that preflight requests succeed. A request to `https://<Funnel-host>/api/auth/me` without a token should return `401`, showing that the route is reachable and protected.
3. Confirm `https://<Funnel-host>/metrics`, `/docs`, and `/openapi.json` return `404` from the proxy.
4. Confirm the agent screen only after the model is running. When the API computer is offline, static Pages screens still load but data and agent requests fail.

To end public access, stop `tailscale funnel` (Ctrl+C), then run `docker compose -f docker-compose.yml -f compose.agent.yml -f compose.public.yml stop public-api`. For a full local shutdown, run `.\calendar-dev.ps1 -Action stop -StopCompose`. Pages remains visible, but its live features will be unavailable.

## Notes

- The site is public, including its sign-in and registration forms. Use demo data and review account-registration exposure before broader use.
- GitHub Pages is a static host. Next.js redirects and rewrites requiring its server are unavailable in this deployment; Pages mode uses a static export. See [Next.js static export](https://nextjs.org/docs/app/guides/static-exports).
- Funnel is a public HTTPS service on a device in your tailnet. Its bandwidth is limited and the computer must remain online. See [Tailscale Funnel requirements](https://tailscale.com/docs/features/tailscale-funnel).
- [GitHub's Pages workflow guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) describes the required Actions permissions and artifact deployment.
