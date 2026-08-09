# Operations

Run all commands from the repository root. The examples use both the base and
self-host Compose files:

```bash
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env ps
curl -fsS http://127.0.0.1:18889/healthz
curl -fsS http://127.0.0.1:18889/api/v3/state
docker compose -f compose.yaml -f compose.selfhost.yaml --env-file deploy/.env run --rm engine krabville-manage diagnose
```

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

Database migrations are additive and run on startup. Make an online backup
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
- A model-degraded state does not stop deterministic simulation time.
- A completed or operator-paused season should not be treated as a crash.

## Storage and logs

Container logs rotate at 5 MB with two files per service. Runtime databases,
reports, and posters are the only persistent application data. Periodically
inspect `docker system df`, prune only unreferenced build cache or images, and
never prune a rollback image until the replacement has passed live checks.
