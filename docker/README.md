# Docker — PIT Market Intelligence Platform

Two Dockerfiles + two compose files ship in this directory.

## Files

| File | Purpose |
|---|---|
| `docker/Dockerfile.api` | FastAPI + PIT runtime image (Python 3.12, uv-based install) |
| `docker/Dockerfile.web` | Next.js 14.2 production image (multi-stage node:20-bookworm-slim) |
| `docker-compose.yml` | **Full prod stack** — API + Redis + Postgres + MinIO + Dagster (port 8000) |
| `docker-compose.dev.yml` | **Dev profile** — API + Web only, no external services (ports 8700/8701) |

## Build & Run — Dev Profile

```bash
docker compose -f docker-compose.dev.yml up -d --build
curl http://127.0.0.1:8700/health   # API up
curl http://127.0.0.1:8701/         # Web up
docker compose -f docker-compose.dev.yml logs -f pit-api
docker compose -f docker-compose.dev.yml down -v
```

## Build & Run — Prod Profile

The prod compose (`docker-compose.yml`) was authored for the Phase 5 stack
(Redis cache + S3-compatible object store + Postgres metadata + Dagster
orchestration). It maps API to **port 8000**. Use it when you have all the
backing services ready:

```bash
docker compose up -d --build
docker compose ps
```

## Local NAS Caveat (this environment)

- `trim.openclaw` user **is in the docker group** (verified 2026-07-23).
  `/var/run/docker.sock` is owned by `root:docker` mode 0660; the user can
  invoke docker via `sg docker -c "docker …"` or after `newgrp docker`.
- **Verified end-to-end (2026-07-23)**: `docker compose -f docker-compose.dev.yml
  up -d --build` brings up API + Web on 8700/8701, both healthy. DeepSeek
  analyze via `POST /v1/analyses {provider: "deepseek"}` returns PUBLISHED
  finding with real LLM call from inside the container.
- Two image build fixes were required (committed):
  1. `Dockerfile.api` — copy `src/` BEFORE `uv sync` (setuptools 77+ needs
     `egg_base` to exist; previously `uv sync` ran before src was mounted).
  2. `Dockerfile.web` — added `frontend/public/.gitkeep` so the COPY in the
     runtime stage resolves.
  3. `frontend/package.json` — `start` now uses `${PORT:-3001}` so Docker
     (`PORT=3000` from `Dockerfile.web`) binds the expected port.
- For non-Docker dev: native `uvicorn` + `next dev` on 8700/8701 still works
  via `scripts/dev-start.sh`.

## LLM Secrets (Optional)

For `POST /v1/analyses` with `provider: "deepseek" | "openai"` to actually
call the LLM, the API container needs `DEEPSEEK_API_KEY` (and optionally
`OPENAI_API_KEY`). Pull them from the workspace secrets file:

```bash
bash scripts/setup-env-docker.sh    # writes .env.docker (chmod 600)
docker compose -f docker-compose.dev.yml up -d   # picks up env_file
```

`.env.docker` is gitignored. Missing file → analyze falls back to `mock`
provider (no network calls, valid for development).

## Image Sizing Notes

- API image uses `uv sync --no-dev --extra etl --extra llm`. Excludes `dev`
  (pytest/ruff/mypy), `research` (xgboost/optuna — heavy ML deps the API
  doesn't need at runtime). Now also includes `jsonschema` and `nbformat`
  in `etl` (used by registry + notebook lineage code at import time).
- Web image is 3-stage: deps → build → runtime. The runtime stage carries
  only `node_modules + .next + public + manifest`, not the build cache.
- Both images run as non-root user (`uid 1001`) for defense-in-depth.

## Verified

- 2026-07-23: `pit-market/api:dev` 1.48 GB, `pit-market/web:dev` 984 MB,
  built + started via `docker compose -f docker-compose.dev.yml up -d`.
- API container healthchecks via `/health` (200 OK).
- Web container serves `/` on port 8701 → container port 3000 (200 OK).
- Real DeepSeek call inside container → PUBLISHED finding in ~4s.