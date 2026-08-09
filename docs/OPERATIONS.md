# Operations

Run all commands from the repository root. The examples use both the base and
self-host Compose files:

```bash
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env ps
curl -fsS http://127.0.0.1:18889/healthz
curl -fsS http://127.0.0.1:18889/metrics
curl -fsS http://127.0.0.1:18889/api/v3/state
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env run --rm engine krabville-manage diagnose --json
```

`/livez` proves only that the API process can answer. `/readyz` requires a valid
database and deliberately does not gate engine startup on tick freshness.
`/healthz` additionally requires a fresh running-season tick heartbeat and no
expired model leases. `/metrics` exposes the same bounded checks in Prometheus
text format. `KRABVILLE_TICK_STALE_SECONDS=0` uses the safe automatic bound of
20 configured tick intervals, never less than 60 seconds; set a positive value
only when an intentionally slow deployment needs a wider bound.

## Online backup

SQLite WAL permits an online, transactionally consistent backup while the
simulation runs. This command writes a timestamped database beside the live
database without copying transient `-wal` or `-shm` files:

```bash
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env exec -T engine \
  python -c "import datetime,sqlite3; p='/data/backup-'+datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')+'.db'; s=sqlite3.connect('/data/krabville.db'); d=sqlite3.connect(p); s.backup(d); d.close(); s.close(); print(p)"
```

Keep only the backups your own retention policy requires. Posters and completed
season data live under the configured data directory.

## Upgrade

```bash
git fetch --tags origin
git pull --ff-only
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env build --pull
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env --profile inference up -d
curl -fsS http://127.0.0.1:18889/healthz
```

Database migrations are additive and owned by the one-shot `migrate` service.
Web, engine, and inference remain stopped if bootstrap or checksum validation
fails. See [Migration bootstrap](MIGRATION_BOOTSTRAP.md). Make an online backup
before an upgrade. Do not delete the previous image until the health endpoint,
public state, live tick advancement, and inference queue have all been checked.

## Rollback

Record the working Git commit and image ID before upgrading. To roll back code,
check out that commit, rebuild, and recreate the services. If the newer release
introduced an incompatible migration, restore the pre-upgrade database backup
only while all three services are stopped.

## Expected states

- `web` and `engine` should be running and healthy during an active season.
- `inference` may exit successfully after the configured final season. That is
  healthy and prevents post-season calls.
- On systemd hosts, install both `deploy/krabville-compose.service` and
  `deploy/krabville-inference.service`. The first health-gates web and engine;
  the second starts and supervises inference only after those gates pass.
- A model-degraded state does not stop deterministic simulation time.
- A completed or operator-paused season should not be treated as a crash.

## Authoritative tick incidents

An exception inside one deterministic tick rolls its transaction back and is
retried at the same tick. Krabville stores only the component, exception class,
attempt count, and timestamps; exception text is not retained. A successful
retry resolves the incident automatically. Three failures at the same tick
pause the season without advancing world time, make `/healthz` degraded, and
surface the incident through `diagnose --json` and `/metrics`. Correct the
fault, then use the existing `resume` control operation to retry that tick.

## Storage and logs

Container logs rotate at 5 MB with two files per service. Runtime databases,
reports, and posters are the only persistent application data. Periodically
inspect `docker system df`, prune only unreferenced build cache or images, and
never prune a rollback image until the replacement has passed live checks.
