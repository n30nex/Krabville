# KVsim 2.3 Release Baseline

This document locks the source, runtime, database, public API, asset, and validation baseline for the KVsim 2.3 backlog. It is the acceptance reference for `KV23-001` and all dependent work.

## Exact source baseline

| Item | Value |
| --- | --- |
| Branch | `main` |
| Release | `v2.2.1` |
| Commit | `f630a9502b029097deeecbbc85b0f74aca4e99f9` |
| Package/frontend/image version | `2.2.1` |
| Database migration | `013_kvsim_v22_depth.sql` |
| Python | `>=3.13` |
| FastAPI | `0.141.1` |
| Phaser | `3.90.0` |
| TypeScript | `7.0.2` |
| Vite | `8.2.1` |

`v2.2.1` differs from `v2.2.0` only in deployment reliability. Production starts web, then engine, then the separately systemd-supervised inference worker. A worker failure restarts only inference. The schema and simulation behavior remain the v2.2 baseline.

## Production baseline

- Public origin: `https://krab.canadaverse.org`
- Local web port: `127.0.0.1:18889`
- Deployment root: `/opt/canadaverse/krabville-v2`
- Services: `krabville-compose.service` and `krabville-inference.service`
- Containers: `krabville-web-1`, `krabville-engine-1`, and `krabville-inference-1`
- Primary model: `gpt-5.3-codex-spark` at low reasoning
- Fallback model: `gpt-5.6-luna` at low reasoning
- Hard per-season guards: 150 attempts and 1,500,000 tokens
- Auto-continuation hard stop: Season 20

The production database is upgraded in place. Resetting or reseeding it is forbidden. Host reboots are not a normal validation tool; use isolated service, container, fixture, and disposable-restore tests.

## Database baseline

Applied migrations are immutable and ordered from `001_initial.sql` through `013_kvsim_v22_depth.sql`. New v2.3 migrations start at `014` and must be additive.

Required invariants:

- `PRAGMA integrity_check` returns `ok`.
- `PRAGMA foreign_key_check` returns no rows.
- Double-entry/accounting reconciliation remains balanced.
- The active season preserves its seed commitment across deploys.
- Completed seasons retain revealed seeds and one 1920x1080 poster.
- A completed Season 20 cannot create Season 21.
- Model-disabled and fake-provider runs remain functional.

## Public API baseline

Compatibility routes that remain available throughout v2.3:

- `GET /healthz`
- `GET /readyz`
- `GET /api/v3/state`
- `GET /api/v3/events`
- `GET /api/v3/events/stream`
- `GET /api/v3/economy`
- `GET /api/v3/properties/{slug}`
- `GET /api/v3/residents/{slug}`
- `GET /api/v3/relationships`
- `GET /api/v3/polls/current`
- `POST /api/v3/polls/{pollId}/vote`
- `GET /api/v3/seasons`
- `GET /api/v3/seasons/{seasonId}`
- Equivalent retained `/api/v2/*` routes and `/api/krabville/state`

Voting is the only public mutation. New bootstrap, world, story, metrics, and diagnostic routes are additive.

## Asset baseline

The shipped public asset family contains 12 files totaling 29,398,833 bytes:

- Four seasonal `kvsim-town-v21-*.webp` maps
- `residents-a.png` and `residents-b.png`
- `life-stages-v2.png`
- `interiors-v4.png`
- `inventory-items-v2.png`
- `event-props-v21.png`
- `weather-seasons-v1.png`
- `manifest.json`

Source artwork remains under `art/kvsim`. v2.3 may optimize loading and add generated metadata, but it does not replace the visual family or change its provenance.

## Baseline validation commands

```bash
python -m pip install '.[test]'
python -m pytest
python -m pip wheel . --no-deps --wheel-dir dist
cd frontend
npm ci --ignore-scripts
npm run build
npm run test:e2e
docker compose -f compose.yaml -f compose.selfhost.yaml \
  --env-file deploy/.env.example --profile inference config --quiet
```

Production checks use the exact deployed image and database:

```bash
curl -fsS https://krab.canadaverse.org/healthz
curl -fsS https://krab.canadaverse.org/api/v3/state
systemctl is-active krabville-compose.service krabville-inference.service
docker image inspect krabville:2.2.1
```

## Scope lock

KVsim 2.3 implements the ordered backlog in `KVSIM_2.3_IMPLEMENTATION_PLAN.md`. It improves trust, observability, transport efficiency, authoritative explanations, Watch UX, deep links, accessibility, performance, backup/restore proof, and release gates.

The following are explicit non-goals:

- No simulation content expansion or broad rebalance.
- No population, season, attempt, or token-limit increase.
- No new model provider for variety.
- No public free-text prompting or direct resident control.
- No frontend framework rewrite.
- No migration away from SQLite.
- No Phaser 4 merge.
- No destructive database migration or production reset.
- No removal or breaking change to `/api/v3/state`.
- No duplicate client-side decision or coordinate authority.

## Known baseline defects

These are measured baseline issues, not accepted v2.3 behavior:

- The connected client combines SSE with a complete state refresh every five seconds.
- Broad backend/frontend modules have multiple responsibilities.
- Browser CI does not currently run the Playwright matrix.
- Frontend location coordinates and some decision forecasts duplicate backend authority.
- Heavy map/interior/inventory/event assets load too early.
- Runtime health lacks tick freshness, queue details, and actionable incidents.
- The economy summary can report a negative unemployed count when employed records exceed the eligible labor-force count; v2.3 must enforce a non-negative, population-consistent metric.

