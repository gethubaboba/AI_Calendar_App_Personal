# Local metrics and monitoring

The FastAPI backend exposes Prometheus metrics at `GET /metrics`. Docker Compose adds Prometheus for scraping and retention, a PostgreSQL exporter, and Grafana with a provisioned overview dashboard.

- `http_requests_total{method,route,status}` counts completed HTTP requests.
- `http_request_duration_seconds{method,route}` is a histogram of request latency.

The `/metrics` scrape itself is excluded. `route` uses the framework route template (for example `/api/events/{event_id}`), never the raw path. Query strings, user IDs, credentials, tokens, and request bodies are not metric labels or metric values. Unknown methods are grouped as `OTHER`.

## Start the stack

Set the Grafana admin password in a root `.env` file. From PowerShell at the repository root:

```powershell
Copy-Item monitoring/.env.example .env
# Edit .env and replace the placeholder password with a unique password.
Copy-Item backend/.env.example backend/.env  # if not already configured
docker compose up -d --build
```

Open [Grafana](http://localhost:3001) with username `admin` and the password from `.env`. The **Smart Calendar Overview** dashboard is provisioned automatically. Prometheus is available at [localhost:9090](http://localhost:9090). Both monitoring UIs bind to loopback and are not exposed to other devices on the LAN. Prometheus scrapes the backend and PostgreSQL exporter over the private Compose network every 15 seconds. Data is retained in named Docker volumes; `docker compose down -v` deletes it.

The dashboard shows API request rate by route, p95 latency, HTTP 5xx rate, API scrape status, PostgreSQL scrape status, and active database connections. `up` indicates whether Prometheus can scrape a target; `pg_up` indicates whether the exporter can connect to PostgreSQL.

The backend `/metrics` route is reachable on the same host/port as the API. It contains aggregate operational data only, but should still be restricted before any non-local deployment. The Grafana and Prometheus ports are deliberately bound to `127.0.0.1`.

To run the instrumentation tests from the `backend` directory:

```sh
python -m unittest test_metrics -v
```

These tests use FastAPI's in-process test client and do not require PostgreSQL. To stop monitoring services without deleting their data, run `docker compose stop prometheus grafana postgres-exporter`; to stop all services, run `docker compose down`.
