## Battlezone: Combat Commander Live Sessions & Analytics — Technical Specification (Living Doc)

### Summary / Introduction

This document defines the end-to-end plan for a Python/Flask web application that ingests real-time Battlezone: Combat Commander (BZCC) session data, enriches it with Steam/GOG metadata, mirrors and serves all game assets independently (no hotlinking), exposes a live GameWatch UI and a public API, and stores historical data forever for analytics.

Major components:
- API & Web UI (Flask) with WebSockets realtime fanout and SSE fallback
- Background worker (polling, enrichment, asset mirroring, backfills)
- Redis (cache + queues + pub/sub)
- Postgres (OLTP + time-series partitions + materialized views)
- Object storage + CDN for mirrored assets (hash-addressed, immutable)
- Provider-agnostic auth (Steam SSO first; GOG later)
- Zero hotlinking asset pipeline (seeded by community data; augmented via enrichment)

References (for behavior, data, and UX ideas):
- RakNet source (BZCC): `http://raknetsrv2.iondriver.com/lobbyServer?__pluginShowSource=true&__pluginQueryServers=true&__pluginShowStatus=true`
- Output inspiration: [MultiplayerSessionList BZCC sessions](https://multiplayersessionlist.iondriver.com/api/1.0/sessions?game=bigboat:battlezone_combat_commander)
- GameWatch examples: [battlezone.report BZCC](https://battlezone.report/games/bzcc), [BZCC-Website live](https://battlezonescrapfield.github.io/BZCC-Website/) and [repo](https://github.com/BattlezoneScrapField/BZCC-Website)
- Seed maps: [vsrmaplist.json](https://battlezonescrapfield.github.io/BZCC-Website/data/maps/vsrmaplist.json)
- Secondary enrichment (never hotlinked at runtime): `https://gamelistassets.iondriver.com/bzcc/getdata.php?map=<map>&mod=<modId>` (example: [vsr4pool + VSR](https://gamelistassets.iondriver.com/bzcc/getdata.php?map=vsr4pool&mod=1325933293))

This is a living document. Any architectural or technology changes (e.g., swapping Postgres for MySQL) must be reflected here.

---

## 0. Preparation / Pre-Launch Checklist (Set me up for success)

What you should provision/configure before development and deployment. Keep base URLs and secrets in environment variables (never in code). If you are a solo user on Render, your Personal account works as the account context (a "team" is optional and can be created later via the avatar menu → Switch Team → New Team). Everything below works in a Personal account.

- Accounts
  - Render: use your Personal account (or create a Team later if you want isolation or member management). Enable services for Web, Worker, Postgres, Redis.
  - GitHub: create repo; enable Render GitHub integration with auto-deploys on `main` and PR previews.
  - Steam Web API Key: log in to Steam, visit `https://steamcommunity.com/dev/apikey`, provide a domain (for development you can use a placeholder like `localhost` or your future domain), accept terms, and record the key in `STEAM_API_KEY`.
  - GOG Galaxy OAuth (optional now): register an application in the Galaxy developer portal; capture `GOG_CLIENT_ID` and `GOG_CLIENT_SECRET` for later.
  - Object storage + CDN: choose S3 + CloudFront or Cloudflare R2 + CDN. Create a bucket, an access key/secret, and a CDN distribution. Decide `ASSETS_CDN_BASE` (e.g., `https://assets.battlezonecc.gg`).
  - Monitoring (optional but recommended): Sentry project for error tracking; uptime checks (e.g., Better Uptime).

- Domain & DNS (when ready)
  - Purchase `battlezonecc.gg` (or alternative). Keep domain configurable; do not hardcode.
  - Create subdomains:
    - `api.battlezonecc.gg` → CNAME to Render Web Service hostname
    - `assets.battlezonecc.gg` → CNAME to CDN distribution hostname
  - Later, set `APP_BASE_URL` and `ASSETS_CDN_BASE` to these values in Render.

- Local development setup
  - Python 3.11+, virtualenv, and `.env` file for secrets.
  - Postgres and Redis (Docker compose or native installs).
  - Optional local object storage (MinIO) or filesystem storage (`ASSETS_STORAGE=file`) for assets.

- Render services (baseline sizing; adjust later)
  - Web Service: small instance (0.5–1 vCPU, 512MB–1GB), health check `GET /healthz`.
  - Background Worker: small instance (0.5 vCPU, 512MB).
  - Managed Redis & Postgres: starter tiers.
  - Environment Groups: store shared env vars (`DATABASE_URL`, `REDIS_URL`, `STEAM_API_KEY`, `APP_BASE_URL`, `ASSETS_CDN_BASE`, etc.).

- Minimal env var set (dev or prod)
  - `RAKNET_URL=http://raknetsrv2.iondriver.com/lobbyServer?__pluginShowSource=true&__pluginQueryServers=true&__pluginShowStatus=true`
  - `POLL_INTERVAL_SECONDS=5`
  - `STEAM_API_KEY=<your_steam_key>`
  - `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`
  - `APP_BASE_URL`, `WS_ALLOWED_ORIGINS`
  - `ASSETS_STORAGE=file|s3|r2`, `ASSETS_BUCKET`, `ASSETS_CDN_BASE`
  - `GETDATA_ENDPOINT_BASE=https://gamelistassets.iondriver.com/bzcc/getdata.php`
  - `ENRICHMENT_ENABLED=true`

---

## 1. Goals & Non-Goals

### Goals
- Real-time GameWatch for BZCC sessions with 5s updates
- Historical data retention forever for analytics (player time, map popularity, mod adoption, session durations)
- Full independence: poll RakNet directly; enrich via Steam/GOG; mirror all assets (no hotlinking)
- Provider-agnostic auth (Steam first, GOG later) for user features and curation
- Modern UI inspired by in-game HUD (purple/magenta accents, metal frames, cyan highlights)

### Non-Goals (initially)
- Generating thumbnails from game files (may come later)
- Ingesting non-BZCC games
- Exposing administrative APIs publicly

---

## 2. High-Level Architecture

- `api-web` (Flask): REST endpoints, Web UI (Jinja + HTMX/Alpine), WebSockets (Flask-SocketIO) with Redis pub/sub, SSE fallback
- `worker` (Celery or RQ): polling RakNet every 5s; enrichment (Steam/GOG, map/mod, asset mirroring); backfills; scheduled maintenance
- `redis` (Render “Key Value” service; Redis-compatible): cache for hot lookups; message bus for WS; task broker (if Celery) or queue (if RQ)
- `postgres`: primary data store; monthly partitions for time-series; materialized views for analytics
- `object storage` + `CDN`: mirrored assets served from `ASSETS_CDN_BASE` (e.g., `assets.battlezonecc.gg`), content-addressed by hash

Rationale: This “boring” web + worker + cache + DB + object-storage pattern scales predictably, isolates concerns, supports realtime and forever history, and is low-cost on Render.

---

## 3. Data Ingestion & Normalization

### 3.1 Polling
- Interval: 5 seconds (configurable via `POLL_INTERVAL_SECONDS`)
- Source: RakNet JSON (see reference URL above)
- Steps:
  1. Fetch JSON; short-timeout and retry with jitter
  2. Ignore placeholders (e.g., `NATNegID == "XXXXXXX@XX"`)
  3. Compute stable `session_id = <source>:<nat_guid_hex16>`
  4. Normalize fields: state (PreGame/InGame/PostGame), version, NAT type, TPS, ping caps, game type/mode, map key `${mod_id}:${map_file_lower}`
  5. Upsert `sessions` and `session_players`; emit diffs over WebSockets

### 3.2 Enrichment (async)
- Steam player summaries (batch; cache hours–days)
- GOG profiles (added after Steam)
- Map/Mod metadata resolution:
  - Seed: ingest [vsrmaplist.json](https://battlezonescrapfield.github.io/BZCC-Website/data/maps/vsrmaplist.json)
  - Secondary: call `getdata.php` for `(map, mod)` pairs to pull `image`, `title`, `description`, `netVars`, and mod info
  - Workshop: GetPublishedFileDetails for mod previews
- Asset mirroring: download external images once; validate; hash; store; update DB to our CDN URL

### 3.3 Independence
- Runtime API/UI only serve assets from our domain; external endpoints are used by enrichment jobs only

---

## 4. Data Model (Initial)

Entity tables:
- `players` (id, display_name, avatar_url, created_at, updated_at)
- `identities` (id, player_id, provider ['steam','gog'], external_id, raw, profile_url, unique(provider, external_id))
- `mods` (id, name, workshop_id, image_url, url, dependencies jsonb)
- `maps` (id, key `${mod_id}:${map_file}`, map_file, mod_id, name, description, size_meta jsonb, image_url, aliases jsonb)
- `sessions` (id, source, name, message, state, nat_type, tps, version, level_map_id, attributes jsonb, started_at, last_seen_at, ended_at)
- `session_mods` (session_id, mod_id, role ['major','minor'])
- `session_players` (session_id, player_id, slot, team_id, is_host, stats jsonb)
- `assets` (hash, mime, bytes, width, height, source_url, stored_url, created_at)
- `curation_queue` (id, kind ['map','mod','image'], key, status, note, created_at)

Team Picker (planned):
- `team_pick_sessions` (id, session_id, state ['open','final','canceled'], coin_winner_team, created_at, created_by_user_id, closed_at)
- `team_pick_picks` (id, pick_session_id, order_index, team_id, player_steam_id, picked_by_user_id, picked_at)
- `team_pick_participants` (pick_session_id, user_id, role ['commander1','commander2','viewer'])

Time-series (monthly partitions):
- `session_snapshots` (snapshot_ts, session_id, state, player_count, map_id, mod_ids, attrs jsonb)
- `player_session_events` (player_id, session_id, joined_at, left_at, cumulative_seconds)

Indexes: by `(last_seen_at)`, `(snapshot_ts)`, `(player_id, snapshot_ts)`, `(map_id, snapshot_ts)`; unique keys on natural identifiers; GIN on jsonb where useful.

Materialized views:
- `mv_player_time_daily`, `mv_map_popularity_daily`, `mv_mod_usage_daily`, `mv_session_duration_stats`

Note: If the database technology changes (e.g., to MySQL), we will update this section with equivalent partition/rollup strategy and feature parity notes.

---

## 5. API (v1)

### Public endpoints
- `GET /api/v1/sessions/current` — live sessions with embedded refs (map/mod/player identity stubs)
- `GET /api/v1/sessions/{id}` — full session detail
- `GET /api/v1/history/summary?minutes=N` — per‑minute aggregates of sessions and players for the last N minutes (default 60)
- `GET /api/v1/players/{player_id}` — identities, avatar, aggregates
- `GET /api/v1/maps` and `/api/v1/maps/{id}` — metadata + image
- `GET /api/v1/mods` and `/api/v1/mods/{id}` — metadata + image/dependencies
- `GET /api/v1/history/sessions` — time-window filter, paging
- `GET /api/v1/history/players/{player_id}` — time-series (playtime, games)

Presence (planned):
- `GET /api/v1/presence/site` — list of users currently online on the site
- `GET /api/v1/presence/in_game` — mapping of `session_id -> [players]` currently in verified sessions

Team Picker (planned):
- Read-only (public):
  - `GET /api/v1/team_picker/{session_id}` — current pick session state and picks (visible to all users, including non‑logged‑in)
- Commander actions (auth; user must be a verified commander in this session):
  - `POST /api/v1/team_picker/{session_id}/start` — create or restart a pick session (invalidates prior picks)
  - `POST /api/v1/team_picker/{session_id}/coin_toss` — cryptographically random coin toss to decide first pick
  - `POST /api/v1/team_picker/{session_id}/pick` — body: { player_steam_id }
  - `POST /api/v1/team_picker/{session_id}/finalize` — each commander may accept; when both accept, state = `final`
  - `POST /api/v1/team_picker/{session_id}/cancel` — cancel an open pick session

### Realtime
- `WS /realtime` rooms: `sessions`, `session:{id}`, `players:{id}`
- SSE fallback: `GET /api/v1/stream/sessions`

Team Picker (planned):
- Room: `team_picker:{session_id}`
- Events: `init`, `coin_toss`, `pick`, `finalize`, `cancel`

### Admin/curation (secured)
- `POST /admin/curation/maps` — propose/override map metadata/image
- `POST /admin/assets` — upload/replace images
- `GET /admin/tools/health` — consolidated status (RakNet fetch ok?, DB/Redis ok?, queue depth)
- `GET /admin/tools/raknet/sample` — fetch and return the raw RakNet payload (redacted) for debugging
- `GET /admin/db/snapshots` — paged listing for `session_snapshots` (filters: time window, session)
- `GET /admin/sessions` — paged sessions with filters (state, map, mod, q)
- `GET /admin/logs` — recent worker/app logs (tail, streaming)

Versioning: prefix paths with `/api/v1/`; future breaking changes → `/api/v2/`.

### Users & Permissions

Roles: `user`, `curator`, `admin`.

Logged-in user capabilities (Steam SSO first; GOG later):
- Link identities (Steam now, GOG later) to a local account
- Personal profile page (public): avatar, display name, recent sessions
- Favorites/watchlist: follow sessions/hosts/maps/mods; receive live updates in UI
- Saved filters and dashboard presets
- Propose metadata corrections (map names/descriptions) and upload candidate thumbnails (goes to curation queue)
- Team Picker: commanders can start/operate picks; everyone (including non‑logged‑in) can view the read‑only Team Picker for any active session

Curator capabilities (subset of admin powers, content-focused):
- Review/approve/reject curation submissions
- Edit map/mod metadata; trigger asset re-mirroring

Admin capabilities:
- All curator powers
- Manage users/roles; revoke/ban abusive accounts (soft-delete)
- Toggle feature flags (e.g., enable/disable `ENRICHMENT_ENABLED`)
- Operational controls: trigger backfills, replays, seed re-ingest; flush selective caches
- Configure polling interval/backoff caps via env; pause poller if needed
- Access observability dashboards: queue depth, error rates, WS connections, DB health

---

## 6. Realtime Delivery

Primary: WebSockets (Flask-SocketIO + Redis). Fallback: SSE.
- Connect → send snapshot; then 5s deltas and on-change pushes
- Diff format: minimal fields changed since last tick per entity
- Backpressure: bound message size; drop-to-snapshot on overflow
 
Backoff policy (approved):
- Poller (RakNet): baseline every 5s. On consecutive failures: 10s → 20s → 30s → 60s (max), with ±20% jitter. On success, immediately reset to 5s. While degraded, UI shows a “stale data” banner after 30s without fresh data.
- Enrichment (Steam/GOG/getdata/workshop): exponential backoff starting at 1s → 2s → 4s → 8s → … up to 5 minutes max, with jitter; respect `Retry-After` headers; cap retries at 6 attempts per item before parking it for later.

---

## 7. Asset Pipeline (Zero Hotlinking)

Priority when resolving a thumbnail/preview:
1) Our registry (DB + bucket)
2) Seed `vsrmaplist.json` (mirror once)
3) `getdata.php` (`image` and `mods/<id>/mod.png`) — mirror once
4) Steam Workshop preview — mirror once
5) Placeholder + curation queue

Integrity & storage:
- Validate MIME/size; compute sha256; store under `/bzcc/<kind>/<sha>.<ext>`
- Immutable objects; DB references updated to `ASSETS_CDN_BASE`
- Nightly integrity/dedupe sweep; quarantine on repeated failures
 
Policy (approved): never hotlink. All external assets are fetched once by enrichment jobs, validated, and mirrored to our bucket/CDN. Runtime responses only reference our `ASSETS_CDN_BASE`.

---

## 8. Auth & Accounts

- Provider-agnostic SSO: Steam first (OpenID/OAuth depending on lib), GOG later (Galaxy OAuth)
- Link identities to canonical `players`
- Roles: `admin`, `curator`, `user`
- Privacy: only public profile data (display name, avatar, profile URL); support deletion on request
 
SSO order (approved): Steam first; GOG added later. The identity & roles model is provider-agnostic to avoid refactors.

---

## 9. Observability, Reliability, Security

Metrics:
- Poll success/latency, enrichment queue depth/latency, WS connection count, DB read/write latencies, asset mirror success

Reliability:
- Retries with exponential backoff + jitter; circuit breakers for Steam/GOG
- Fallback to last-good sessions when RakNet blips; degraded mode banners in UI

Security:
- Rate limiting; CORS; WS origin checks; secure cookies; CSRF on forms
- Signed admin uploads; input validation; sanitize external descriptions (allowlist)
- Secrets only via env vars; no secrets in repo

---

## 10. Local Development & Deployment (Render)

Local (Windows-friendly):
- Python 3.11+, venv, `.env`
- Postgres + Redis via Docker or native
- Local object storage: MinIO or filesystem backend (`ASSETS_STORAGE=file`)
- Run `api-web` and `worker` concurrently; dev WebSockets; hot reload

Render (CI/CD via GitHub pushes):
- Services: Web Service (Flask), Background Worker, Redis (managed), Postgres (managed)
- Optional: static site for docs/demo; object storage on S3/R2 with CDN
- Preview environments for PRs; Production on `main`

Key environment variables

Minimum (before first run):
- `SECRET_KEY` — long random string for Flask session/signing
- `RAKNET_URL` — `http://raknetsrv2.iondriver.com/lobbyServer?__pluginShowSource=true&__pluginQueryServers=true&__pluginShowStatus=true`
- `POLL_INTERVAL_SECONDS` — `5`
- `ENRICHMENT_ENABLED` — `true`
- `ASSETS_STORAGE` — `file` (switch to `s3` or `r2` later)
- `GETDATA_ENDPOINT_BASE` — `https://gamelistassets.iondriver.com/bzcc/getdata.php`
- `APP_BASE_URL` — e.g., your Render URL `https://<service>.onrender.com`
- `WS_ALLOWED_ORIGINS` — comma-separated allowed origins (Render URL and, later, custom domains)

Auto-provided when you attach services:
- `DATABASE_URL` — Render Postgres connection string
- `REDIS_URL` — Render Redis connection string

Optional / when ready:
- `STEAM_API_KEY` — enables Steam enrichment
- `GOG_CLIENT_ID`, `GOG_CLIENT_SECRET` — add when implementing GOG
- `ASSETS_CDN_BASE` — set after creating CDN (e.g., `https://assets.battlezonecc.gg`)

Object storage configuration (choose one when not using `file`):
- If `ASSETS_STORAGE=s3`: `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT` (optional), `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
- If `ASSETS_STORAGE=r2`: `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`

Notes:
- `PORT` is set by Render automatically and used by Gunicorn via `--bind 0.0.0.0:$PORT`.

Domains:
- Plan for `battlezonecc.gg` later; keep base URLs in env to avoid code changes
 
Cost posture (approved): start with the smallest viable instances; scale by increasing worker concurrency, cache TTLs, and DB/storage tiers only when metrics indicate need.

---

## 11. Cost & Scaling Posture

Early stage (low traffic):
- Web: 0.5–1 vCPU, 512MB–1GB RAM
- Worker: 0.5 vCPU, 512MB RAM
- Postgres + Redis: starter tiers
- Object storage + CDN: minimal cost; cache aggressively

Monthly estimate: low tens of USD total, scaling linearly with traffic/data retention.

Knobs to control cost:
- Enrichment concurrency; prewarm limits; cache TTLs; WS broadcast scope; snapshot granularity (remains 5s for accuracy unless constrained)

---

## 12. Roadmap & Milestones

- M0: Scaffolding, health checks, local Postgres/Redis, env wiring
- M1: Poller → normalized sessions + session_players; `GET /api/v1/sessions/current`; basic GameWatch (no enrichment)
- M2: Steam enrichment + cache; WebSockets fanout; Steam SSO
- M3: Seed ingest (`vsrmaplist.json`); map/mod resolution; asset mirroring; replace external URLs
- M4: Snapshots + partitions; materialized views; first analytics pages
- M5: GOG enrichment + SSO; curator dashboard for metadata/assets
- M5.1: Admin utilities: health dashboard, RakNet tester, DB browser for sessions/snapshots, cache controls
- M6: Hardening (retries/backoff, metrics, alerts); perf pass; preview deploys

Success criteria per milestone will be tracked alongside issues/PRs.

---

## 13. Risks & Mitigations

- Steam/GOG limits → batching, TTL caches, backoff, circuit breakers
- Asset coverage gaps → curator workflow, placeholders, nightly reports
- Storage growth → partitions, rollups, optional compression; observe and tune
- Realtime scale → WS rooms via Redis; cap message sizes; SSE fallback

---

## 14. UI/UX Principles

- Aesthetic: modern “tactical HUD” inspired by in-game screens (purple/magenta, metallic frames, cyan glow)
- Components: GameWatch grid → session drawer; filters; analytics dashboards (ECharts)
- Motion: subtle parallax and micro-animations; respect reduce-motion
- Accessibility: high-contrast variant; keyboard nav; ARIA labels

---

## 15. Change Management (Living Doc)

- Any significant change (DB, auth providers, realtime transport, data model) requires updating this document before implementation
- Keep a `Changelog` section with date, change, and rationale

#### Changelog
- 2025-08-10: Initial version
- 2025-08-10: Added Preparation checklist; defined user/curator/admin capabilities; documented approved policies (no hotlinking, WS+SSE, 5s polling) and detailed backoff strategy; clarified SSO order and cost posture.
- 2025-08-10: Implemented base web API + worker; added `/api/v1/sessions/current`, SSE stream, basic GameWatch UI; added `levels`/`mods` tables; created `session_snapshots` and history summary endpoint; enabled asset mirroring to local `/static/assets`; added Steam enrichment groundwork (GetPlayerSummaries) and API hydration for Steam identity; added Admin utilities plan (health/raknet/db tools).
- 2025-08-12: Planned Presence endpoints and Team Picker feature (public read‑only view; commander‑only actions; finalize flow that does not modify main GameWatch UI; optional status indicator when in‑game team assignments match finalized roster). Added data model stubs and realtime rooms for Team Picker.
- 2025-08-13: Implemented Team Picker backend scaffold: SQLAlchemy tables (`team_pick_sessions`, `team_pick_picks`, `team_pick_participants`) and v1 endpoints (`GET /api/v1/team_picker/{session_id}`, POST `start`, `coin_toss`, `pick`, `finalize`, `cancel`). Realtime emits on `team_picker:update` to room `team_picker:{session_id}` when WS enabled.

---

## Implementation Status (current)

- Completed
  - Poller every 5s; normalized sessions/players; SSE stream
  - `/api/v1/sessions/current`, `/api/v1/sessions/{id}`
  - Map/mod enrichment (title + image) via getdata; local asset mirroring
  - DB: `levels`, `mods`, `session_snapshots`; history summary endpoint
  - UI: GameWatch grid, filters, team/FFA views; mini history chart
  - Dev tooling: `dev.ps1`, localhost hints; living tech spec maintained

- In progress
  - Steam identity enrichment → display avatars/nicknames in UI
  - Admin Tools pages (health, RakNet tester, DB browser)

- Next
  - WebSockets fanout; partitioning for snapshots; analytics pages


