# Apache Superset — Production Deployment Guide (OTM BI)

**Target:** a clean Ubuntu Server (22.04 LTS or 24.04 LTS), Docker Compose, no Kubernetes.
**Public URL:** `https://otm-bi.otmretail.ai/`  **Internal URL:** `https://otm-bi.otm.internal/`
**Prepared for:** Kapa-Oil / OTM Retail

Every command below is tagged with **where** to run it:

- **[HOST]** — the Ubuntu server shell (your SSH session)
- **[SUPERSET]** — inside the `superset` container (`docker compose exec superset …`)
- **[DB]** — inside the PostgreSQL container / `psql`
- **[REDIS]** — inside the Redis container / `redis-cli`

---

## 0. Version decision and assumptions

Superset now ships as a **6.x** series (6.1.0 is current at the time of writing;
the changelog runs through 6.1.0). This stack **pins an exact tag** via
`SUPERSET_VERSION` in `.env` (default `6.1.0`) and builds a small custom image
on top of it. **Never deploy `latest` / `latest-dev`** — those float and will
eventually pull a breaking change under you.

Choose your pin deliberately:

| Choice | When to use it |
|---|---|
| **6.1.0** (default here) | You want the current feature set (Playwright reporting, granular export controls, AES-GCM secrets). Verify the newest 6.x **patch** on Docker Hub before you build. |
| **5.0.x** | More conservative — a series that has been in the field longer. Same architecture; a few config keys differ (noted in §22). |

**This guide flags every place 6.x differs from 4.x/5.x** (see §22 for the
consolidated list). Do not copy option names from old blog posts — several were
renamed or removed.

**Baseline hardware assumption** (used for all the numeric tuning below):

> **8 vCPU · 16 GB RAM · 100+ GB SSD**, Ubuntu LTS.

Everything that depends on that baseline is marked **⚙ TUNE** with the exact
value to change once you know the real spec. If your server is smaller (e.g.
4 vCPU / 8 GB) or larger, jump to §17 first — it tells you exactly which numbers
to move and how.

**Other assumptions you must fill in:** a working SMTP relay for Alerts &
Reports (§11), public DNS already pointing at the server (§15), and an internal
DNS entry or `/etc/hosts` for the internal hostname (§15).

---

## 1. Architecture — every container and why it exists

Ten services, one private Docker network. **Only nginx is exposed to the network
(80/443).** Everything else is reachable only by service name on `superset_net`.

```
                       Internet                    Internal LAN
                          │                             │
                    :443 / :80                        :443
                          ▼                             ▼
                 ┌───────────────────────────────────────────┐
                 │                  nginx                     │  ← only public entry
                 │  TLS term · HTTP→HTTPS · headers · /ws/    │
                 └───────┬───────────────────────┬───────────┘
                         │ HTTP                   │ WS upgrade
                         ▼                        ▼
                 ┌──────────────┐        ┌──────────────────┐
                 │  superset    │        │ superset-websocket│
                 │  (Gunicorn)  │        │  (Node, :8080)    │
                 └──┬────────┬──┘        └─────────┬─────────┘
                    │        │                     │
        ┌───────────┘        └─────────┐           │ reads async
        ▼                              ▼           ▼ result stream
 ┌────────────┐   ┌────────────┐  ┌────────────────────────────┐
 │ PostgreSQL │   │   Redis    │◄─┤ superset-worker (Celery)   │
 │ (metadata) │   │ broker +   │  │ async SQL · reports ·      │
 └────────────┘   │ cache +    │  │ thumbnails (Chromium)      │
                  │ results +  │  └────────────────────────────┘
                  │ streams    │  ┌────────────────────────────┐
                  └────────────┘◄─┤ superset-worker-beat (x1)  │  scheduler
                                  └────────────────────────────┘
                  superset-init (one-shot: migrations, admin, roles)
                  superset-flower (Celery monitoring, loopback only)
                  certbot (TLS issuance/renewal)
```

| Service | Purpose |
|---|---|
| **nginx** | The only Internet-facing container. Terminates TLS for the public domain, redirects HTTP→HTTPS, adds security headers, reverse-proxies to Superset, and upgrades `/ws/` to the websocket service. Serves the internal HTTPS vhost. |
| **superset** | The Superset web application, served by **Gunicorn** (never the Flask dev server). Handles the UI and REST API. |
| **superset-init** | **One-shot** bootstrap: runs DB migrations, creates the admin user, initialises roles/permissions, optional examples. Every other Superset service waits for it to finish successfully. |
| **superset-worker** | Celery worker. Executes **async SQL Lab** queries, **Alerts & Reports**, **thumbnail/screenshot** rendering (needs the Chromium baked into the image), and cache warm-up. Scale horizontally. |
| **superset-worker-beat** | Celery **beat** scheduler — emits the periodic triggers (report scheduler, log pruning, cache warm-up). **Exactly one instance**, or schedules double-fire. |
| **superset-websocket** | Node service for the async-query **WebSocket** transport. Reads completed-query events from a Redis stream and pushes them to the browser, authenticated by a short-lived JWT signed by Superset. |
| **superset-flower** | Celery monitoring UI (task throughput, failures, worker liveness). Bound to loopback only; reach via SSH tunnel. Optional but recommended in production. |
| **db (PostgreSQL)** | Superset's **metadata** database — dashboards, charts, users, roles, saved queries, and the (encrypted) definitions of the BI sources you connect. **This is not a BI/reporting database.** |
| **redis** | Multi-duty: Celery broker + result backend, general cache, chart **data cache**, filter/explore state, SQL Lab async results, and the global-async-query stream. |
| **certbot** | Issues and auto-renews the Let's Encrypt certificate for the public domain. |

**Why the full stack, not a single container:** async queries, alerts, reports,
thumbnails and cache warm-up all run as **Celery tasks** — they need a broker
(Redis), workers, and a scheduler (beat). WebSockets need a dedicated Node
service. Metadata needs a real database (Postgres), not the bundled SQLite.
Splitting these lets you scale, restart, and monitor each concern independently.

---

## 2. Host-level setup (§ Host configuration)

### 2.1 Base packages and updates — **[HOST]**

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl gnupg git ufw htop
sudo timedatectl set-timezone Africa/Nairobi   # or UTC if you prefer
```

### 2.2 Install Docker Engine + Compose plugin — **[HOST]**

Use Docker's official repository (the Ubuntu `docker.io` package lags and lacks
the modern `docker compose` plugin):

```bash
# Add Docker's GPG key and repo
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt -y install docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# Verify
docker --version           # Docker Engine 27+
docker compose version     # Compose v2 (note: "docker compose", not "docker-compose")
```

Run Docker as your user (optional but convenient) — **[HOST]**:

```bash
sudo usermod -aG docker "$USER"
# log out/in (or: newgrp docker) for it to take effect
```

Set container-friendly kernel limits for Redis/Postgres — **[HOST]**:

```bash
echo 'vm.overcommit_memory = 1' | sudo tee /etc/sysctl.d/99-superset.conf
echo 'net.core.somaxconn = 1024' | sudo tee -a /etc/sysctl.d/99-superset.conf
sudo sysctl --system
```

### 2.3 Get the project onto the server — **[HOST]**

Place this `superset-prod/` directory at e.g. `/opt/otm-superset`:

```bash
sudo mkdir -p /opt/otm-superset
sudo chown "$USER":"$USER" /opt/otm-superset
# copy the contents of this bundle into /opt/otm-superset, then:
cd /opt/otm-superset
```

---

## 3. Directory structure

```
superset-prod/
├── docker-compose.yml          # all services, networks, volumes
├── .env.example → .env         # every secret + tunable (chmod 600, never commit)
├── README.md / DEPLOYMENT_GUIDE.md
├── docker/
│   ├── Dockerfile              # apache/superset + Playwright/Chromium + drivers
│   ├── superset_config.py      # the production config (reads env)
│   └── superset-init.sh        # migrations, admin, roles, examples
├── websocket/
│   ├── Dockerfile              # builds superset-websocket from the pinned tag
│   ├── config.json.template    # rendered from env at runtime
│   └── entrypoint.sh
├── nginx/
│   ├── nginx.conf              # http{} core, upstreams, ws upgrade map
│   ├── conf.d/                 # 00-default, public vhost, internal vhost
│   ├── snippets/               # proxy-common, ws-proxy, ssl-params
│   └── certs/internal/         # internal TLS cert/key (generated)
├── postgres/
│   ├── postgresql.conf         # annotated tuning reference
│   └── initdb/                 # optional first-boot SQL
├── redis/redis.conf            # broker + cache + persistence policy
├── scripts/                    # generate-secrets, init-letsencrypt,
│   │                           # gen-internal-cert, backup/restore, healthcheck
├── certbot/{conf,www}/         # Let's Encrypt state + ACME webroot
├── backups/                    # pg_dump archives + config tarballs
└── logs/                       # nginx + certbot logs (app logs go to docker)
```

This is the structure you asked for, adjusted for production: `websocket/` and
`certbot/` are added because the full stack needs them, and `docker/` holds the
image build + config + init in one place.

---

## 4. Configure secrets (`.env`) (§ Secure environment variables)

### 4.1 Create and fill `.env` — **[HOST]**

```bash
cp .env.example .env
./scripts/generate-secrets.sh          # prints strong random secrets
nano .env                              # paste secrets; set hostnames + SMTP
chmod 600 .env                         # readable only by you
```

What you **must** change before first boot:

- `SUPERSET_SECRET_KEY` — 42+ random bytes. Superset refuses to start if it's the
  placeholder. **Pin it once and never let a rebuild regenerate it.** It signs two
  things that break if it changes: (1) encrypted DB-connection passwords in the
  metadata DB become unreadable; (2) every issued JWT — including the service-account
  `access_token` an embedding backend caches — fails signature verification
  (`422 Signature verification failed`), and embedded dashboards stop minting guest
  tokens until every client re-logs-in (see §11c.3, §21a gate ladder). If you must
  change it, run `superset re-encrypt-secrets` **and** restart every token-caching
  client in the same window — never just edit the value.
- `GLOBAL_ASYNC_QUERIES_JWT_SECRET` — ≥32 bytes; shared with the websocket
  service. **6.x will not start with the default value.**
- `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `ADMIN_PASSWORD`, `FLOWER_BASIC_AUTH`.
- Hostnames (`SUPERSET_PUBLIC_HOST`, `SUPERSET_INTERNAL_HOST`), `CERTBOT_EMAIL`.
- `SMTP_*` for Alerts & Reports email delivery.

### 4.2 Generating a SECRET_KEY manually — **[HOST]**

```bash
openssl rand -base64 42
```

---

## 5. Initialization — from clean Ubuntu to first login

This is the exact ordered sequence. Steps 1–2 (§2.2) install Docker.

**3. Build the images — [HOST]**
```bash
docker compose build          # builds the custom superset image (Chromium) and
                              # the websocket image (from the pinned tag)
```

**4. Bring up the data tier first and confirm it's healthy — [HOST]**
```bash
docker compose up -d db redis
docker compose ps             # wait until db and redis show (healthy)
```

**5. Public TLS cert (DNS must already resolve to this server) — [HOST]**
```bash
./scripts/init-letsencrypt.sh          # add 'staging' as an arg to dry-run first
```

**6. Internal TLS cert — [HOST]**
```bash
./scripts/gen-internal-cert.sh         # or install your internal-CA cert instead
```

**7–9. Migrations, admin user, roles — [HOST]**
These run automatically via the `superset-init` one-shot container, but you can
run them explicitly:
```bash
docker compose run --rm superset-init  # db upgrade + create-admin + init
```

**10. Examples — only if this is a demo — [HOST]**
```bash
# set SUPERSET_LOAD_EXAMPLES=yes in .env BEFORE init to load sample dashboards.
# Leave it 'no' for production.
```

**11. Start all services — [HOST]**
```bash
docker compose up -d
```

**12. Verify health — [HOST]**
```bash
docker compose ps                      # every service (healthy)
./scripts/healthcheck.sh               # app /health, redis ping, pg ready, celery
```

**13. First login** — open `https://otm-bi.otmretail.ai/`, sign in with
`ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`. Immediately change the password
in the UI and create per-person accounts.

**14. Test the public URL — [HOST or your laptop]**
```bash
curl -I https://otm-bi.otmretail.ai/            # expect 200/302 + HSTS header
curl -I http://otm-bi.otmretail.ai/             # expect 301 → https
```

**15. Test the internal URL — [internal client]**
```bash
curl -kI https://otm-bi.otm.internal/           # -k until the internal CA is trusted
```

The whole sequence is reproducible from a clean Ubuntu install: §2.2 → §4 → the
15 steps above.

---

## 6. Superset configuration explained (§ Superset configuration)

The full file is `docker/superset_config.py`. It reads everything from
environment variables so no secret is hard-coded. Key sections:

- **SECRET_KEY** — guarded: the app raises if it's unset/placeholder.
- **SQLALCHEMY_DATABASE_URI** — built from `POSTGRES_*`; points only at the
  metadata DB. **SQLALCHEMY_ENGINE_OPTIONS** sets the connection pool
  (`pool_size`, `max_overflow`, `pool_recycle`, `pool_pre_ping=True`). `pre_ping`
  silently drops dead connections; `pool_recycle=1800` reconnects before Postgres
  would time them out.
- **CACHE_CONFIG / DATA_CACHE_CONFIG / FILTER_STATE_CACHE_CONFIG /
  EXPLORE_FORM_DATA_CACHE_CONFIG / THUMBNAIL_CACHE_CONFIG** — all Redis-backed
  (`RedisCache`), each on its own logical DB so they don't collide.
  `DATA_CACHE_CONFIG` is the one that makes dashboards fast on reload.
- **RESULTS_BACKEND** — SQL Lab async results in **Redis**, not the filesystem.
  The stock reference config uses a filesystem path; that breaks in a
  multi-container setup because workers and the web tier wouldn't share it.
- **CELERY_CONFIG** — broker + result backend on Redis, task imports, dedicated
  queues, `worker_prefetch_multiplier=1` (fair scheduling for long queries),
  `task_acks_late=True` (a task re-runs if a worker dies mid-flight), and the
  **beat schedule** (report scheduler every minute, nightly log prune).
- **GLOBAL_ASYNC_QUERIES** — feature flag on, `transport="ws"`,
  `GLOBAL_ASYNC_QUERIES_CACHE_BACKEND` (6.x name) on its own Redis DB, the JWT
  secret, secure cookie settings, and the public `wss://…/ws/` URL the browser
  connects to.
- **ENABLE_PROXY_FIX + PROXY_FIX_CONFIG + PREFERRED_URL_SCHEME="https"** — makes
  Superset trust nginx's `X-Forwarded-*` headers and emit **https** absolute
  URLs (report links, redirects) instead of http.
- **Session cookies** — `SECURE`, `HTTPONLY`, `SAMESITE="Lax"`.
- **CSRF** — enabled, no blanket exemptions, token tied to the session.
- **Talisman** — HSTS + CSP + frame options. `force_https=False` because nginx
  already does the redirect (leaving it on causes redirect loops behind a proxy).
  The CSP's `connect-src` explicitly allows `wss://otm-bi.otmretail.ai` — without
  that, the browser blocks the async-query WebSocket.
- **CORS** — off by default; a commented, scoped example is provided. Never `*`.
- **Alerts & Reports** — `WEBDRIVER_BASEURL` (internal address the headless
  browser hits) vs `WEBDRIVER_BASEURL_USER_FRIENDLY` (public link in the email),
  SMTP settings, executors.

---

## 7. PostgreSQL (§ Database configuration) — **[DB]**

**Version:** pinned to `postgres:16` (stable, widely deployed; 15 and 17 also
work — the Superset reference uses 17). **Pin a major version and never let it
auto-upgrade majors** — a major upgrade needs `pg_upgrade` or dump/restore, not
just a new image tag.

**This is the metadata DB only.** Your BI/reporting sources (SAP HANA, MSSQL,
other Postgres, etc.) are added later from **Settings → Database Connections** in
the UI and never touch this container. Keep that separation absolutely clear —
mixing reporting load into the metadata DB is a classic mistake.

**Tuning** is applied via `-c` flags in `docker-compose.yml` (annotated
reference in `postgres/postgresql.conf`), sized for a container capped near 3 GB:

- `max_connections=120` — ⚙ TUNE. Each Gunicorn/Celery process keeps a small
  pool; 120 covers the baseline. Prefer pooling over raising this; if you truly
  outgrow it, add **PgBouncer** rather than pushing connections into the hundreds.
- `shared_buffers=768MB` (~25% of container RAM), `effective_cache_size=2GB`
  (~66%), `work_mem=16MB`, `maintenance_work_mem=256MB`.
- **WAL / crash safety:** `wal_level=replica`, `max_wal_size=2GB`,
  `checkpoint_completion_target=0.9`, `wal_compression=on`. `wal_level=replica`
  lets you take consistent base backups and add a replica later without a restart.
- **Autovacuum on** with slightly aggressive scale factors — the report execution
  log churns and needs regular vacuuming.
- `log_min_duration_statement=1000` logs slow (>1s) metadata queries.

**Persistence:** the `db_data` named volume. **A volume is not a backup** — see
§19 for `pg_dump`.

**Health check:** `pg_isready -U superset -d superset` (in compose); other
services wait for `service_healthy`.

**Maintenance — [HOST]:**
```bash
docker compose exec db psql -U superset -d superset -c "VACUUM (ANALYZE);"
docker compose exec db psql -U superset -d superset -c \
  "SELECT pg_size_pretty(pg_database_size('superset'));"
```

---

## 8. Redis (§ Redis configuration) — **[REDIS]**

One Redis instance serves **six roles** (broker, Celery results, general cache,
data cache, filter/explore state, SQL Lab results, async-query stream), separated
by **logical DB number** (see the map in `.env`). Full config in `redis/redis.conf`.

- **Memory cap:** `maxmemory 1024mb` (container limited to 1536 MB, leaving
  headroom). ⚙ TUNE — raise on a bigger box, but always keep a cap so Redis can
  never consume unlimited RAM.
- **Eviction:** `maxmemory-policy volatile-lru`. This is the crucial choice for a
  **shared** instance: it evicts **only keys that have a TTL** (cache, results),
  never the Celery **broker** keys (queued tasks have no TTL). `allkeys-lru`
  would happily evict your queued alerts — don't use it here.
- **Persistence:** AOF on (`appendonly yes`, `appendfsync everysec`) plus RDB
  snapshots. **What must persist:** queued Celery tasks (scheduled alerts) and
  in-flight async results. **What's safe to lose:** cache entries — they simply
  repopulate. AOF covers the broker; the cache regenerating on a cold start is
  fine.
- **Security:** password via `--requirepass` from `.env`; `protected-mode no` is
  safe **only** because Redis is never published to the host/Internet — it lives
  on the private Docker network.

**Advanced option:** for strict isolation, split into two instances — a durable
`noeviction` broker and an `allkeys-lru` cache with no persistence (documented at
the bottom of `redis/redis.conf`). The single-instance `volatile-lru` default is
a sound production choice; split only if cache churn starts evicting under memory
pressure.

**Inspect — [HOST]:**
```bash
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" info memory | grep used_memory_human
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" -n 0 llen celery   # queued tasks
```

---

## 9. Celery (§ Celery configuration)

Superset uses Celery for everything that can't happen inside a web request:
**async SQL Lab queries, Alerts & Reports execution, thumbnail/screenshot
rendering, and cache warm-up.**

- **worker** (`superset-worker`) — runs the tasks. `--concurrency=${CELERYD_CONCURRENCY}`
  (default 4). ⚙ TUNE: start at the number of vCPUs you'll dedicate to async
  work; screenshotting is memory-heavy, so watch RAM. Scale out with
  `docker compose up -d --scale superset-worker=3`.
- **beat** (`superset-worker-beat`) — the scheduler. **Runs as exactly one
  instance.** Two beats = every alert fires twice. Never `--scale` it.
- **Queues:** `sql_lab` and `thumbnails` are routed to dedicated queues so heavy
  async SQL doesn't starve fast report jobs. (Both workers currently consume all
  queues; split workers per-queue if one workload dominates.)
- **Retry / reliability:** `task_acks_late=True` re-queues a task if its worker
  dies mid-run; `worker_max_tasks_per_child=200` recycles workers to bound memory
  growth; `task_time_limit` / `task_soft_time_limit` cap runaway tasks.
- **Broker + result backend:** Redis (DBs 0 and 1).

**Verify — [HOST]:**
```bash
docker compose exec superset-worker celery --app=superset.tasks.celery_app:app inspect ping
docker compose exec superset-worker celery --app=superset.tasks.celery_app:app inspect active
```

---

## 10. Alerts & Reports (§ Alerts & reports) — **[SUPERSET]/[worker]**

Scheduled reports and threshold alerts email a rendered dashboard/chart to
recipients. The moving parts:

1. **beat** fires the `reports.scheduler` task every minute.
2. A **worker** picks up due reports, opens the dashboard in a **headless
   Chromium**, screenshots it, and emails it via SMTP.

**Version-critical dependency:** since **Superset 6.0** the default image ships
**without Chromium** (`INCLUDE_CHROMIUM=false`). That's why `docker/Dockerfile`
installs `playwright` + `playwright install chromium`. But installing the browser
is not enough — you must ALSO tell Superset to use Playwright, or 6.1.0 falls back
to **Selenium + Firefox** (not in the image) and every screenshot fails with
`Unable to obtain driver for firefox`. The switch is the feature flag
**`PLAYWRIGHT_REPORTS_AND_THUMBNAILS = True`** (already set in
`superset_config.py`). This one flag governs BOTH report screenshots and
dashboard/chart thumbnails. (On a 4.1–5.x pin the flag is
`PLAYWRIGHT_REPORT_SCHEDULES`, and it covered reports only — see §22.)

**Config (already in `superset_config.py`):**
- `FEATURE_FLAGS["ALERT_REPORTS"] = True`, `FEATURE_FLAGS["THUMBNAILS"] = True`.
- `WEBDRIVER_BASEURL = "http://superset:8088/"` — the **internal** address the
  worker's browser loads (fast, no TLS round-trip).
- `WEBDRIVER_BASEURL_USER_FRIENDLY = https://otm-bi.otmretail.ai/` — the
  **public** link placed in the email body.
- `ALERT_REPORTS_EXECUTORS = [("FixedExecutor", "admin")]` — which user the
  virtual browser authenticates as (tighten to a dedicated least-privilege
  reports user in production).
- `SMTP_*` + `SMTP_MAIL_FROM` — your mail relay.

**Enable in the UI:** create a report/alert on any dashboard or chart
(**⋯ → Set up an email report**). **Test — [HOST]:**
```bash
docker compose logs -f superset-worker | grep -i report   # watch a report run
```

Common pitfalls are in §21 (reports not generating).

---

## 11. WebSockets & async queries (§ WebSockets / async queries)

> **DEPLOYMENT DEFAULT: Global Async Queries is OFF** (`FEATURE_FLAGS[
> "GLOBAL_ASYNC_QUERIES"] = False`). Charts compute synchronously and paint on
> first load. In practice, enabling GAQ here caused charts to spin on first load
> and only render after a refresh (the async submit → ws/poll → cache-key
> retrieval round-trip returned a 404 on the result fetch). Unless you have
> dashboards whose queries run tens of seconds, leave it off — it's the standard,
> reliable configuration and the `superset-websocket` service can be stopped
> (`docker compose stop superset-websocket`). The rest of this section documents
> the WebSocket wiring for if/when you deliberately re-enable async. Note:
> embedding does NOT require GAQ.

**Which service handles WebSockets:** `superset-websocket` (Node, port 8080,
built from the Superset repo at your pinned tag). There is no official published
image, so the stack builds it.

**How Redis participates:** when you run an async SQL Lab query, the worker writes
the finished result to a Redis **stream**; the websocket service tails that stream
and pushes an event to the browser, which then fetches the result from the Redis
**results backend**.

**Feature flags / config required:**
- `FEATURE_FLAGS["GLOBAL_ASYNC_QUERIES"] = True`
- `GLOBAL_ASYNC_QUERIES_TRANSPORT = "ws"` (use `"polling"` to drop the ws service)
- `GLOBAL_ASYNC_QUERIES_CACHE_BACKEND` (6.x; was `..._REDIS_CONFIG` pre-6.0)
- `GLOBAL_ASYNC_QUERIES_JWT_SECRET` — **must match** the websocket's `jwtSecret`
- `GLOBAL_ASYNC_QUERIES_JWT_COOKIE_NAME = "async-token"` — **must match** the
  websocket's `jwtCookieName`
- `GLOBAL_ASYNC_QUERIES_WEBSOCKET_URL = "wss://otm-bi.otmretail.ai/ws/"`
- The Talisman CSP `connect-src` must include `wss://otm-bi.otmretail.ai`.

**How nginx routes it:** `location /ws/` proxies to the `superset_ws` upstream
with `Upgrade`/`Connection` headers and a long read timeout (see
`nginx/snippets/ws-proxy.conf`).

**Ports:**
- **Internal only:** `superset:8088`, `superset-websocket:8080`, `redis:6379`,
  `db:5432`, `flower:5555` (bound to host loopback). None are published to the
  Internet.
- **Public:** only nginx's 80/443.

**Don't want WebSockets?** Set `GLOBAL_ASYNC_QUERIES_TRANSPORT=polling` and remove
the `superset-websocket` service; the browser then polls results over HTTPS.
WebSockets give a snappier experience for long queries, which is why they're
included here.

---

## 11c. Embedding dashboards in other apps (guest-token method)

Internal apps (an Angular app at `http://localhost:4200` in dev, and
`https://merchandiser.otmretail.ai` in prod) embed OTM BI dashboards via
`@superset-ui/embedded-sdk` and **guest tokens**. This section was rewritten after
a long production debug; read the "gate ladder" at the end of §21a alongside it.

### 11c.1 Superset-side settings (all already applied)

Embedding is cross-site, so it needs a coordinated set of settings:

- **`FEATURE_FLAGS["EMBEDDED_SUPERSET"] = True`** — enables the embedded endpoints.
- **`EMBED_ORIGINS`** (in `superset_config.py`) — the single source of truth for
  the embedding origins, reused by CORS and the CSP allowlist. Origins are matched
  **exactly on scheme + host + port**: `http://localhost:4200` ≠
  `http://127.0.0.1:4200` ≠ `http://localhost:8000`. A test harness on the "wrong"
  localhost/port is refused with a `frame-ancestors` CSP violation — serve it from
  a listed origin or add its origin here (and strip test origins before prod).
- **CORS** — `ENABLE_CORS = True` with `CORS_OPTIONS` (supports_credentials,
  `origins = EMBED_ORIGINS`) so the SDK/iframe can call the API cross-origin.
- **CSP `frame-ancestors`** — `['self'] + EMBED_ORIGINS`, which is what actually
  authorizes the iframe. The old `X-Frame-Options: SAMEORIGIN` is removed from
  BOTH Talisman (`frame_options = None`) and nginx (both vhosts) — it can only say
  SAMEORIGIN and would block embedding.
- **`SESSION_COOKIE_SAMESITE = "None"`** (Secure already on) — a Lax cookie is not
  sent inside a cross-site iframe, so the embedded session needs None.
- **Per-dashboard `allowed_domains`** — a *separate* referrer allowlist from the CSP
  list, stored on each embedded dashboard (Embed dialog). If framing succeeds but
  `/embedded/<uuid>` returns **403**, this is why — add the hosting origin here too.
- **Guest tokens** — `GUEST_ROLE_NAME` (default `embedded_viewer`), a 5-minute token
  expiry (the SDK auto-refreshes), signed with `GUEST_TOKEN_JWT_SECRET` (set to
  `SECRET_KEY`).

### 11c.2 The four gates `guest_token` enforces — the core lesson

`POST /api/v1/security/guest_token/` is minted **server-to-server** by the embedding
app's backend (service account), and in 6.1.0 it requires **all four** of the
following. Each maps to a distinct error we hit; knowing the ladder turns a blank
iframe into a one-line diagnosis:

| Gate | Missing it returns | Provided via |
|------|--------------------|--------------|
| 1. Valid Bearer JWT **signature** | `422 {"msg":"Signature verification failed"}` | `Authorization: Bearer <access_token>` from a fresh login under the current `SECRET_KEY` |
| 2. CSRF token | `400 "The CSRF token is missing"` | `X-CSRFToken` header + the session cookie returned by `csrf_token` |
| 3. Referrer | `400 "The referrer header is missing"` | `Referer: https://<superset-host>/` (WTF_CSRF_SSL_STRICT, on for HTTPS) |
| 4. Role rights | `403` / `1011` | service account may mint; guest gets `GUEST_ROLE_NAME` |

**Two hard-won corrections to earlier assumptions, recorded so they aren't repeated:**

- **`guest_token` DOES require CSRF *and* a referrer, even with a valid Bearer JWT.**
  The correct backend sequence is therefore: (a) `POST /api/v1/security/login` →
  `access_token`; (b) `GET /api/v1/security/csrf_token/` with that Bearer, keeping
  the session cookie; (c) `POST /api/v1/security/guest_token/` with Bearer +
  `X-CSRFToken` + that cookie + `Referer`. Do **not** "simplify" by removing the
  csrf_token call — the mint will 400.
- **Do NOT add a `FLASK_APP_MUTATOR` hook that fakes a `csrf_token` 200 for Bearer
  requests.** We tried it while mis-reading the first 422 as "session-bound"; it only
  masked the real fault (a bad service-account token) and hands a CSRF token to any
  caller. It is not in the shipped config and must not be carried to a new server.

### 11c.3 SECRET_KEY stability — the root cause of "works here, fails there"

The Bearer `access_token` is signed with `SECRET_KEY` (Superset sets no separate
`JWT_SECRET_KEY`). Therefore:

- If `SECRET_KEY` **changes**, every token minted under the old key fails gate 1
  (`Signature verification failed`) — including the ones an embedding backend has
  **cached** (e.g. in its own Redis). Its `refresh` call fails the same way, so it
  cannot self-heal; it must **re-login**.
- "It works from my local test but not from the production app" is almost always
  **token provenance, not origin**: the local harness logs in fresh each run (valid
  signature), while a long-running backend that logged in *once* (before the key
  changed, or with the wrong credentials) keeps presenting a stale/invalid token.
- **Pin `SUPERSET_SECRET_KEY` in `.env` and never let a rebuild regenerate it** (see
  §4.1). If you must rotate it, run `superset re-encrypt-secrets` **and** restart
  every client that caches a token, in the same window.
- Also confirm the embedding backend uses the **correct service-account
  credentials** — wrong creds produce the same failed-mint symptom (this was the
  actual root cause in the first deployment).

### 11c.4 One-time setup in Superset (as admin)

1. Create a role matching `GUEST_ROLE_NAME` (e.g. `embedded_viewer`) and grant it
   access to ONLY the datasets/dashboards you expose. (In 6.1.0 the role-editor UI
   can 400 on permission filters; grant via `security_manager` in a shell if so.)
2. Open the dashboard → **⋯ → Embed dashboard** → copy the **embed UUID**, and add
   each hosting origin to that dashboard's **allowed_domains**.

### 11c.5 In the embedding app

1. The **backend** authenticates to Superset (service account) and runs the
   login → csrf → guest_token sequence in §11c.2, returning `{ "token": "<JWT>" }`.
   Do this server-side — never ship admin credentials to the browser.
2. The frontend calls `embedDashboard({ id: <uuid>, supersetDomain:
   "https://otm-bi.otmretail.ai", fetchGuestToken: () => <call your backend>.then(r
   => r.token), dashboardUiConfig: {...} })`. `fetchGuestToken` must resolve to the
   **guest token string**, i.e. `res.token` — not the whole object, and not a CSRF
   token.

**Adding/removing an embedding origin later:** edit `EMBED_ORIGINS` in
`superset_config.py` (it feeds both CORS and frame-ancestors), update each
dashboard's `allowed_domains`, and `docker compose up -d --force-recreate superset`.
No nginx change needed.

**Third-party-cookie note:** browsers are phasing out third-party cookies. The
guest token is the primary auth, but if an embedded dashboard misbehaves only in
a strict-privacy browser, that's the cause — serving the embedding app and
Superset under the same parent domain (e.g. both under `*.otmretail.ai`) avoids
the third-party context entirely.

### 11c.6 Row-Level Security (RLS) — per-tenant data scoping

By default a guest token carries `rls: []`, so **every** guest sees the **full**
data on the dashboard. To show each viewer only their own rows (e.g. each
merchandiser only their outlets), inject an RLS clause **into the guest token at
mint time**. Because the clause is baked into the signed token by your trusted
backend, the browser can neither see nor change it — that is what makes it a real
security boundary rather than a UI filter.

Each entry in the `rls` array:

```jsonc
"rls": [
  { "clause": "merchandiser_code = 'M00123'" },          // applies to ALL datasets
  { "clause": "owner_code = 'M00123'", "dataset": 22 }   // scoped to dataset id 22
]
```

- **`clause`** — a raw SQL boolean expression, injected as `AND (<clause>)` on every
  query. Quote strings; leave numbers unquoted.
- **`dataset`** (optional) — a Superset dataset **id**. Present → the clause applies
  only to that dataset; omitted → it applies to every dataset backing the token's
  dashboards (so the column must exist in all of them, or those queries error —
  scope per-dataset when a dashboard mixes tables).

Setup: the backend substitutes the value from the **authenticated user's own
identity** (their server-side session/JWT), never from anything the browser passes.
It is raw SQL, so treat the injected value as sensitive — take it from the trusted
session and ideally validate it against a known set. Index the filter column on
large tables.

Verify: mint a token with the clause, decode the JWT payload and confirm
`rls_rules` is populated (was `[]` before), load the dashboard as that guest, and
confirm the row counts match only that tenant — and that fiddling with dashboard
filters cannot widen the result (the clause is `AND`-ed beneath every chart query).

(Native RLS rules under **Settings → Row Level Security** attach a *fixed* clause to
a *role*/dataset and are the right tool for non-embedded users or a static baseline;
for embedding, the per-token `rls` array above is what scopes each guest.)

---

## 12. Networking (§ Networking)

- One user-defined bridge network, `superset_net`. All services attach to it and
  address each other by **service name** (`db`, `redis`, `superset`,
  `superset-websocket`, …) via Docker's embedded DNS — no hard-coded IPs.
- **No `ports:` on internal services.** The only published ports are nginx's
  `80` and `443`. `flower` is published to `127.0.0.1:5555` (host loopback) so
  it's reachable only via an SSH tunnel, never the network.
- Nginx reaches the app as `http://superset:8088` and the ws service as
  `http://superset-websocket:8080`, both purely inside `superset_net`.

To reach Flower from your laptop — **[HOST/laptop]:**
```bash
ssh -L 5555:127.0.0.1:5555 user@server   # then open http://localhost:5555
```

---

## 13. Security (§ Security / Firewall configuration)

Treat this as Internet-facing. Layers:

**Firewall (UFW) — [HOST]:**
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH                 # or: sudo ufw allow 22/tcp
sudo ufw allow 80/tcp                  # ACME + HTTP→HTTPS redirect
sudo ufw allow 443/tcp                 # HTTPS
# Optionally restrict the internal HTTPS vhost to the LAN only:
# sudo ufw allow from 10.0.0.0/8 to any port 443 proto tcp
sudo ufw enable
sudo ufw status verbose
```
Do **not** open 5432, 6379, 8088, 8080 or 5555. Docker publishes nothing else,
and UFW denies them anyway. **Never disable the firewall.**

> **Docker + UFW caveat:** Docker manipulates iptables directly and can bypass
> UFW for **published** ports. Since we publish only 80/443 (public) and
> 127.0.0.1:5555 (loopback), there's nothing sensitive to leak. If you ever add a
> `ports:` mapping, bind it to `127.0.0.1:` or install `ufw-docker` to enforce
> UFW on Docker-published ports.

**SSH hardening — [HOST]** (`/etc/ssh/sshd_config.d/99-hardening.conf`):
```
PermitRootLogin no
PasswordAuthentication no        # key-based auth only
KbdInteractiveAuthentication no
X11Forwarding no
MaxAuthTries 3
```
```bash
sudo systemctl restart ssh       # keep your current session open until you re-test
```

**Application security (already configured):** HTTPS everywhere, `Secure` +
`HttpOnly` + `SameSite=Lax` cookies, CSRF on, Talisman security headers (HSTS,
CSP, frame options), strong `SECRET_KEY`, strong DB/Redis passwords, no broad
CORS.

**Docker/host hygiene:** containers run under the image's unprivileged user; no
`privileged: true`; secrets only in `.env` (chmod 600), never in the compose
file or image. Keep the host and images patched (§20).

**Backup protection:** `backups/` and `.env` contain everything needed to
impersonate the deployment and decrypt connection secrets — store copies
**encrypted and off-host** (§19).

---

## 14. DNS (§ DNS configuration)

Two **different** resolution paths:

- **Public:** `otm-bi.otmretail.ai → PUBLIC_SERVER_IP` — an **A** (or **AAAA**)
  record in the `otmretail.ai` public zone. This must resolve **before** you run
  `init-letsencrypt.sh`, because Let's Encrypt validates by hitting
  `http://otm-bi.otmretail.ai/.well-known/acme-challenge/…`.
- **Internal:** `otm-bi.otm.internal` is a **private** name. It is not (and
  cannot be) in public DNS, so Let's Encrypt can't certify it. Resolve it via
  your **internal DNS server** (an A record on your AD/BIND/Unbound resolver
  pointing at the server's LAN IP) or, for a handful of machines, `/etc/hosts`:
  ```
  10.20.0.15   otm-bi.otm.internal
  ```

The public path is reachable from anywhere and TLS-trusted by every browser; the
internal path is reachable only on your LAN and trusted only by clients that have
your internal CA / self-signed cert installed.

---

## 15. Nginx (§ Nginx configuration)

Full config in `nginx/`. What matters for Superset:

- **HTTP→HTTPS redirect** for the public domain, with an exception for the ACME
  challenge path.
- **TLS termination** (`ssl-params.conf`: TLS 1.2/1.3, modern ciphers, OCSP
  stapling on the public vhost).
- **Forwarded headers** — `Host`, `X-Real-IP`, `X-Forwarded-For`,
  `X-Forwarded-Host/Port`, and crucially **`X-Forwarded-Proto https`** set
  per-vhost. Combined with `ENABLE_PROXY_FIX`, this makes Superset generate
  correct **https** URLs and not fall into redirect loops.
- **WebSocket routing** — `location /ws/` sends `Upgrade`/`Connection` headers to
  the ws upstream with a 1-hour read timeout.
- **Timeouts sized for BI** — `proxy_read_timeout 300s` on the app so long SQL
  Lab queries and heavy dashboards don't 504. **Do not** drop this to the nginx
  default 60s. Keep it ≥ `SUPERSET_WEBSERVER_TIMEOUT`.
- **Buffering on** with enlarged buffers so slow browsers don't tie up Gunicorn
  workers, while large dashboard JSON still flows.
- **`client_max_body_size 100m`** for dashboard/CSV imports.
- **Security headers** (HSTS, `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`) and per-vhost access/error logs.
- **gzip** on JSON/JS/CSS to shrink dashboard payloads.

**Reload after any nginx edit — [HOST]:**
```bash
docker compose exec nginx nginx -t          # test config
docker compose exec nginx nginx -s reload   # zero-downtime reload
```

---

## 16. TLS / certificates recap (§ Reverse proxy / HTTPS)

- **Public** (`otm-bi.otmretail.ai`): **Let's Encrypt via certbot**, webroot
  method. `scripts/init-letsencrypt.sh` bootstraps it (dummy cert → nginx up →
  real cert → reload). The `certbot` service then auto-renews every 12h and nginx
  picks up the new cert. Test renewal — **[HOST]:**
  `docker compose run --rm certbot renew --dry-run`.
- **Internal** (`otm-bi.otm.internal`): **not** publicly certifiable. Use an
  **internal CA** (preferred — issue a cert and add the CA to clients' trust
  stores) or the provided **self-signed** cert (`gen-internal-cert.sh`).
  **Serve it over HTTPS, not plain HTTP**, because Superset's `Secure` cookies
  aren't sent over HTTP — a plain-HTTP internal endpoint would silently break
  login and async queries. The internal vhost is configured for HTTPS
  accordingly; the HTTP-only alternative (and its caveat) is documented in
  `nginx/conf.d/otm-bi.otm.internal.conf`.

---

## 17. Performance & sizing (§ Performance) — how to pick the numbers

Don't allocate blindly. Start from the **baseline (8 vCPU / 16 GB)** values in
`.env`, then adjust with these rules:

| Knob | Where | Baseline | How to size it |
|---|---|---|---|
| **Gunicorn workers** | `SERVER_WORKER_AMOUNT` | 8 | `(2 × vCPU) + 1`, then cap by RAM (each worker ≈ 300–600 MB). On 4 vCPU use 5–9; on 16 vCPU, ~17 only if RAM allows. With `gthread`, threads add concurrency cheaply. |
| **Gunicorn threads** | `SERVER_THREADS_AMOUNT` | 20 | Raise for I/O-bound dashboards; lower if CPU-bound. |
| **Web timeout** | `GUNICORN_TIMEOUT` / `SUPERSET_WEBSERVER_TIMEOUT` | 120 / 300 | Keep ≥ your slowest sync query and ≥ nginx `proxy_read_timeout`. |
| **Celery concurrency** | `CELERYD_CONCURRENCY` | 4 | ≈ vCPUs dedicated to async work. Screenshots are RAM-heavy — if reports OOM, lower this or scale workers out instead. |
| **Worker replicas** | `--scale superset-worker=N` | 1 | Add replicas before pushing single-worker concurrency high. |
| **Postgres connections** | `max_connections` | 120 | ≥ `(workers + threads-in-flight + celery + overhead)`. Prefer PgBouncer over large numbers. |
| **Postgres memory** | `shared_buffers` / `effective_cache_size` | 768MB / 2GB | ~25% / ~66% of the **db container** memory limit. |
| **Redis memory** | `maxmemory` (redis.conf) + container limit | 1024mb / 1536m | Set `maxmemory` below the container limit; raise both together on a bigger box. |
| **Container CPU/RAM limits** | `deploy.resources.limits` in compose | see file | Sum of limits should sit under total host RAM with ~15% headroom for the OS. |

**Process to right-size once the real spec is known:**
1. Set container limits so their **sum ≤ ~85% of host RAM** (leave the rest for
   the kernel/page cache).
2. Set `SERVER_WORKER_AMOUNT` from CPU, then check steady-state memory under load
   with `docker stats` and back off if the `superset` container nears its limit.
3. Load-test a heavy dashboard; if you see 504s, raise `proxy_read_timeout` +
   `SUPERSET_WEBSERVER_TIMEOUT`, not the whole box.
4. If async queries queue up, scale `superset-worker`; if the metadata DB is the
   bottleneck (rare), it's usually connection exhaustion → add PgBouncer.

**Values to change first on a non-baseline server:** `SERVER_WORKER_AMOUNT`,
`CELERYD_CONCURRENCY`, `max_connections`, `shared_buffers`/`effective_cache_size`,
Redis `maxmemory`, and every `deploy.resources.limits` block.

---

## 18. Monitoring (§ Monitoring)

**Built-in, no extra tools — [HOST]:**
```bash
docker compose ps                       # container state + health
docker compose logs -f superset         # app logs (also: superset-worker, nginx)
docker stats                            # live CPU/RAM/IO per container
docker inspect --format '{{json .State.Health}}' superset_app   # health detail
df -h                                   # disk (watch /var/lib/docker)
free -h                                 # host memory
htop                                    # processes
./scripts/healthcheck.sh                # one-shot roll-up of the whole stack
```

**What to watch, and where:**
- **Containers** — `docker compose ps` (any `Restarting`/`unhealthy`?).
- **CPU/RAM** — `docker stats` (a container pinned at its mem limit will OOM-kill).
- **Disk** — `df -h`; Docker logs are capped (50 MB × 5 per service) but Postgres
  data and backups grow.
- **PostgreSQL** — slow-query log (`log_min_duration_statement`), DB size query
  (§7), connection count.
- **Redis** — `redis-cli info memory` / `info stats` (evictions, keyspace).
- **Celery / failed jobs** — **Flower** (task success/failure, latency) and
  `superset-worker` logs; in the UI, **Alerts & Reports → execution log**.
- **Gunicorn / Nginx** — nginx access/error logs in `logs/nginx/` (`rt=` request
  time, upstream times, 5xx rate).
- **Superset errors** — `docker compose logs superset` (tracebacks), plus the
  app's own **Query History** and **Logs** views.

**Later: Prometheus + Grafana.** Add `cadvisor` (container metrics),
`node-exporter` (host), `redis_exporter`, `postgres_exporter`, and
`nginx-prometheus-exporter` as extra services on `superset_net`, scrape them with
a `prometheus` container, and visualise in `grafana`. Superset also exposes
StatsD-style metrics you can bridge to Prometheus. Keep all of these bound to the
private network / loopback and reach Grafana via nginx or an SSH tunnel — don't
publish exporters.

---

## 19. Backups (§ Backups)

**A Docker volume is not a backup.** Back up **logical dumps** + config.

**What to back up:**
- **Metadata DB** — `pg_dump` (dashboards, charts, users, roles, saved queries,
  encrypted connection defs). This is the crown jewels. → `scripts/backup-postgres.sh`
- **`.env`** — secrets, incl. the `SECRET_KEY` needed to decrypt the dump's
  connection passwords. Store **encrypted, off-host**.
- **Config** — `superset_config.py`, `docker-compose.yml`, `nginx/`, `redis/`,
  `postgres/`, `scripts/`, and the **internal** cert. → `scripts/backup-config.sh`

**What you don't need to back up:** the `redis_data` volume (cache/queues rebuild;
at most you lose in-flight async results and pending schedules), the `superset_home`
volume (regenerable), the **public** Let's Encrypt cert (certbot re-issues it),
and Docker images (rebuilt from the pinned tag).

**Take a backup — [HOST]:**
```bash
./scripts/backup-postgres.sh            # verified, gzipped pg_dump into backups/
./scripts/backup-config.sh              # config+secrets tarball into backups/
```
The DB script verifies each archive with `pg_restore --list` and prunes dumps
older than `BACKUP_RETENTION_DAYS` (14).

**Schedule it — [HOST]** (`crontab -e`):
```cron
30 1 * * *  cd /opt/otm-superset && ./scripts/backup-postgres.sh >> logs/backup.log 2>&1
0  2 * * 0  cd /opt/otm-superset && ./scripts/backup-config.sh   >> logs/backup.log 2>&1
```
Then **copy `backups/` off the host** (object storage / another server), ideally
encrypted (`age`/`gpg`). Test a restore into a scratch environment periodically.

**Restore — [HOST]:**
```bash
docker compose stop superset superset-worker superset-worker-beat \
  superset-flower superset-websocket
./scripts/restore-postgres.sh backups/superset_superset_YYYYMMDD_HHMMSS.dump.gz
docker compose up -d
```
> The `.env` `SECRET_KEY` at restore time **must match** the one used when the
> backup was taken, or encrypted connection passwords won't decrypt.

---

## 20. Upgrade strategy (§ Upgrade considerations)

**Never** bump to `latest` blindly. Superset majors (4→5→6) carry breaking
changes (see §22). Procedure:

1. **Read `UPDATING.md`** for every version between your current pin and the
   target. Note removed/renamed config options and feature flags.
2. **Back up first — [HOST]:** `./scripts/backup-postgres.sh && ./scripts/backup-config.sh`.
3. **Pick an exact patch tag.** Edit `.env`: `SUPERSET_VERSION` and bump
   `SUPERSET_CUSTOM_IMAGE` (e.g. `otm/superset:6.2.0-1`) so Compose rebuilds.
4. **Rebuild — [HOST]:** `docker compose build superset superset-websocket`.
5. **Migrate — [HOST]:** `docker compose run --rm superset-init` runs
   `superset db upgrade`. On large deployments some 5.x/6.x migrations add
   indexes and can briefly lock tables — do it in a maintenance window.
6. **Roll — [HOST]:** `docker compose up -d`. Compose recreates services;
   `restart: unless-stopped` + healthchecks keep things orderly. For minimal
   downtime, workers/beat can be updated a moment after the web tier.
7. **Verify** with §21 checks and a smoke test (login, a dashboard, an async
   query, a test report).

**Rollback:** set `SUPERSET_VERSION`/image back to the previous pin,
`docker compose up -d`. **If the new version already ran `db upgrade`, restore the
pre-upgrade dump** (§19) — schema downgrades aren't supported. This is exactly why
step 2 is non-negotiable.

**Also upgrade** the base OS, Docker, and the `postgres`/`redis`/`nginx` pins on a
cadence — but bump Postgres **majors** only via a planned dump/restore or
`pg_upgrade`, never by swapping the tag on a populated volume.

---

## 21. Troubleshooting (§ Troubleshooting)

Format: **symptom → likely cause → diagnose → fix.**

**Superset returns 502 (Bad Gateway)**
Cause: app container down/unhealthy or still booting. Diagnose:
`docker compose ps`; `docker compose logs --tail=100 superset`. Fix: wait for the
healthcheck `start_period`; if it's crash-looping, the log shows why (usually a
bad `SECRET_KEY`, DB unreachable, or a config typo).

**Nginx can't reach Superset / "host not found in upstream"**
Cause: app not on the network yet, or name typo. Diagnose:
`docker compose exec nginx ping -c1 superset`;
`docker compose exec nginx nginx -t`. Fix: ensure `superset` is up; reload nginx.

**Superset container repeatedly restarts**
Cause: startup exception. Diagnose: `docker compose logs superset | tail -50`.
Common: placeholder `SECRET_KEY`/`GLOBAL_ASYNC_QUERIES_JWT_SECRET` (6.x aborts),
can't connect to `db`/`redis`, or a Python error in `superset_config.py`. Fix the
offending value and `docker compose up -d`.

**PostgreSQL connection errors ("could not connect" / "too many clients")**
Diagnose: `docker compose logs db`;
`docker compose exec db psql -U superset -c "SELECT count(*) FROM pg_stat_activity;"`.
Fix: confirm `POSTGRES_PASSWORD` matches in `.env`; if connections are exhausted,
lower pool sizes or raise `max_connections`/add PgBouncer (§17).

**Redis connection errors / NOAUTH**
Diagnose: `docker compose exec redis redis-cli -a "$REDIS_PASSWORD" ping`. Fix:
ensure the same `REDIS_PASSWORD` everywhere (app, worker, ws, flower all read
`.env`); check the DB numbers in the Redis map.

**Celery worker not processing tasks**
Diagnose: `docker compose exec superset-worker celery -A superset.tasks.celery_app:app inspect ping`;
check queue depth `redis-cli -n 0 llen celery`; watch `docker compose logs -f superset-worker`.
Fix: confirm worker is up and pointed at the same broker; make sure **beat** is
running for scheduled tasks.

**Reports not being generated**
Cause (6.x): missing headless browser or SMTP misconfig. Diagnose:
`docker compose logs superset-worker | grep -iE "report|playwright|screenshot|smtp"`.
Fix: ensure the custom image built Chromium (`playwright install chromium`
succeeded); verify `SMTP_*`; confirm **beat** is scheduling `reports.scheduler`;
check the UI execution log. Test SMTP from the container with a quick Python
`smtplib` snippet.

**WebSockets failing (async queries never return / console shows ws errors)**
Diagnose: browser devtools → Network → WS (is `wss://…/ws/` 101 Switching
Protocols?); `docker compose logs superset-websocket`. Fix: `jwtSecret` and
`jwtCookieName` must match between `superset_config.py` and the ws config; nginx
`/ws/` must send upgrade headers; the Talisman CSP `connect-src` must include
`wss://otm-bi.otmretail.ai`; confirm both share the same Redis GAQ DB.

**HTTPS redirect loop (ERR_TOO_MANY_REDIRECTS)**
Cause: both nginx and Talisman forcing https behind the proxy, or ProxyFix not
trusting the proto. Fix: keep `force_https=False` in `TALISMAN_CONFIG`, ensure
nginx sends `X-Forwarded-Proto https`, and `ENABLE_PROXY_FIX=True`.

**Incorrect http:// URLs (report links / redirects use http)**
Cause: ProxyFix/scheme not applied. Fix: `ENABLE_PROXY_FIX=True`,
`PREFERRED_URL_SCHEME="https"`, nginx sets `X-Forwarded-Proto`, and
`WEBDRIVER_BASEURL_USER_FRIENDLY` is the https public URL.

**CSRF errors ("The CSRF token is missing/expired")**
Cause: proxy dropping the Host/scheme, clock skew, or a stale tab. Diagnose:
check forwarded headers reach the app. Fix: forwarded headers as above;
`WTF_CSRF_TIME_LIMIT=None` (already set) avoids stale-tab expiry. Don't "fix" it
by adding endpoints to `WTF_CSRF_EXEMPT_LIST`.

**CORS errors**
Cause: calling the API from another origin with CORS off (correct default). Fix:
only if you truly embed/serve from another origin, set `ENABLE_CORS=True` and a
**scoped** `CORS_OPTIONS` (never `*`). Otherwise serve everything same-origin.

**Dashboard loads slowly**
Diagnose: nginx `rt=`/upstream times; Superset Query History; DB slow log. Fix:
ensure `DATA_CACHE_CONFIG` (Redis) is working; enable dashboard caching timeouts;
optimise the underlying BI query/datasource; consider cache warm-up (§9).

**Async queries not working at all**
Diagnose: is `GLOBAL_ASYNC_QUERIES` flag on? worker + ws + redis healthy?
Fix: the four must all be up; check the JWT secret match and CSP as above.

**SECRET_KEY / decryption errors ("Invalid decryption key" / Fernet errors)**
Cause: `SECRET_KEY` changed after connections were saved. Fix: restore the
original key, or rotate properly —
`docker compose exec superset superset re-encrypt-secrets`.

**Database migrations failing**
Diagnose: `docker compose run --rm superset-init` output; `docker compose logs db`.
Fix: ensure you backed up, the DB is reachable, and you didn't skip intermediate
versions. Restore the dump and retry the upgrade in a window (§20).

---

## 21a. First-build gotchas actually hit on this stack (6.1.0)

These are lean-6.x-image and build-from-source issues encountered bringing the
stack up the first time. All are already fixed in the shipped files; this record
is so the next rebuild/upgrade doesn't rediscover them.

**`superset-init` fails: `ModuleNotFoundError: No module named 'psycopg2'`**
Cause: the lean 6.x image does not bundle the PostgreSQL driver. Fix: the custom
image (`docker/Dockerfile`) installs `psycopg2-binary`. Critical subtlety — a
plain `pip install` in that image lands in a different site-packages than the
`/app/.venv` Superset runs from, so the package appears "installed" yet Superset
still can't import it. The Dockerfile therefore installs with
`uv pip install --python /app/.venv/bin/python …` and runs a build-time
`import psycopg2` check that FAILS THE BUILD if it didn't reach the venv. Any new
Python dependency must go through that same path.

**Build fails on resolution, or app fails with
`ImportError: cannot import name 'eagerload' from 'sqlalchemy.orm'`**
Cause: a BI-source driver (typically `snowflake-sqlalchemy`; also possible with
`sqlalchemy-redshift`/`sqlalchemy-hana`) pulls **SQLAlchemy 2.0**, which removes
`eagerload`; Superset 6.1.0 needs SQLAlchemy 1.4.x. Fix: the Dockerfile freezes
Superset's existing pins into a constraints file and installs the extra drivers
with `-c constraints.txt`, so no driver can move SQLAlchemy (or anything else
Superset pins); a build-time canary asserts SQLAlchemy stays `< 2`. If a build
now fails during resolution naming a conflict, that driver has no version
compatible with Superset's pins — drop it from `EXTRA_PY_PKGS` (snowflake is the
usual culprit) and rebuild, or add it later in isolation.

**`superset-flower` restarts with exit 2**
Symptom: `docker compose logs superset-flower` shows `Error: No such command
'flower'`. Cause: the `flower` package isn't bundled in the Superset image. Fix:
it's in the Dockerfile's `EXTRA_PY_PKGS`. Rebuild the image and recreate flower.

**`superset-websocket` restarts (255): `exec /app/entrypoint.sh: exec format error`**
The kernel can't exec the script. Two causes seen, both about the file's first
bytes, neither about the code: (1) a **missing/replaced shebang** — the file's
first line must be `#!/bin/sh` (check with `head -c 3 websocket/entrypoint.sh |
od -An -tx1` → expect `23 21 2f`); (2) a **UTF-8 BOM** or CRLF that pushes/breaks
the shebang. Fixes applied: the websocket `Dockerfile` strips a leading BOM and
CRLF at build time AND uses `ENTRYPOINT ["sh", "/app/entrypoint.sh"]` (the kernel
execs `/bin/sh`, a real binary, so a bad shebang can never cause this again). If
a transferred `entrypoint.sh` is ever corrupted, recreate it on the host with a
quoted heredoc (`cat > websocket/entrypoint.sh <<'EOF' … EOF`) rather than
re-downloading.

**`superset-websocket` is Up but `(unhealthy)`; log shows only the startup echo**
Cause: the ws service is a CLI — it only launches the server when invoked as
`node dist/index.js start`. Without the `start` subcommand the process idles and
never binds 8080 (`NOT LISTENING: ECONNREFUSED`). Fix: `entrypoint.sh` ends with
`exec node /app/dist/index.js start`. Verify listening with
`docker compose exec superset-websocket node -e "require('net').connect(8080,'127.0.0.1',()=>process.exit(0)).on('error',()=>process.exit(1))"`;
a healthy service logs `{"level":"info","message":"Server started on port 8080"}`.

**`nginx` won't boot: `host not found in upstream "superset-websocket:8080"`**
Cause: nginx resolves upstream hostnames at **startup**, so if `superset` or
`superset-websocket` is down/unresolvable when nginx (re)starts, nginx refuses to
boot — one non-critical backend takes the whole entry point down. Fix (upstream-
resilience hardening): `nginx/nginx.conf` drops the `upstream {}` blocks and adds
`resolver 127.0.0.11 valid=10s;` (Docker's embedded DNS); each vhost puts the
backend in a variable (`set $app_upstream "superset:8088";
proxy_pass http://$app_upstream;`) so resolution happens at **request** time. A
down backend now returns 502 for just that route while nginx stays up. The `/ws/`
location keeps its prefix-strip via `rewrite ^/ws/(.*)$ /$1 break;`. Trade-off:
variable `proxy_pass` can't use upstream keepalive (needs a named upstream block)
— negligible in front of Gunicorn on a local network. Verify the hardening by
stopping a backend and confirming `docker compose restart nginx` still comes up:
`docker compose stop superset-websocket && docker compose restart nginx &&
docker compose ps nginx` → `Up (healthy)`.

**Dashboard charts spin on first load, render only after a refresh; console shows
`POST /api/v1/chart/data` → 404 `{"message":"Not found"}`**
Cause: Global Async Queries. On a cold load each chart submits an async job and
then fetches the result by cache key; that retrieval round-trip (WebSocket/poll +
`GET /api/v1/chart/data/<cache_key>`) misses and returns "Not found". A refresh
serves the now-cached result synchronously, so it appears to "work on refresh."
Fix: set `FEATURE_FLAGS["GLOBAL_ASYNC_QUERIES"] = False` and
`docker compose up -d --force-recreate superset superset-worker`. Charts then
compute synchronously and paint on first load. This is the deployment default
(§11). It is unrelated to the WebSocket host or the thumbnail engine.

**Thumbnails / report screenshots fail; `/api/v1/{chart,dashboard}/<id>/thumbnail/<hash>`
returns 404; worker log shows `Unable to obtain driver for firefox`**
Cause: the browser is installed (Playwright + Chromium) but Superset wasn't told
to use it, so 6.1.0 falls back to Selenium + Firefox, which isn't in the image.
Fix: set `FEATURE_FLAGS["PLAYWRIGHT_REPORTS_AND_THUMBNAILS"] = True` in
`superset_config.py`, then `docker compose up -d --force-recreate superset
superset-worker`. This governs both thumbnails and Alerts & Reports screenshots.
Note the welcome/home page shows thumbnail spinners while this is broken — that is
NOT the dashboard chart-data path (charts load from `/api/v1/chart/data`, no
browser involved).

**`nginx` won't boot: `cannot load certificate ".../fullchain.pem"`**
Cause: the referenced TLS cert doesn't exist yet. Fix: issue the public cert
(`./scripts/init-letsencrypt.sh`, needs public DNS → server) and the internal
cert (`./scripts/gen-internal-cert.sh`). If public DNS isn't ready, drop a
temporary self-signed cert at
`certbot/conf/live/otm-bi.otmretail.ai/{fullchain,privkey,chain}.pem` so nginx
boots, then swap in Let's Encrypt once DNS resolves (§16).

**`nginx` container shows `(unhealthy)` though the site works**
Cause: the healthcheck used `http://localhost/healthz`, and `localhost` can
resolve to IPv6 `::1` while nginx listens on IPv4 only. Fix: the healthcheck in
`docker-compose.yml` uses `http://127.0.0.1/healthz`.

**Embedded dashboard is blank / won't load — the guest-token gate ladder**
The iframe shell loads (`GET /embedded/<uuid>` → 200) but no `chart/data` ever
fires. Isolate which gate fails by minting a token by hand on the server, adding one
piece at a time — the first error tells you exactly what the embedding backend is
missing (see §11c.2):

```bash
# [HOST] 1) fresh login under the CURRENT secret
ACCESS=$(curl -sk https://otm-bi.otmretail.ai/api/v1/security/login \
  -H "Content-Type: application/json" \
  -d '{"username":"<svc_user>","password":"<pw>","provider":"db","refresh":true}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) csrf token, keeping the session cookie
CSRF=$(curl -sk -c cookies.txt -H "Authorization: Bearer $ACCESS" \
  https://otm-bi.otmretail.ai/api/v1/security/csrf_token/ \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['result'])")

# 3) mint — needs Bearer + X-CSRFToken + cookie + Referer
curl -sk -b cookies.txt -X POST https://otm-bi.otmretail.ai/api/v1/security/guest_token/ \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" -H "Referer: https://otm-bi.otmretail.ai/" \
  -d '{"user":{"username":"embed","first_name":"E","last_name":"V"},
       "resources":[{"type":"dashboard","id":"<embed-uuid>"}],"rls":[]}'
```

Read the result against the table in §11c.2:
- `422 Signature verification failed` → the token is signed with a **different
  `SECRET_KEY`** (key changed, or the embedding backend logged in with **wrong
  credentials** / against a different Superset). Fix the creds / pin the key and make
  the backend **re-login** (restart it so its startup login re-mints). A *fresh*
  login here proves the key is fine; a stale cached token in the app does not.
- `400 CSRF token is missing` → the backend isn't sending `X-CSRFToken` + the session
  cookie from `csrf_token`.
- `400 The referrer header is missing` → add `Referer: https://<superset-host>/`.
- `{"token": "..."}` → the **server side is healthy**; the fault is in the app
  (wrong `fetchGuestToken` mapping, stale cached token, or a CSP/`allowed_domains`
  origin miss — check the browser console for a `frame-ancestors` violation or a
  `/embedded/` 403).

Harmless noise that is NOT the cause: `GET /static/service-worker.js → 404` (Superset
ships no service worker) and, from a browser with no Superset login, `csrf_token →
422` inside the iframe (a pure guest has no session; read-only chart data doesn't
need it because `chart/data` is CSRF-exempt).

---

## 22. Version differences to be aware of (4.x → 5.x → 6.x)

Because you asked not to assume old options still apply — the ones that bite in
a production config:

- **Alerts & Reports / thumbnails engine:** 6.0 made **Playwright** the intended
  screenshot engine and the base image dropped Chromium (`INCLUDE_CHROMIUM=false`).
  This stack installs Playwright+Chromium in `docker/Dockerfile` AND sets
  `FEATURE_FLAGS["PLAYWRIGHT_REPORTS_AND_THUMBNAILS"]=True`. Both are required: if
  the flag is off, 6.1.0 falls back to **Selenium + Firefox** (not installed) and
  all screenshots fail with `Unable to obtain driver for firefox`. On a **4.1–5.x**
  pin the flag is instead `PLAYWRIGHT_REPORT_SCHEDULES` (reports only).
- **Global Async Queries config key:** 6.x uses
  `GLOBAL_ASYNC_QUERIES_CACHE_BACKEND`; **< 6.0** used
  `GLOBAL_ASYNC_QUERIES_REDIS_CONFIG` (+ `..._REDIS_STREAM_PREFIX`). The
  pre-6.0 form is shown commented in `superset_config.py`.
- **Mandatory JWT secret:** 6.x refuses to start if `GLOBAL_ASYNC_QUERIES` is on
  and `GLOBAL_ASYNC_QUERIES_JWT_SECRET` is the default.
- **Executor options renamed:** `ALERT_REPORTS_EXECUTE_AS`/`THUMBNAILS_EXECUTE_AS`
  → `ALERT_REPORTS_EXECUTORS`/`THUMBNAILS_EXECUTORS` with the `FixedExecutor`
  class (used here).
- **Encryption engine:** 6.x can use authenticated **AES-GCM**
  (`SQLALCHEMY_ENCRYPTED_FIELD_ENGINE`). Migrating from the older `aes` engine is
  a two-pass `superset re-encrypt-secrets` operation — plan it, don't flip it
  blind.
- **Password policy:** 6.x enables FAB password complexity (min 8 chars, blocklist)
  by default — your admin/user passwords must comply.
- **Hash algorithm:** default moved MD5 → SHA-256, invalidating cached thumbnails
  on upgrade (they regenerate).
- **Feature flags graduated/removed:** several (e.g. dashboard cross-filters,
  legacy datasource editor toggle) became permanent — don't set them.
- **Python:** 3.10+ (3.11 preferred); 3.7/3.8 removed. The image handles this;
  relevant only if you build custom.
- **Postgres/Redis in the reference:** 17 / 7. We pin Postgres 16 for
  conservatism; both are fine.

Always cross-check the exact option names for **your** pinned tag in that
version's `UPDATING.md` and `docker/pythonpath_dev/superset_config.py`.

---

## 23. Production validation checklist

Run through this after deployment (commands are **[HOST]** unless noted):

```
[ ] Docker installed              docker --version
[ ] Docker Compose working        docker compose version
[ ] PostgreSQL healthy            docker compose ps | grep db      → (healthy)
[ ] Redis healthy                 docker compose exec redis redis-cli -a "$REDIS_PASSWORD" ping → PONG
[ ] Superset healthy              docker compose exec superset curl -fsS localhost:8088/health → OK
[ ] Gunicorn working              docker compose logs superset | grep -i "Listening at"
[ ] Celery worker working         docker compose exec superset-worker celery -A superset.tasks.celery_app:app inspect ping → pong
[ ] Celery beat working (x1)      docker compose logs superset-worker-beat | grep -i "beat: Starting"
[ ] WebSockets working            browser devtools → WS → wss://otm-bi.otmretail.ai/ws/ = 101
[ ] Alerts/reports working        create a test email report → arrives; check execution log
[ ] Nginx working                 curl -I https://otm-bi.otmretail.ai/ → 200/302
[ ] HTTPS certificate valid       curl -Iv https://otm-bi.otmretail.ai/ 2>&1 | grep -i "issuer\|expire"
[ ] Public DNS working            dig +short otm-bi.otmretail.ai  → your public IP
[ ] Internal DNS working          dig +short otm-bi.otm.internal  (or /etc/hosts) → LAN IP
[ ] HTTP/HTTPS routing correct    curl -I http://otm-bi.otmretail.ai/ → 301 https
[ ] Secure cookies working        login → devtools → cookies show Secure + HttpOnly
[ ] CSRF working                  forms submit fine; no CSRF errors in logs
[ ] Caching working               reload a dashboard → second load faster; redis keys present
[ ] Async queries working         SQL Lab "Run async" returns via ws
[ ] Backups working               ./scripts/backup-postgres.sh → verified archive in backups/
[ ] Firewall configured           sudo ufw status verbose → 22/80/443 only
[ ] No unnecessary ports exposed  ss -tlnp | grep -E ':(5432|6379|8088|8080)' → none on 0.0.0.0
[ ] Embedding mint works          §21a gate-ladder curl → {"token": "..."}
```

---

## 24. Porting this stack to another server

This whole bundle is portable. What moves unchanged vs what is
**environment-specific** and must be regenerated/edited:

**Copy as-is:** `docker-compose.yml`, `docker/` (Dockerfile + `superset_config.py`),
`nginx/`, `redis/`, `postgres/`, `websocket/`, `scripts/`, `.env.example`, and this
guide. The application logic and hardening are not server-specific.

**Regenerate / re-edit per environment (do NOT copy the old values):**
- **All secrets** — new `SUPERSET_SECRET_KEY`, `GLOBAL_ASYNC_QUERIES_JWT_SECRET`,
  `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `ADMIN_PASSWORD`, `FLOWER_BASIC_AUTH`
  (`./scripts/generate-secrets.sh`). A fresh `SECRET_KEY` is correct here — but it
  means **every embedding backend must log in fresh against the new server** (its old
  cached tokens are worthless; see §11c.3). Pin the new key from day one.
- **Hostnames / DNS / TLS** — new `SUPERSET_PUBLIC_HOST`, `SUPERSET_INTERNAL_HOST`,
  `CERTBOT_EMAIL`; re-issue Let's Encrypt (`init-letsencrypt.sh`, needs public DNS →
  new server) and the internal cert (`gen-internal-cert.sh`). The nginx vhost
  filenames/`server_name`s must match the new hosts.
- **Embedding wiring** — set `EMBED_ORIGINS` to the new consumer origins; set each
  dashboard's `allowed_domains`; create the `embedded_viewer` role and the
  **service account** on the new instance; point the embedding app's backend at the
  new Superset host **and its new service-account credentials**.
- **SMTP** for Alerts & Reports.

**Ordered bring-up on the new server:** follow §5 (build → data tier → certs →
init/admin → full stack), then §23 validation, then the §21a gate-ladder curl to
confirm embedding before wiring the consumer app. Metadata (dashboards, datasets,
roles) does **not** transfer with the files — either rebuild it, or migrate it with
Superset's `export-dashboards` / `import-dashboards` (or a `pg_dump` of the metadata
DB **plus the same `SECRET_KEY`**, since encrypted DB passwords are tied to it).

**Do NOT carry over:** the `FLASK_APP_MUTATOR` csrf interceptor (a misdiagnosis
workaround — never in the shipped config; see §11c.2) and any hand-added
`WTF_CSRF_EXEMPT_LIST` entries in the wrong `module.ClassName.method` format.

### 24.1 Enabling Global Async Queries on the new server

GAQ is **off** on this stack by default (§11) because cold-load charts spun and only
rendered on refresh. Plan to enable it deliberately on the new server and validate:

1. In `superset_config.py`: `FEATURE_FLAGS["GLOBAL_ASYNC_QUERIES"] = True`, and set
   `GLOBAL_ASYNC_QUERIES_TRANSPORT = "ws"`, `GLOBAL_ASYNC_QUERIES_CACHE_BACKEND`,
   `GLOBAL_ASYNC_QUERIES_JWT_SECRET` (**must equal** the websocket's `jwtSecret`),
   `GLOBAL_ASYNC_QUERIES_JWT_COOKIE_NAME = "async-token"`, and
   `GLOBAL_ASYNC_QUERIES_WEBSOCKET_URL = "wss://<new-public-host>/ws/"` (§11).
2. **CRITICAL for embedded + async — the async-token cookie.** The async feature
   sets its *own* cookie (`async-token`), separate from the session cookie. Inside a
   cross-site iframe a `Lax` cookie is **not sent**, so every chart/filter data
   request fails with `401 "Not authorized"` (`AsyncQueryTokenException`) — even
   though guest-token auth itself works. When dashboards are embedded, this cookie
   MUST be cross-site:
   ```python
   GLOBAL_ASYNC_QUERIES_JWT_COOKIE_SECURE = True
   GLOBAL_ASYNC_QUERIES_JWT_COOKIE_SAMESITE = "None"   # NOT "Lax" for embedded
   ```
   (The shipped `superset_config.py` already sets `None` for this reason. A purely
   non-embedded async deployment could use `Lax`.)
3. Ensure the Talisman CSP `connect-src` includes `wss://<new-public-host>`, and keep
   the `superset-websocket` service running (don't stop it as §11 allows when GAQ is
   off). Confirm the websocket service's `REDIS_DB`/JWT secret match
   `GLOBAL_ASYNC_QUERIES_CACHE_BACKEND`'s DB and `GLOBAL_ASYNC_QUERIES_JWT_SECRET` —
   a mismatch means async events silently never arrive (no error, just spinning).
4. `docker compose up -d --force-recreate superset superset-worker superset-websocket`.
5. Validate: SQL Lab "Run async" returns via the WS (devtools → WS →
   `wss://<host>/ws/` = 101); **cold-load a dashboard and confirm charts paint on
   first load, not only after a refresh** (a 404 on `GET /api/v1/chart/data/<cache_key>`
   = JWT/cookie/CSP misconfig); and **cold-load an *embedded* dashboard from the
   consumer origin and confirm no `401` on chart/filter requests** (that 401 is the
   `SameSite` cookie in step 2). Embedding does not depend on GAQ either way.

---

## 25. AI Assistant (embedded MCP agent) — deployment & security

The target build carries an embedded AI Assistant: an in-process LangGraph ReAct
agent (`superset/ai_assistant/`) that calls Superset's MCP tools
(`superset/mcp_service/`) **inside the Gunicorn worker** — no separate MCP container
or HTTP hop for this path. It is a powerful internal feature; deploy it as such.

**Enable + gate (two layers):**
- `FEATURE_FLAGS["AI_ASSISTANT"] = True` turns it on; when off, the widget doesn't
  render and `/api/v1/ai/*` returns 404.
- `AI_ASSISTANT_ALLOWED_ROLES` (default `["Admin", "Alpha"]`) controls who may use
  it; `Admin` always passes.

**Security — treat allowed roles as "may drive powerful tooling":** the MCP
tool-call path's own docs state that per-tool authorization is **not yet
implemented** (`mcp_auth_hook` has open TODOs for permission checks, JWT scope
validation, and audit logging). Access control effectively stops at "is this an
allowed, authenticated user," and such a user can invoke all ~19 tools (generate
charts, list/query datasets…) with the app's privileges. Therefore:
- **Never add the guest/embed role (`GUEST_ROLE_NAME` — `embedded_viewer`/`Gamma`)
  to `AI_ASSISTANT_ALLOWED_ROLES`.** Keep it to internal staff roles.
- **Verify the chat widget does not render inside the `/embedded/` iframe** — guests
  must never get a chat box wired to MCP tools. (The widget mounts on the Dashboard
  and Explore pages and is flag-gated client-side; confirm it stays out of embeds.)

**New runtime dependency — an LLM:** the ReAct loop makes outbound LLM calls, so the
server needs network **egress to that provider** and an **API key/config**, kept in
`.env-local`/`.env` (never in a tracked file, same hygiene as the JWT secrets).
Budget for the provider's cost and rate limits.

**Worker/concurrency:** tool calls run synchronously via `asyncio.run()` in the
request worker, and a chat turn holds an **SSE stream open for the whole turn**
(seconds to minutes), tying up a `gthread` worker thread the entire time and
competing with dashboard chart bursts. Size `SERVER_THREADS_AMOUNT` with chat load
in mind, keep the gunicorn/`SUPERSET_WEBSERVER_TIMEOUT` long enough for streaming,
and load-test that a few concurrent chats don't starve dashboard rendering.

**Build deps (same venv rule as §21a):** `langgraph`/`langchain` must install into
`/app/.venv` (the psycopg2 lesson applies identically). And a still-live import
trap when extending `agent.py`: `from langgraph.prebuilt import create_react_agent`
— **not** `langchain.agents.create_react_agent`, which does not exist in the pinned
version. The `MCP_SERVICE_HOST/PORT/DEV_USERNAME` env vars are **not** needed for
the embedded widget (in-process); they only matter for the standalone MCP server
used by external clients.

**Quick health checks:**
```bash
docker compose logs superset | grep -iE "Loaded .* MCP tools"     # "Loaded N MCP tools (in-process)" = healthy; "Loaded 0" = registration failed
curl -f http://localhost:8088/api/v1/ai/health                    # AI endpoint up (feature flag on)
```

---

### Appendix — everyday commands (**[HOST]**)

```bash
docker compose up -d                 # start / apply changes
docker compose ps                    # status + health
docker compose logs -f superset      # follow app logs
docker compose restart superset      # graceful restart one service
docker compose exec superset bash    # shell inside the app container
docker compose down                  # stop (keeps named volumes/data)
docker compose pull && docker compose up -d   # infra image refresh
./scripts/healthcheck.sh             # full status roll-up
```

Graceful restarts: `restart: unless-stopped` plus `stop_grace_period: 60s` on the
web/worker services lets in-flight requests and tasks finish before shutdown.
