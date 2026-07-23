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

- `trim.openclaw` user is **not in the docker group**; `/var/run/docker.sock`
  is owned by `root:docker` with mode 0660 → direct `docker build` fails.
- `sudo` requires a password (not passwordless), so `sudo docker …` is also
  blocked.
- **Workaround**: ask admin to either (a) `usermod -aG docker trim.openclaw`
  then re-login, or (b) install `podman` and use rootless mode.
- Until then, this repo uses native `uvicorn` + `next dev` on ports 8700/8701
  (see `scripts/dev-start.sh`). The Dockerfiles here are written and committed
  for any environment that *can* run them.

## Image Sizing Notes

- API image uses `uv sync --no-dev --extra etl --extra llm`. Excludes `dev`
  (pytest/ruff/mypy), `research` (xgboost/optuna — heavy ML deps the API
  doesn't need at runtime).
- Web image is 3-stage: deps → build → runtime. The runtime stage carries
  only `node_modules + .next + public + manifest`, not the build cache.
- Both images run as non-root user (`uid 1001`) for defense-in-depth.

## Verified

- `docker buildx debug` not available without daemon → Dockerfile syntax was
  validated by review and by mirroring the local `uv` install steps.
- The local NAS dev profile (8700/8701) was used to write + test the runtime
  commands inside the images; commands match the dev-start.sh entry points.